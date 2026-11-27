"""Step detector and hard-fault event rules.

Events
------
Each event record is a dict:
  {
    event_id:   str   (stable UUID5 hex for this stream event)
    component:  str
    type:       str   ('step_change' | 'overspeed' | 'power_loss' | 'converter_burst' | 'pitch_seizure')
    severity:   float (0–1)
    asset_time: float (asset hours when first detected)
    message:    str
    evidence:   dict  (signal values that triggered the rule)
    status:     str   ('shock' | 'imminent' | 'failed')
  }

After a step event the caller must restart the component's trend window so the
sudden slope does not create a spurious days-range forecast.
"""
from __future__ import annotations

import statistics
import uuid
from collections import deque
from dataclasses import dataclass, field

from .config import (
    CONVERTER_FAULT_BURST,
    POWER_LOSS_THRESHOLD_KW,
    POWER_LOSS_WIND_MIN_MS,
    ROTOR_OVERSPEED_RATIO,
    STEP_BASELINE,
    STEP_K_SIGMA,
    STEP_MIN_BREACHES,
    STEP_RECENT,
)

RATED_RPM = 12.6  # from simulation constants


# ---------------------------------------------------------------------------
# Step detector
# ---------------------------------------------------------------------------

@dataclass
class ResidualBuffer:
    """Short ring buffer for step detection on one signal."""

    maxlen: int = STEP_BASELINE + STEP_RECENT
    _buf: list[float] = field(default_factory=list)

    def push(self, value: float) -> None:
        self._buf.append(value)
        if len(self._buf) > self.maxlen:
            self._buf.pop(0)

    def ready(self) -> bool:
        return len(self._buf) >= STEP_BASELINE + STEP_RECENT

    def baseline_median(self) -> float:
        return statistics.median(self._buf[:STEP_BASELINE]) if self.ready() else 0.0

    def recent_median(self) -> float:
        return statistics.median(self._buf[STEP_BASELINE:]) if self.ready() else 0.0

    def detect(self, sigma: float) -> bool:
        """Return True if a step of k·σ is detected."""
        if not self.ready():
            return False
        bl_med = self.baseline_median()
        recent = self._buf[STEP_BASELINE:]
        threshold = STEP_K_SIGMA * sigma
        jump = statistics.median(recent) - bl_med
        if abs(jump) < threshold:
            return False
        # Opposite-sign spikes are not a sustained step.
        breaches = sum(1 for r in recent if (r - bl_med) * jump > 0 and abs(r - bl_med) >= threshold)
        return breaches >= STEP_MIN_BREACHES

    def reset(self) -> None:
        self._buf.clear()


# ---------------------------------------------------------------------------
# Event store (hysteresis + dedup)
# ---------------------------------------------------------------------------

@dataclass
class EventStore:
    """Keeps track of active events, with dedup so each event fires once."""

    turbine_id: str = "T1"
    _active: dict[str, dict] = field(default_factory=dict)  # key → event record
    _history: list[dict] = field(default_factory=list)
    _pitch_history: deque = field(default_factory=lambda: deque(maxlen=6))
    _normal_counts: dict[str, int] = field(default_factory=dict)

    # --- helpers -----------------------------------------------------------

    def _key(self, component: str, type_: str) -> str:
        return f"{component}:{type_}"

    def fire(
        self,
        component: str,
        type_: str,
        asset_time: float,
        message: str,
        evidence: dict,
        status: str = "shock",
        severity: float = 0.9,
    ) -> dict | None:
        """Register an event; return the new record or None if already active."""
        key = self._key(component, type_)
        if key in self._active:
            return None  # already active; hysteresis prevents re-firing
        self._normal_counts[key] = 0
        record = {
            "event_id": uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"vrar:{self.turbine_id}:{component}:{type_}:{asset_time:.4f}",
            ).hex[:12],
            "component": component,
            "type": type_,
            "severity": severity,
            "asset_time": round(asset_time, 2),
            "message": message,
            "evidence": evidence,
            "status": status,
        }
        self._active[key] = record
        self._history.append(record)
        return record

    def clear(self, component: str, type_: str) -> None:
        """Mark an event as resolved (remove from active)."""
        key = self._key(component, type_)
        self._active.pop(key, None)
        self._normal_counts.pop(key, None)

    def observe_normal(self, component: str, type_: str, required: int = 3) -> None:
        """Resolve only after several consecutive normal samples."""
        key = self._key(component, type_)
        if key not in self._active:
            return
        self._normal_counts[key] = self._normal_counts.get(key, 0) + 1
        if self._normal_counts[key] >= required:
            self.clear(component, type_)

    def observe_active(self, component: str, type_: str) -> None:
        """Reset the normalisation counter while the fault remains active."""
        self._normal_counts[self._key(component, type_)] = 0

    def active_for(self, component: str) -> list[dict]:
        return [ev for ev in self._active.values() if ev["component"] == component]

    def all_active(self) -> list[dict]:
        return list(self._active.values())

    def history(self) -> list[dict]:
        return list(self._history)

    def reset(self) -> None:
        self._active.clear()
        self._history.clear()
        self._pitch_history.clear()
        self._normal_counts.clear()


