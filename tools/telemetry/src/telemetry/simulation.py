"""Layered, deterministic synthetic telemetry for a 3.6 MW class wind turbine.

Every engine tick flows through four stages::

    nominal generator -> physical modifiers -> sensor-quality modifiers -> sample

* The **nominal generator** is a closed-form function of time. It describes a
  healthy machine and nothing else.
* **Physical modifiers** change what the turbine is doing (wear, heat, icing,
  a lightning strike). They update the *true* state.
* **Sensor-quality modifiers** corrupt only what the sensor reports (stuck,
  dropout, noise). They update the *measured* state and leave truth intact.
* The resulting :class:`~telemetry.models.Sample` carries both values, plus
  ``turbine_id`` and ``asset_time_h``.

The physics is illustrative, not certified: the point is plausible,
reproducible signals with recognisable fault signatures.

Sampling is random-access. The canonical engine tick is one **asset-hour**
(0.125 simulation seconds at the demo's eight asset-hours per second), and the
noise helpers are seeded per ``(turbine_seed, signal, tick_index)``. Scrubbing
backward or jumping straight to a tick therefore returns identical data.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .injection.engine import (
    apply_physical_injections,
    apply_sensor_injections,
    weather_deltas,
)
from .injection.models import Injection
from .models import (
    COMPONENT_LABELS,
    DEFAULT_TURBINE_ID,
    UNITS,
    Environment,
    Sample,
    Signal,
)

# Rotor / plant constants for the notional turbine.
ROTOR_DIAMETER_M = 120.0
RATED_WIND_MS = 12.0
CUT_IN_MS = 3.0
CUT_OUT_MS = 25.0
RATED_RPM = 12.6
RATED_POWER_KW = 3600.0
BLADE_PASS_PER_REV = 3
# Gearbox oil temperature expected to sit this far above ambient at idle.
GEARBOX_BASELINE_RISE_C = 44.0

# Time compression used by the demo: one simulated second stands for eight
# asset-hours. The canonical engine grid is one asset-hour per sample.
ASSET_HOURS_PER_SIM_SECOND = 8.0
SIM_SECONDS_PER_ASSET_HOUR = 1.0 / ASSET_HOURS_PER_SIM_SECOND

DEFAULT_TURBINE_SEED = 1


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    label: str
    description: str
    healthy_asset: bool
    onset_s: float
    tags: tuple[str, ...]


SCENARIOS: dict[str, ScenarioSpec] = {
    "nominal": ScenarioSpec(
        id="nominal",
        label="Nominal operation",
        description="Healthy turbine in a steady wind band, no developing fault.",
        healthy_asset=True,
        onset_s=0.0,
        tags=("baseline",),
    ),
    "gearbox_degradation": ScenarioSpec(
        id="gearbox_degradation",
        label="Gearbox bearing degradation",
        description=(
            "Worn gearbox bearing: oil temperature and high-frequency vibration "
            "climb together after onset while power output sags slightly."
        ),
        healthy_asset=False,
        onset_s=8.0,
        tags=("thermal", "vibration"),
    ),
    "generator_overheat": ScenarioSpec(
        id="generator_overheat",
        label="Generator cooling loss",
        description=(
            "Generator cooling airflow drops, winding temperature rises, active "
            "power is derated and the converter reports repeated warnings."
        ),
        healthy_asset=False,
        onset_s=10.0,
        tags=("thermal", "power"),
    ),
    "blade_imbalance": ScenarioSpec(
        id="blade_imbalance",
        label="Rotor imbalance",
        description=(
            "Mass imbalance on one blade produces once-per-rev vibration, a rotor "
            "speed oscillation and nacelle pitch/yaw hunting."
        ),
        healthy_asset=False,
        onset_s=6.0,
        tags=("vibration", "rotor"),
    ),
    "pitch_fault": ScenarioSpec(
        id="pitch_fault",
        label="Pitch actuator fault",
        description=(
            "Blade pitch feedback drifts: pitch angle runs out of position, "
            "aerodynamic loading falls and pitch position error grows."
        ),
        healthy_asset=False,
        onset_s=9.0,
        tags=("control", "aero"),
    ),
}


def default_scenario() -> str:
    return "gearbox_degradation"


# -- timebase ---------------------------------------------------------------


def asset_time_hours(sim_seconds: float) -> float:
    """Convert simulation seconds to asset-hours (the engine's clock)."""
    return max(0.0, float(sim_seconds)) * ASSET_HOURS_PER_SIM_SECOND


def sim_seconds_for_asset_hours(asset_hours: float) -> float:
    """Convert asset-hours to simulation seconds."""
    return max(0.0, float(asset_hours)) * SIM_SECONDS_PER_ASSET_HOUR


def tick_index_at(sim_seconds: float) -> int:
    """Nearest engine tick for a simulation time."""
    return int(round(max(0.0, float(sim_seconds)) / SIM_SECONDS_PER_ASSET_HOUR))


def sim_seconds_for_tick(tick: int) -> float:
    """Simulation time of an engine tick."""
    return max(0, int(tick)) * SIM_SECONDS_PER_ASSET_HOUR


# -- deterministic noise ----------------------------------------------------


def _seed_for(turbine_seed: int, signal: str, tick_index: int) -> int:
    """Stable 64-bit seed for one (turbine, signal, tick) triple."""
    key = f"{int(turbine_seed)}:{signal}:{int(tick_index)}".encode("utf-8")
    return int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big")


def rng_for(turbine_seed: int, signal: str, tick_index: int) -> random.Random:
    """A fresh RNG for one signal at one tick.

    A new instance per draw is what makes sampling random-access: there is no
    stream position to rewind when the client scrubs.
    """
    return random.Random(_seed_for(turbine_seed, signal, tick_index))


def deterministic_noise(
    turbine_seed: int, signal: str, tick_index: int, scale: float = 1.0
) -> float:
    """Uniform noise in ``[-scale, scale]``, reproducible for a tick."""
    return scale * rng_for(turbine_seed, signal, tick_index).uniform(-1.0, 1.0)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge1 <= edge0:
        return 0.0
    t = _clamp((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _noise(t: float, seed: float, scale: float) -> float:
    """Cheap band-limited pseudo-noise: two incommensurate sines, deterministic."""
    return scale * (
        0.6 * math.sin(0.83 * t + seed * 1.7)
        + 0.4 * math.sin(2.31 * t + seed * 0.9)
    )


def wind_speed(t: float) -> float:
    """Mean wind with a slow ramp, gusts and a veer."""
    ramp = 7.5 + 4.5 * _smoothstep(0.0, 45.0, t)
    gust = _noise(t, 3.0, 1.8) + 0.9 * math.sin(0.17 * t)
    return _clamp(ramp + gust, CUT_IN_MS, CUT_OUT_MS - 2.0)


def rotor_rpm(wind: float, imbalance_onset: float = 0.0) -> float:
    """Region-2-ish speed control below rated, constant above."""
    if wind < CUT_IN_MS:
        return 0.0
    if wind >= RATED_WIND_MS:
        rpm = RATED_RPM
    else:
        span = RATED_WIND_MS - CUT_IN_MS
        rpm = RATED_RPM * _clamp((wind - CUT_IN_MS) / span, 0.0, 1.0) ** 1.35
    return max(0.0, rpm)


def active_power(wind: float, rpm: float, derate: float) -> float:
    if rpm <= 0.01:
        return 0.0
    available = RATED_POWER_KW * _clamp(rpm / RATED_RPM, 0.0, 1.0) ** 3
    return _clamp(available * derate, 0.0, RATED_POWER_KW)


_ANGLE_DT = 0.05
_ANGLE_CACHE: dict[int, float] = {0: 0.0}  # unwrapped radians at whole seconds


def _nominal_rpm_at(t: float) -> float:
    """Scenario-independent rotor speed: the phase reference for 1P excitation."""
    return rotor_rpm(wind_speed(t))


def _integrate_angle(from_s: float, to_s: float) -> float:
    span = to_s - from_s
    steps = max(1, int(round(span / _ANGLE_DT)))
    dt = span / steps
    angle = 0.0
    t = from_s
    for _ in range(steps):
        angle += _nominal_rpm_at(t) * (2.0 * math.pi / 60.0) * dt
        t += dt
    return angle


def rotor_angle_rad(t: float) -> float:
    """Cumulative rotor azimuth in radians, wrapped to [0, 2*pi).

    Integrated from t=0 on a fixed step, so it is a pure function of time: any
    caller can recompute the phase of a 1P (once-per-revolution) signature
    without carrying state between frames. Whole-second results are cached, so a
    client polling forward in time pays for one second of integration per frame.
    """
    seconds = int(max(0.0, t))
    base = max(k for k in _ANGLE_CACHE if k < seconds) if seconds else 0
    angle = _ANGLE_CACHE.get(base, 0.0)
    for s in range(base + 1, seconds + 1):
        angle += _integrate_angle(s - 1.0, float(s))
        _ANGLE_CACHE[s] = angle
    if seconds:
        angle += _integrate_angle(float(seconds), max(0.0, t))
    return angle % (2.0 * math.pi)


# -- modifiers --------------------------------------------------------------


@dataclass(frozen=True)
class ModifierContext:
    """Read-only context handed to every modifier."""

    scenario: str
    t: float
    asset_time_h: float
    turbine_seed: int = DEFAULT_TURBINE_SEED
    onset_s: float = 0.0
    progress: float = 0.0


class Modifier(Protocol):
    """One pipeline stage.

    ``apply`` receives the sample, the asset time in hours and the context, and
    returns the next sample. Modifiers are pure: the same inputs always produce
    the same output, which keeps seeking and replay cheap.
    """

    def apply(self, sample: Sample, asset_time: float, ctx: ModifierContext) -> Sample:
        ...


@dataclass(frozen=True)
class ScenarioFaultModifier:
    """Physical effect of one named scenario.

    This is the Phase 0 home for the fault programmes that used to be baked into
    the generator. Phase 1 replaces it with a data-driven injection catalog; the
    pipeline does not change.
    """

    scenario: str

    def apply(self, sample: Sample, asset_time: float, ctx: ModifierContext) -> Sample:
        true = dict(sample.true)
        meta = dict(sample.meta)
        heat = ctx.progress

        if self.scenario == "gearbox_degradation":
            true["gearbox_temp_c"] += 18.0 * heat
            true["gearbox_temp_rise_c"] = true["gearbox_temp_c"] - meta["expected_gearbox_temp"]
            true["gearbox_vibration_mm_s"] += 4.4 * heat
            true["nacelle_vibration_mm_s"] += 0.9 * heat
            meta["derate"] -= 0.05 * heat
        elif self.scenario == "generator_overheat":
            true["generator_winding_temp_c"] += 30.0 * heat
            meta["derate"] -= 0.22 * heat
            if ctx.progress > 0.35:
                true["converter_faults"] = (
                    1.0 if int((ctx.t - ctx.onset_s) / 6.0) % 2 == 0 else 0.0
                )
        elif self.scenario == "blade_imbalance":
            imbalance = heat
            true["rotor_imbalance_index"] = imbalance
            angle = meta["rotor_angle_rad"]
            if imbalance > 0.0:
                true["nacelle_vibration_mm_s"] += 3.0 * imbalance * abs(math.sin(angle))
                true["rotor_rpm"] = _clamp(
                    meta["rpm_base"] + 0.35 * imbalance * math.sin(angle),
                    0.0,
                    RATED_RPM * 1.2,
                )
                true["yaw_deg"] += 4.0 * imbalance * math.sin(0.5 * angle)
        elif self.scenario == "pitch_fault":
            true["pitch_angle_deg"] += 6.0 * heat
            true["pitch_position_error_deg"] += 5.0 * heat

        _recompute_power(true, meta)
        updated = sample.with_true(true)
        return updated.with_meta(meta)


@dataclass(frozen=True)
class SensorNoiseModifier:
    """Add seeded noise to one reported signal, leaving truth untouched."""

    signal: str
    scale: float

    def apply(self, sample: Sample, asset_time: float, ctx: ModifierContext) -> Sample:
        if self.signal not in sample.measured:
            return sample
        noise = deterministic_noise(ctx.turbine_seed, self.signal, sample.tick, self.scale)
        return sample.with_measured({self.signal: sample.measured[self.signal] + noise})


@dataclass(frozen=True)
class StuckSensorModifier:
    """Report a held value for one signal; the machine keeps changing underneath."""

    signal: str
    held_value: float | None = None

    def apply(self, sample: Sample, asset_time: float, ctx: ModifierContext) -> Sample:
        if self.signal not in sample.measured:
            return sample
        value = sample.true[self.signal] if self.held_value is None else self.held_value
        return sample.with_measured({self.signal: value})


@dataclass(frozen=True)
class DropoutModifier:
    """Report zero for one signal, the wire model's stand-in for a null sample."""

    signal: str

    def apply(self, sample: Sample, asset_time: float, ctx: ModifierContext) -> Sample:
        if self.signal not in sample.measured:
            return sample
        return sample.with_measured({self.signal: 0.0})


def _nominal_values(
    t: float,
    wind_delta: float = 0.0,
    ambient_delta: float = 0.0,
) -> tuple[dict[str, float], dict[str, float]]:
    """Healthy machine state at time ``t`` plus the internal values modifiers need."""
    wind = wind_speed(t)
    if wind_delta != 0.0:
        wind = _clamp(wind + wind_delta, 0.0, CUT_OUT_MS + 2.0)
    rpm_base = rotor_rpm(wind)
    ambient = 9.0 + 4.0 * _noise(t, 11.0, 1.0) + 0.02 * t + ambient_delta

    load_fraction = _clamp(rpm_base / RATED_RPM, 0.0, 1.0)
    # Oil temperature rides on load: baseline rise over ambient at idle plus a
    # load term. Health is judged on the rise above that baseline, not on
    # absolute degrees, so a cold morning is not scored as a fault.
    expected_gearbox_temp = ambient + GEARBOX_BASELINE_RISE_C + 18.0 * load_fraction
    gearbox_temp = expected_gearbox_temp + _noise(t, 5.0, 0.4)
    gearbox_temp_rise = gearbox_temp - expected_gearbox_temp

    gearbox_vib = 1.4 + 1.1 * _clamp(rpm_base / RATED_RPM, 0.0, 1.0)
    gearbox_vib += _noise(t, 7.0, 0.12)

    generator_temp = 61.0 + 34.0 * _clamp(rpm_base / RATED_RPM, 0.0, 1.0)
    generator_temp += _noise(t, 13.0, 0.6)

    blade_pass_hz = BLADE_PASS_PER_REV * rpm_base / 60.0
    rotor_angle = rotor_angle_rad(t)

    nacelle_vib = 0.6 + 0.9 * _clamp(rpm_base / RATED_RPM, 0.0, 1.0)
    nacelle_vib += _noise(t, 17.0, 0.1)

    yaw = 187.0 + 6.0 * _noise(t, 19.0, 0.5)

    pitch_target = -0.5
    pitch_angle = pitch_target + 0.8 * _noise(t, 23.0, 0.2)
    pitch_error = 0.25 + _noise(t, 29.0, 0.15)

    pitch_power_factor = 1.0 - 0.0045 * max(0.0, pitch_angle - pitch_target)
    expected_power_kw = active_power(wind, rpm_base, 1.0)
    power_kw = expected_power_kw * 1.0 * pitch_power_factor
    power_ratio = power_kw / expected_power_kw if expected_power_kw > 1.0 else 1.0

    # The main bearing has its own sensors now: Phase 1's bearing-wear injection
    # needs a temperature and a vibration channel to act on.
    main_bearing_temp = ambient + 12.0 + 9.0 * load_fraction + _noise(t, 31.0, 0.35)
    main_bearing_vib = 1.1 + 0.8 * load_fraction + _noise(t, 37.0, 0.08)

    true = {
        "wind_speed_ms": wind,
        "ambient_temp_c": ambient,
        "rotor_rpm": _clamp(rpm_base + 0.0, 0.0, RATED_RPM * 1.2),
        "active_power_kw": power_kw,
        "power_ratio": power_ratio,
        "yaw_deg": yaw,
        "gearbox_temp_c": gearbox_temp,
        "gearbox_temp_rise_c": gearbox_temp_rise,
        "gearbox_vibration_mm_s": gearbox_vib,
        "nacelle_vibration_mm_s": nacelle_vib,
        "generator_winding_temp_c": generator_temp,
        "converter_faults": 0.0,
        "pitch_angle_deg": pitch_angle,
        "pitch_position_error_deg": pitch_error,
        "blade_pass_hz": blade_pass_hz,
        "rotor_angle_deg": math.degrees(rotor_angle),
        "rotor_imbalance_index": 0.0,
        "main_bearing_temp": main_bearing_temp,
        "main_bearing_vibration": main_bearing_vib,
    }
    meta = {
        "load_fraction": load_fraction,
        "expected_gearbox_temp": expected_gearbox_temp,
        "expected_power_kw": expected_power_kw,
        "pitch_target": pitch_target,
        "derate": 1.0,
        "rpm_base": rpm_base,
        "rotor_angle_rad": rotor_angle,
    }
    return true, meta


def _recompute_power(true: dict[str, float], meta: dict[str, float]) -> None:
    """Apply the current derate and pitch attitude to active power.

    Called after physical modifiers, because a pitch fault changes the
    aerodynamic efficiency as well as the reported angle.
    """
    pitch_target = meta["pitch_target"]
    pitch_angle = true["pitch_angle_deg"]
    pitch_power_factor = 1.0 - 0.0045 * max(0.0, pitch_angle - pitch_target)
    expected = meta["expected_power_kw"]
    power_kw = expected * meta["derate"] * pitch_power_factor
    true["active_power_kw"] = power_kw
    true["power_ratio"] = power_kw / expected if expected > 1.0 else 1.0


def scenario_progress(t: float, spec: ScenarioSpec) -> float:
    """0..1 fault envelope for a named scenario."""
    if spec.healthy_asset:
        return 0.0
    return _smoothstep(spec.onset_s, spec.onset_s + 90.0, t)


def physical_modifiers(scenario: str) -> list[Modifier]:
    """Physical stages for a scenario. Nominal returns an empty list."""
    spec = SCENARIOS.get(scenario)
    if spec is None or spec.healthy_asset:
        return []
    return [ScenarioFaultModifier(spec.id)]


def sensor_modifiers(scenario: str) -> list[Modifier]:
    """Sensor-quality stages for a scenario.

    The built-in scenarios are sensor-healthy, so this is deliberately empty.
    Phase 1 appends stuck/dropout/noise modifiers here or to the active
    injection set; the pipeline already handles them.
    """
    return []


def _build_pre_sensor_sample(
    t: float,
    scenario: str | None = None,
    turbine_id: str = DEFAULT_TURBINE_ID,
    turbine_seed: int = DEFAULT_TURBINE_SEED,
    modifiers: list[Modifier] | None = None,
    tick: int | None = None,
    injections: Sequence[Injection] = (),
) -> tuple[Sample, ModifierContext, str]:
    """Run nominal + weather + physical stages without sensor-quality modifiers."""
    scenario_id = scenario or default_scenario()
    spec = SCENARIOS.get(scenario_id, SCENARIOS[default_scenario()])
    scenario_id = spec.id

    t = max(0.0, float(t))
    tick_index = tick_index_at(t) if tick is None else max(0, int(tick))
    asset_h = asset_time_hours(t)

    wind_delta, ambient_delta = (
        weather_deltas(injections, asset_h) if injections else (0.0, 0.0)
    )
    true, meta = _nominal_values(t, wind_delta=wind_delta, ambient_delta=ambient_delta)
    sample = Sample(
        turbine_id=turbine_id or DEFAULT_TURBINE_ID,
        tick=tick_index,
        asset_time_h=asset_h,
        elapsed_s=t,
        scenario=scenario_id,
        true=true,
        measured=dict(true),
        units=UNITS,
        meta=meta,
    )

    ctx = ModifierContext(
        scenario=scenario_id,
        t=t,
        asset_time_h=sample.asset_time_h,
        turbine_seed=turbine_seed,
        onset_s=spec.onset_s,
        progress=scenario_progress(t, spec),
    )

    if modifiers is None:
        for modifier in physical_modifiers(scenario_id):
            sample = modifier.apply(sample, sample.asset_time_h, ctx)
        if injections:
            def _onset_pitch(onset_h: float) -> float:
                onset_s = sim_seconds_for_asset_hours(onset_h)
                w_d, a_d = weather_deltas(injections, onset_h)
                base_true, _ = _nominal_values(onset_s, wind_delta=w_d, ambient_delta=a_d)
                return base_true["pitch_angle_deg"]

            sample = apply_physical_injections(
                sample, injections, sample.asset_time_h, onset_pitch_fn=_onset_pitch
            )
    else:
        for modifier in modifiers:
            sample = modifier.apply(sample, sample.asset_time_h, ctx)

    return sample, ctx, scenario_id


def build_sample(
    t: float,
    scenario: str | None = None,
    turbine_id: str = DEFAULT_TURBINE_ID,
    turbine_seed: int = DEFAULT_TURBINE_SEED,
    modifiers: list[Modifier] | None = None,
    tick: int | None = None,
    injections: Sequence[Injection] = (),
) -> Sample:
    """Run one tick through the full pipeline.

    ``modifiers=None`` uses the scenario's physical and sensor stages plus any
    active Scenario Lab injections. Passing an explicit list (including ``[]``)
    bypasses the scenario defaults, which is what makes the nominal generator
    directly testable.
    """
    sample, ctx, scenario_id = _build_pre_sensor_sample(
        t,
        scenario=scenario,
        turbine_id=turbine_id,
        turbine_seed=turbine_seed,
        modifiers=modifiers,
        tick=tick,
        injections=injections,
    )

    if modifiers is None:
        for modifier in sensor_modifiers(scenario_id):
            sample = modifier.apply(sample, sample.asset_time_h, ctx)

    if injections and modifiers is None:
        def _pre_sensor_at(onset_h: float) -> Sample:
            onset_tick = tick_index_at(sim_seconds_for_asset_hours(onset_h))
            onset_s = sim_seconds_for_tick(onset_tick)
            pre_sample, _, _ = _build_pre_sensor_sample(
                onset_s,
                scenario=scenario_id,
                turbine_id=sample.turbine_id,
                turbine_seed=turbine_seed,
                modifiers=None,
                tick=onset_tick,
                injections=injections,
            )
            return pre_sample

        sample = apply_sensor_injections(
            sample,
            injections,
            sample.asset_time_h,
            turbine_seed=turbine_seed,
            pre_sensor_fn=_pre_sensor_at,
        )

    return sample


def sample_at_tick(
    tick: int,
    scenario: str | None = None,
    turbine_id: str = DEFAULT_TURBINE_ID,
    turbine_seed: int = DEFAULT_TURBINE_SEED,
    modifiers: list[Modifier] | None = None,
    injections: Sequence[Injection] = (),
) -> Sample:
    """Canonical random-access entry point: one sample per asset-hour tick."""
    tick = max(0, int(tick))
    return build_sample(
        sim_seconds_for_tick(tick),
        scenario,
        turbine_id=turbine_id,
        turbine_seed=turbine_seed,
        modifiers=modifiers,
        tick=tick,
        injections=injections,
    )


def sample_at(
    sim_seconds: float,
    scenario: str | None = None,
    turbine_id: str = DEFAULT_TURBINE_ID,
    turbine_seed: int = DEFAULT_TURBINE_SEED,
    modifiers: list[Modifier] | None = None,
    injections: Sequence[Injection] = (),
) -> Sample:
    """Sample the tick nearest to ``sim_seconds``."""
    return sample_at_tick(
        tick_index_at(sim_seconds),
        scenario,
        turbine_id=turbine_id,
        turbine_seed=turbine_seed,
        modifiers=modifiers,
        injections=injections,
    )


# Backwards-compatible aliases: existing callers and tests use these names.
def simulate(
    t: float,
    scenario: str | None = None,
    turbine_id: str = DEFAULT_TURBINE_ID,
    modifiers: list[Modifier] | None = None,
    turbine_seed: int = DEFAULT_TURBINE_SEED,
    injections: Sequence[Injection] = (),
) -> Sample:
    return build_sample(
        t,
        scenario,
        turbine_id=turbine_id,
        turbine_seed=turbine_seed,
        modifiers=modifiers,
        injections=injections,
    )


def nominal_signals(t: float) -> tuple[Signal, ...]:
    """Healthy machine only: no scenario, no sensor problems."""
    sample = build_sample(t, "nominal", modifiers=[])
    return tuple(Signal(s.id, s.measured_value, s.unit) for s in sample.signals)


def nominal_sample(
    t: float, turbine_id: str = DEFAULT_TURBINE_ID
) -> Sample:
    """Healthy machine state at ``t``, with no fault or sensor stages."""
    return build_sample(t, "nominal", turbine_id=turbine_id, modifiers=[])


def build_signals(t: float, scenario_id: str) -> tuple[Signal, ...]:
    """Return the measured signal set for time ``t`` under ``scenario_id``.

    This is the compatibility surface used by the health tests and the old
    prognosis code. New code should use :func:`sample_at_tick` and read
    ``sample.true`` / ``sample.measured``.
    """
    sample = build_sample(t, scenario_id)
    return tuple(Signal(s.id, s.measured_value, s.unit) for s in sample.signals)


def environment_from(signals: dict[str, float]) -> Environment:
    return Environment(
        wind_speed_ms=signals["wind_speed_ms"],
        ambient_temp_c=signals["ambient_temp_c"],
        rotor_rpm=signals["rotor_rpm"],
        active_power_kw=signals["active_power_kw"],
        yaw_deg=signals["yaw_deg"],
    )


COMPONENT_IDS = tuple(COMPONENT_LABELS.keys())
