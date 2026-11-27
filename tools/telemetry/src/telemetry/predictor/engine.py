"""PredictorEngine: processes one sample at a time, returns ComponentPrognosis.

The engine never imports the injection layer.  It sees only ``sample.measured``
(the SCADA view) and produces a prognosis for each component.

Call pattern::

    engine = PredictorEngine(turbine_id="T1")
    for tick in range(n_ticks):
        sample = sample_at_tick(tick, ...)
        prognoses = engine.update(sample)
        # prognoses: dict[str, ComponentPrognosis]

After a backward seek or scenario/injection change the registry calls
``engine.reset()`` and replays from tick 0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import Sample
from . import baseline as bl
from .config import FLATLINE_WINDOW, STEP_SETTLE_H
from .events import EventStore, ResidualBuffer, check_hard_faults
from .health import COMPONENT_SIGNAL_WEIGHTS, fuse, state_for, z_to_health
from .models import ComponentPrognosis
from .residuals import ResidualState, should_skip
from .sensor_guard import SensorGuardState
from .trend import GateState, TrendWindow, estimate as trend_estimate

# Derived predictor signals inherit the quality of the raw channel they come
# from.  If the raw sensor is suspect, the derived signal is suspect too.
_DERIVED_SOURCE = {
    "pitch_error_rms": "pitch_position_error_deg",
    "converter_fault_rate": "converter_faults",
    "blade_1p_ratio": "rotor_imbalance_index",
    "load_fraction": "rotor_rpm",
}

_COMPONENT_SENSOR_INPUTS = {
    "gearbox": {"ambient_temp_c", "rotor_rpm", "power_ratio"},
    "generator": {"active_power_kw", "wind_speed_ms", "power_ratio"},
    "main_bearing": {"ambient_temp_c", "rotor_rpm", "power_ratio"},
    "pitch_system": {"pitch_angle_deg", "pitch_position_error_deg"},
    "blade_set": {"rotor_rpm", "rotor_imbalance_index", "nacelle_vibration_mm_s"},
}

# Status bands that carry a forecast rather than "stable"/"unknown".
_FORECAST_BANDS = frozenset({"<8 d", "8-30 d", ">30 d"})

# A step event is considered normalised when the raw residual returns to
# within this many σ of the baseline for several consecutive samples.
STEP_CLEAR_SIGMA = 3.0
STEP_CLEAR_SAMPLES = 3


@dataclass
class _ComponentState:
    component: str
    window: TrendWindow = field(default_factory=TrendWindow)
    gate: GateState = field(default_factory=GateState)
    residual_bufs: dict[str, ResidualBuffer] = field(default_factory=dict)
    step_settle_until: float = -1.0  # skip trend until this asset_time_h
    _normal_count: dict[str, int] = field(default_factory=dict)
    usable_signals: frozenset[str] | None = None

    def reset(self) -> None:
        self.window.reset_all()
        self.gate.reset()
        for buf in self.residual_bufs.values():
            buf.reset()
        self._normal_count.clear()
        self.usable_signals = None
        self.step_settle_until = -1.0


class PredictorEngine:
    """Full predictive engine for one turbine.

    Processes measured samples in chronological order.  Reset and replay from
    t=0 on any backward seek (see :class:`~predictor.registry.PredictorRegistry`).
    """

    COMPONENTS = list(COMPONENT_SIGNAL_WEIGHTS.keys())

    def __init__(self, turbine_id: str = "T1") -> None:
        self.turbine_id = turbine_id
        self._residuals = ResidualState()
        self._windowed = bl.WindowedSignals()
        self._guard = SensorGuardState()
        self._events = EventStore(turbine_id=turbine_id)
        self._components: dict[str, _ComponentState] = {
            c: _ComponentState(c) for c in self.COMPONENTS
        }
        # A suspect channel stays quarantined for a short window even after it
        # looks normal again, so a burst of bad samples cannot feed the step
        # detector or drag health down with a one-off spike.
        self._suspect_until: dict[str, float] = {}

    def reset(self) -> None:
        """Full state reset for replay."""
        self._residuals.reset_all()
        self._windowed.reset()
        self._guard.reset()
        self._events.reset()
        self._suspect_until.clear()
        for cs in self._components.values():
            cs.reset()

    def update(self, sample: Sample) -> dict[str, ComponentPrognosis]:
        """Process one asset-hour sample; return current prognoses."""
        # 1. Sensor guard (runs before residuals, on measured values only)
        measured = dict(sample.measured)
        suspect_signals = set(self._guard.check(measured, sample.asset_time_h))

        # 2. Predictor view: measured signals + deterministic derived signals
        # Invalid inputs are never used as model values.  Supplying safe
        # placeholders only permits construction of the view; the dependency
        # checks below exclude the affected models from fusion and alarms.
        safe_measured = {
            key: value for key, value in measured.items()
            if key not in suspect_signals
        }
        view = bl.build_view(safe_measured)
        for derived, source in _DERIVED_SOURCE.items():
            if source in suspect_signals:
                suspect_signals.add(derived)
        if "rotor_rpm" in suspect_signals:
            suspect_signals.update({
                "gearbox_temp_c", "gearbox_vibration_mm_s",
                "generator_winding_temp_c", "main_bearing_temp",
                "main_bearing_vibration", "blade_1p_ratio",
            })
        if "ambient_temp_c" in suspect_signals:
            suspect_signals.update({
                "gearbox_temp_c", "generator_winding_temp_c", "main_bearing_temp",
            })

        for sig in suspect_signals:
            self._suspect_until[sig] = sample.asset_time_h + FLATLINE_WINDOW
        blocked = {
            sig
            for sig, until in self._suspect_until.items()
            if sample.asset_time_h <= until
        }
        self._windowed.update(view, blocked)
        unavailable = {
            sig for sig in bl.modelled_signals()
            if not bl.within_operating_range(sig, safe_measured)
        }
        # Previously detected steps must not remain alarms once their sole
        # source is known to be suspect.
        for event in self._events.all_active():
            if event["type"] != "step_change":
                continue
            source_signals = set(event["evidence"]) & set(bl.modelled_signals())
            if source_signals & blocked:
                self._events.clear(event["component"], "step_change")
                for signal in source_signals:
                    component_state = self._components[event["component"]]
                    buffer = component_state.residual_bufs.get(signal)
                    if buffer is not None:
                        buffer.reset()

        # 3. Residuals + z-scores (skip when turbine idling)
        signal_z: dict[str, float] = {}
        signal_residuals: dict[str, float] = {}

        skip = "power_ratio" in suspect_signals or should_skip(safe_measured)
        for sig in bl.modelled_signals():
            if sig in blocked or sig in unavailable or skip:
                signal_z[sig] = 0.0
                signal_residuals[sig] = 0.0
            else:
                r, ew, z = self._residuals.update(sig, view)
                signal_z[sig] = z
                signal_residuals[sig] = r

        # 4. Signal health from z
        signal_health: dict[str, float] = {
            sig: z_to_health(z) for sig, z in signal_z.items()
        }

        # 5. Hard-fault events
        check_hard_faults(measured, sample.asset_time_h, self._events, blocked)

        # 6. Step detector per modelled signal
        step_components: set[str] = set()
        for sig, residual in signal_residuals.items():
            if sig in blocked or sig in unavailable or skip:
                continue
            sig_sigma = bl.sigma(sig)
            for comp_id, cs in self._components.items():
                if sig not in COMPONENT_SIGNAL_WEIGHTS.get(comp_id, {}):
                    continue
                buf = cs.residual_bufs.setdefault(sig, ResidualBuffer())
                buf.push(residual)
                if buf.detect(sig_sigma):
                    event = self._events.fire(
                        component=comp_id,
                        type_="step_change",
                        asset_time=sample.asset_time_h,
                        message=f"Step change detected in {_SIG_LABEL.get(sig, sig)}.",
                        evidence={
                            sig: round(view.get(sig, 0.0), 4),
                            f"{sig}_baseline_residual": round(buf.baseline_median(), 4),
                            f"{sig}_post_step_residual": round(buf.recent_median(), 4),
                        },
                        status="shock",
                    )
                    if event is not None:
                        step_components.add(comp_id)
                    buf.reset()
                    cs._normal_count[sig] = 0
                    if event is None:
                        self._maybe_clear_step(comp_id, cs, sig, residual, sig_sigma)
                else:
                    self._maybe_clear_step(comp_id, cs, sig, residual, sig_sigma)

        # Restart trend windows after a step (after settle time)
        for comp_id in step_components:
            cs = self._components[comp_id]
            cs.step_settle_until = sample.asset_time_h + STEP_SETTLE_H
            cs.window.reset_after(sample.asset_time_h)
            cs.gate.reset()

        # 7. Component health + trend per component
        prognoses: dict[str, ComponentPrognosis] = {}
        for comp_id in self.COMPONENTS:
            cs = self._components[comp_id]
            comp_weights = COMPONENT_SIGNAL_WEIGHTS.get(comp_id, {})

            # Exclude suspect signals from fusion (weights renormalise in fuse).
            filtered_sh = {
                sig: sh
                for sig, sh in signal_health.items()
                if not skip and sig not in blocked and sig not in unavailable and sig in comp_weights
            }
            comp_health = fuse(filtered_sh, comp_id)

            usable = frozenset(filtered_sh)
            if cs.usable_signals is not None and cs.usable_signals != usable:
                cs.window.reset_all()
                cs.gate.reset()
            cs.usable_signals = usable

            # Update trend window (unless inside a post-step settle period)
            if usable and sample.asset_time_h > cs.step_settle_until:
                cs.window.push(sample.asset_time_h, comp_health)

            # Gate: z_max for this component
            z_max = max(
                (signal_z.get(sig, 0.0) for sig in comp_weights),
                default=0.0,
            )
            gate_open = cs.gate.update(z_max)

            # TTF forecast
            ttf, band, conf = trend_estimate(cs.window, comp_health, gate_open)

            if len(cs.window) < 72 and band != "critical":
                ttf, band, conf = None, "unknown", None

            active_events = self._events.active_for(comp_id)
            if active_events:
                status = "event"
            elif len(cs.window) < 72:
                status = "insufficient_data"
            elif band in _FORECAST_BANDS or band == "critical":
                status = "degrading"
            else:
                status = "stable"

            # Contributors: the largest z deviations for this component.
            contributors: list[dict[str, Any]] = []
            for sig, z in sorted(signal_z.items(), key=lambda x: -x[1]):
                if sig not in comp_weights or z < 0.1:
                    continue
                contributors.append(
                    {
                        "signal": sig,
                        "residual": round(signal_residuals.get(sig, 0.0), 4),
                        "z": round(z, 3),
                        "text": _contributor_text(sig, signal_residuals.get(sig, 0.0), z),
                    }
                )
            contributors = contributors[:3]

            prognoses[comp_id] = ComponentPrognosis(
                turbine_id=self.turbine_id,
                component=comp_id,
                asset_time_h=sample.asset_time_h,
                health=comp_health,
                state=state_for(comp_health),
                status=status,
                ttf_days=ttf,
                band=band,
                confidence=conf,
                top_contributors=contributors,
                active_events=active_events,
                sensor_faults=sorted(
                    s for s in blocked
                    if s in comp_weights or s in _COMPONENT_SENSOR_INPUTS.get(comp_id, set())
                ),
            )

        return prognoses

    def _maybe_clear_step(
        self,
        comp_id: str,
        cs: _ComponentState,
        sig: str,
        residual: float,
        sig_sigma: float,
    ) -> None:
        """Resolve a step event once the signal has genuinely normalised."""
        has_step = any(
            ev["type"] == "step_change" and sig in ev.get("evidence", {})
            for ev in self._events.active_for(comp_id)
        )
        if not has_step:
            cs._normal_count[sig] = 0
            return
        event = next(
            (
                ev for ev in self._events.active_for(comp_id)
                if ev["type"] == "step_change" and sig in ev.get("evidence", {})
            ),
            None,
        )
        baseline = (
            float(event["evidence"].get(f"{sig}_baseline_residual", 0.0))
            if event is not None
            else 0.0
        )
        if abs(residual - baseline) <= STEP_CLEAR_SIGMA * sig_sigma:
            count = cs._normal_count.get(sig, 0) + 1
            cs._normal_count[sig] = count
            if count >= STEP_CLEAR_SAMPLES:
                self._events.clear(comp_id, "step_change")
                cs._normal_count[sig] = 0
        else:
            cs._normal_count[sig] = 0

    def event_history(self) -> list[dict]:
        return self._events.history()

    def all_active_events(self) -> list[dict]:
        return self._events.all_active()


# ---------------------------------------------------------------------------
# Human-readable contributor text
# ---------------------------------------------------------------------------
_SIG_LABEL = {
    "gearbox_temp_c":           "Gearbox temperature",
    "gearbox_vibration_mm_s":   "Gearbox vibration",
    "generator_winding_temp_c": "Generator winding temperature",
    "main_bearing_temp":        "Main bearing temperature",
    "main_bearing_vibration":   "Main bearing vibration",
    "pitch_error_rms":          "Pitch error RMS",
    "converter_fault_rate":     "Converter fault count",
    "blade_1p_ratio":           "Blade 1P ratio",
    "power_ratio":              "Power ratio",
}

_SIG_UNIT = {
    "gearbox_temp_c":           "°C",
    "gearbox_vibration_mm_s":   "mm/s",
    "generator_winding_temp_c": "°C",
    "main_bearing_temp":        "°C",
    "main_bearing_vibration":   "mm/s",
    "pitch_error_rms":          "°",
    "converter_fault_rate":     "faults",
    "blade_1p_ratio":           "",
    "power_ratio":              "",
}


def _contributor_text(sig: str, residual: float, z: float) -> str:
    label = _SIG_LABEL.get(sig, sig)
    unit = _SIG_UNIT.get(sig, "")
    direction = "above" if residual >= 0 else "below"
    return (
        f"{label} {abs(residual):.2f}{(' ' + unit) if unit else ''} {direction} "
        f"expected for this load (z={z:.1f})"
    )