# ---------------------------------------------------------------------------
# Hard-fault rules
# ---------------------------------------------------------------------------

def check_hard_faults(
    measured: dict[str, float],
    asset_time_h: float,
    store: EventStore,
    suspect: set[str] | None = None,
) -> list[dict]:
    """Evaluate hard-fault rules against the measured frame; return new events."""
    new_events: list[dict] = []
    suspect = suspect or set()

    # Overspeed
    rpm = measured.get("rotor_rpm")
    if "rotor_rpm" not in suspect and rpm is not None and rpm > RATED_RPM * ROTOR_OVERSPEED_RATIO:
        store.observe_active("blade_set", "overspeed")
        ev = store.fire(
            component="blade_set",
            type_="overspeed",
            asset_time=asset_time_h,
            message=f"Rotor RPM {rpm:.1f} exceeds {ROTOR_OVERSPEED_RATIO * 100:.0f} % of rated ({RATED_RPM} RPM).",
            evidence={"rotor_rpm": rpm},
            status="imminent",
        )
        if ev:
            new_events.append(ev)
    elif "rotor_rpm" not in suspect and rpm is not None:
        store.observe_normal("blade_set", "overspeed")

    # Power loss above cut-in
    wind = measured.get("wind_speed_ms")
    power = measured.get("active_power_kw")
    if (
        not ({"wind_speed_ms", "active_power_kw"} & suspect)
        and wind is not None
        and power is not None
        and wind >= POWER_LOSS_WIND_MIN_MS
        and power < POWER_LOSS_THRESHOLD_KW
    ):
        store.observe_active("generator", "power_loss")
        ev = store.fire(
            component="generator",
            type_="power_loss",
            asset_time=asset_time_h,
            message=(
                f"Power near zero ({power:.0f} kW) while wind is {wind:.1f} m/s — "
                "possible converter or drivetrain failure."
            ),
            evidence={"wind_speed_ms": wind, "active_power_kw": power},
            status="failed",
        )
        if ev:
            new_events.append(ev)
    elif not ({"wind_speed_ms", "active_power_kw"} & suspect) and wind is not None and power is not None:
        store.observe_normal("generator", "power_loss")

    # Converter fault burst
    cfaults = measured.get("converter_faults")
    if "converter_faults" not in suspect and cfaults is not None and cfaults >= CONVERTER_FAULT_BURST:
        store.observe_active("generator", "converter_burst")
        ev = store.fire(
            component="generator",
            type_="converter_burst",
            asset_time=asset_time_h,
            message=f"Converter fault rate {cfaults:.2f} exceeds burst threshold.",
            evidence={"converter_faults": cfaults},
            status="shock",
        )
        if ev:
            new_events.append(ev)
    elif "converter_faults" not in suspect and cfaults is not None:
        store.observe_normal("generator", "converter_burst")

    # A flat feedback alone can be a sensor fault; require independently
    # changing measured position error as evidence of a moving command.
    pitch_err = measured.get("pitch_position_error_deg")
    pitch = measured.get("pitch_angle_deg")
    if {"pitch_position_error_deg", "pitch_angle_deg"} & suspect or pitch_err is None or pitch is None:
        store._pitch_history.clear()
        return new_events

    store._pitch_history.append((pitch, pitch_err))
    pitches = [p for p, _ in store._pitch_history]
    errors = [e for _, e in store._pitch_history]
    seizure = (
        len(pitches) == store._pitch_history.maxlen
        and max(pitches) - min(pitches) < 0.02
        and max(errors) - min(errors) > 0.5
        and max(errors) > 0.5
    )
    if seizure:
        store.observe_active("pitch_system", "pitch_seizure")
        ev = store.fire(
            component="pitch_system",
            type_="pitch_seizure",
            asset_time=asset_time_h,
            message="Pitch feedback is flat while position error changes — possible actuator seizure.",
            evidence={"pitch_position_error_deg": pitch_err, "pitch_angle_deg": pitch},
            status="shock",
            severity=0.95,
        )
        if ev:
            new_events.append(ev)
    elif pitch_err <= 0.5:
        store.observe_normal("pitch_system", "pitch_seizure")
    else:
        store.observe_active("pitch_system", "pitch_seizure")

    return new_events
