"""Sensor guard: detect stuck, dropout, out-of-range and impossible rate signals.

A suspect signal is excluded from health fusion (remaining weights renormalised).
No failure alarm is raised from a sensor fault — it emits a note in the prognosis.

Rules applied in order (each runs independently on the measured dict):
  1. Dropout    — NaN, None, or absent key
  2. Out-of-range — outside SIGNAL_RANGE physical limits
  3. Rate-of-change — faster than physics allows
  4. Flatline    — variance near zero while related signals are changing

A stuck sensor that drifts from the expected value is the classic false-alarm
source; the guard prevents it from triggering a step event or prognosis.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .config import (
    FLATLINE_VAR_THRESHOLD,
    FLATLINE_WINDOW,
    SIGNAL_MAX_RATE,
    SIGNAL_RANGE,
)

# Signals whose flatline is confirmed by checking if related signals are moving.
_FLATLINE_CONFIRM_PAIRS: list[tuple[str, str]] = [
    ("rotor_rpm", "active_power_kw"),
    ("gearbox_temp_c", "active_power_kw"),
    ("generator_winding_temp_c", "active_power_kw"),
    ("main_bearing_temp", "active_power_kw"),
    ("gearbox_vibration_mm_s", "rotor_rpm"),
    ("main_bearing_vibration", "rotor_rpm"),
    ("nacelle_vibration_mm_s", "rotor_rpm"),
]
_FLATLINE_PARTNER: dict[str, str] = {sig: partner for sig, partner in _FLATLINE_CONFIRM_PAIRS}

# The injection catalog models a dropped sample as 0.0 (the wire's null
# stand-in).  These channels are never legitimately exactly zero in operation,
# so an exact zero is a dropout rather than a reading.
_ZERO_IS_DROPOUT = frozenset(
    {
        "gearbox_temp_c",
        "generator_winding_temp_c",
        "main_bearing_temp",
        "gearbox_vibration_mm_s",
        "main_bearing_vibration",
        "nacelle_vibration_mm_s",
    }
)


@dataclass
class SensorGuardState:
    """Accumulator for one turbine (all signals)."""

    # {signal_id: deque of recent measured values}
    _history: dict[str, list[float]] = field(default_factory=dict)
    # {signal_id: last measured value (for rate check)}
    _prev: dict[str, float] = field(default_factory=dict)
    _prev_time: float = -1.0

    def _push(self, signal_id: str, value: float) -> None:
        buf = self._history.setdefault(signal_id, [])
        buf.append(value)
        if len(buf) > FLATLINE_WINDOW:
            buf.pop(0)

    def reset(self) -> None:
        self._history.clear()
        self._prev.clear()
        self._prev_time = -1.0

    def check(
        self, measured: dict[str, float], asset_time_h: float
    ) -> list[str]:
        """Return a list of suspect signal ids, pushing new values into history."""
        suspect: list[str] = []
        dt = max(0.0, asset_time_h - self._prev_time)

        for sig_id in list(SIGNAL_RANGE.keys()):
            raw = measured.get(sig_id)

            # 1. Dropout
            if raw is None or not isinstance(raw, (int, float)) or not math.isfinite(raw):
                suspect.append(sig_id)
                continue

            value = float(raw)
            if sig_id in _ZERO_IS_DROPOUT and abs(value) < 1e-9:
                suspect.append(sig_id)
                self._push(sig_id, value)
                self._prev[sig_id] = value
                continue

            # 2. Out-of-range
            lo, hi = SIGNAL_RANGE[sig_id]
            if value < lo or value > hi:
                suspect.append(sig_id)
                # still push to history so rate guard can fire next tick
                self._push(sig_id, value)
                self._prev[sig_id] = value
                continue

            # 3. Rate-of-change
            max_rate = SIGNAL_MAX_RATE.get(sig_id)
            if max_rate is not None and dt > 0 and sig_id in self._prev:
                rate = abs(value - self._prev[sig_id]) / dt
                if rate > max_rate:
                    suspect.append(sig_id)

            self._push(sig_id, value)
            self._prev[sig_id] = value

        # Cross-check the power output and its independently calculated ratio.
        # The Scenario Lab represents a channel dropout as zero; zero power is
        # otherwise a legitimate hard-fault signal, so flag it only when the
        # redundant channel says the turbine is still producing normally.
        power = measured.get("active_power_kw")
        ratio = measured.get("power_ratio")
        if "active_power_kw" not in suspect and "power_ratio" not in suspect:
            if power is not None and ratio is not None:
                if abs(float(power)) < 1e-9 and float(ratio) >= 0.05:
                    suspect.append("active_power_kw")
                elif float(ratio) < 0.05 and float(power) >= 50.0:
                    suspect.append("power_ratio")

        # 4. Flatline (uses history built above)
        for sig_id, partner in _FLATLINE_PARTNER.items():
            if sig_id in suspect:
                continue  # already flagged
            buf = self._history.get(sig_id, [])
            if len(buf) < FLATLINE_WINDOW:
                continue
            var = sum((v - sum(buf) / len(buf)) ** 2 for v in buf) / len(buf)
            if var > FLATLINE_VAR_THRESHOLD:
                continue
            # Confirm: partner signal is actually changing
            partner_buf = self._history.get(partner, [])
            if len(partner_buf) < 2:
                continue
            partner_range = max(partner_buf) - min(partner_buf)
            if partner_range > 1.0:  # partner is moving; signal is stuck
                suspect.append(sig_id)

        self._prev_time = asset_time_h
        return list(set(suspect))
