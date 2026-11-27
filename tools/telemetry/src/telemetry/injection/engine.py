"""Pure-function injection evaluator for weather, physical, and sensor stages."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Sequence

from ..models import Sample
from .catalog import get_entry
from .envelopes import envelope
from .models import Injection

_RATED_POWER_MAX_KW = 3600.0 * 1.25


def _seeded_unit_noise(turbine_seed: int, salt: str, signal: str, tick: int) -> float:
    """Deterministic uniform draw in [-1, 1] keyed by (turbine, injection, signal, tick)."""
    key = f"{int(turbine_seed)}:{salt}:{signal}:{int(tick)}".encode("utf-8")
    digest = hashlib.blake2b(key, digest_size=8).digest()
    return (int.from_bytes(digest, "big") / float((1 << 64) - 1)) * 2.0 - 1.0


def _clamp_physical(signal: str, value: float) -> float:
    if signal == "active_power_kw":
        return max(0.0, min(_RATED_POWER_MAX_KW, value))
    if signal == "rotor_imbalance_index":
        return max(0.0, min(1.0, value))
    if signal in (
        "wind_speed_ms",
        "rotor_rpm",
        "gearbox_vibration_mm_s",
        "nacelle_vibration_mm_s",
        "main_bearing_vibration",
        "converter_faults",
        "pitch_position_error_deg",
        "blade_pass_hz",
    ):
        return max(0.0, value)
    return value


def weather_deltas(
    injections: Sequence[Injection], asset_time_h: float
) -> tuple[float, float]:
    """Return ``(wind_delta_ms, ambient_delta_c)`` from active weather injections."""
    wind_delta = 0.0
    ambient_delta = 0.0
    for inj in injections:
        entry = get_entry(inj.type)
        if entry.category != "weather":
            continue
        env = envelope(asset_time_h, inj.onset_asset_h, inj.progression, seed=inj.id)
        scale = inj.severity * env
        if scale <= 0.0:
            continue
        for item in entry.weather_inputs:
            if item.op != "add":
                continue
            delta = item.magnitude * scale
            if item.input == "wind_speed_ms":
                wind_delta += delta
            elif item.input == "ambient_temp_c":
                ambient_delta += delta
    return wind_delta, ambient_delta


def has_physical_fault(injections: Sequence[Injection], asset_time_h: float) -> bool:
    """True when at least one physical fault injection is active at ``asset_time_h``."""
    for inj in injections:
        entry = get_entry(inj.type)
        if entry.category not in ("gradual", "sudden"):
            continue
        env = envelope(asset_time_h, inj.onset_asset_h, inj.progression, seed=inj.id)
        if inj.severity * env > 0.0:
            return True
    return False


def apply_physical_injections(
    sample: Sample,
    injections: Sequence[Injection],
    asset_time_h: float,
    onset_pitch_fn: Callable[[float], float] | None = None,
) -> Sample:
    """Apply active physical fault injections to ``sample.true`` (and ``measured``)."""
    if not injections:
        return sample

    true = dict(sample.true)
    meta = dict(sample.meta)
    gearbox_temp_changed = False
    power_changed = False
    any_changed = False

    for inj in injections:
        entry = get_entry(inj.type)
        if entry.category not in ("gradual", "sudden"):
            continue
        env = envelope(asset_time_h, inj.onset_asset_h, inj.progression, seed=inj.id)
        scale = inj.severity * env
        if scale <= 0.0:
            continue

        any_changed = True

        for effect in entry.effects:
            if effect.signal not in true:
                continue
            current = true[effect.signal]
            if effect.op == "add":
                updated = current + effect.magnitude * scale
            elif effect.op == "mul":
                updated = current * max(0.0, 1.0 + effect.magnitude * scale)
            elif effect.op == "set":
                updated = effect.magnitude * scale
            else:
                continue

            true[effect.signal] = _clamp_physical(effect.signal, updated)
            if effect.signal == "gearbox_temp_c":
                gearbox_temp_changed = True
            elif effect.signal == "active_power_kw":
                power_changed = True

        if entry.special == "pitch_seizure":
            frozen_pitch = (
                onset_pitch_fn(inj.onset_asset_h)
                if onset_pitch_fn is not None
                else true["pitch_angle_deg"]
            )
            dt_h = max(0.0, float(asset_time_h) - float(inj.onset_asset_h))
            # Feedback freezes toward onset pitch while commanded pitch keeps tracking wind/time.
            true["pitch_angle_deg"] = (
                (1.0 - scale) * true["pitch_angle_deg"] + scale * frozen_pitch
            )
            commanded_pitch = (
                -0.5
                + 3.5 * 0.5 * (1.0 - math.cos(0.35 * dt_h))
                + 0.6 * max(0.0, true.get("wind_speed_ms", 0.0) - 9.0)
            )
            meta["commanded_pitch_deg"] = commanded_pitch
            mismatch = abs(commanded_pitch - true["pitch_angle_deg"]) * scale
            true["pitch_position_error_deg"] = max(
                true["pitch_position_error_deg"], mismatch
            )

    if not any_changed:
        return sample

    if gearbox_temp_changed and "expected_gearbox_temp" in meta:
        true["gearbox_temp_rise_c"] = (
            true["gearbox_temp_c"] - meta["expected_gearbox_temp"]
        )

    if power_changed and "expected_power_kw" in meta:
        expected = meta["expected_power_kw"]
        true["power_ratio"] = (
            true["active_power_kw"] / expected if expected > 1.0 else 1.0
        )

    return sample.with_true(true).with_meta(meta)


def apply_sensor_injections(
    sample: Sample,
    injections: Sequence[Injection],
    asset_time_h: float,
    turbine_seed: int,
    pre_sensor_fn: Callable[[float], Sample] | None = None,
) -> Sample:
    """Apply sensor-quality modifiers to ``sample.measured`` only, leaving truth intact."""
    if not injections:
        return sample

    measured = dict(sample.measured)
    changed = False

    for inj in injections:
        entry = get_entry(inj.type)
        if entry.category != "sensor":
            continue
        env = envelope(asset_time_h, inj.onset_asset_h, inj.progression, seed=inj.id)
        scale = inj.severity * env
        if scale <= 0.0:
            continue

        signal = str(inj.params.get("signal") or entry.default_params.get("signal") or "")
        if signal not in measured:
            continue

        changed = True
        if entry.sensor_kind == "stuck":
            explicit_held = inj.params.get("held_value")
            if explicit_held is not None:
                held = float(explicit_held)
            elif pre_sensor_fn is not None:
                held = pre_sensor_fn(inj.onset_asset_h).true[signal]
            else:
                held = sample.true[signal]
            measured[signal] = held

        elif entry.sensor_kind == "dropout":
            # 0.0 is the wire model's stand-in for a null sample (Unity JsonUtility).
            measured[signal] = 0.0

        elif entry.sensor_kind == "noise_burst":
            noise_scale = float(
                inj.params.get("scale", entry.default_params.get("scale", 3.5))
            )
            noise = _seeded_unit_noise(turbine_seed, inj.id, signal, sample.tick)
            measured[signal] = measured[signal] + noise * noise_scale * scale

        elif entry.sensor_kind == "bias_drift":
            bias = float(inj.params.get("bias", entry.default_params.get("bias", 12.0)))
            measured[signal] = measured[signal] + bias * scale

    if not changed:
        return sample
    return sample.with_measured(measured)
