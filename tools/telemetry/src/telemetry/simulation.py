"""Deterministic synthetic telemetry for a single 3.6 MW class wind turbine.

The generator is a closed-form function of simulation time, so any tick can be
recomputed from scratch. That keeps the Unity client free of hidden state and
lets the PlayMode tests replay an exact frame.

Physics here is illustrative, not certified: the point is to produce plausible,
reproducible signals with recognisable fault signatures.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .models import COMPONENT_LABELS, Environment, Signal

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


def build_signals(t: float, scenario_id: str) -> tuple[Signal, ...]:
    """Return the full signal set for time ``t`` under ``scenario_id``."""
    spec = SCENARIOS.get(scenario_id, SCENARIOS[default_scenario()])
    onset = spec.onset_s if not spec.healthy_asset else float("inf")
    progress = _smoothstep(onset, onset + 90.0, t) if not spec.healthy_asset else 0.0

    wind = wind_speed(t)
    rpm_base = rotor_rpm(wind)
    ambient = 9.0 + 4.0 * _noise(t, 11.0, 1.0) + 0.02 * t

    # --- gearbox degradation -------------------------------------------------
    gearbox_heat = 0.0
    if scenario_id == "gearbox_degradation":
        gearbox_heat = progress
    # Oil temperature rides on load: baseline rise over ambient at idle plus a
    # load term. Health is judged on the rise above that baseline, not on
    # absolute degrees, so a cold morning is not scored as a fault.
    load_fraction = _clamp(rpm_base / RATED_RPM, 0.0, 1.0)
    expected_gearbox_temp = ambient + GEARBOX_BASELINE_RISE_C + 18.0 * load_fraction
    gearbox_temp = expected_gearbox_temp + _noise(t, 5.0, 0.4) + 18.0 * gearbox_heat
    gearbox_temp_rise = gearbox_temp - expected_gearbox_temp

    gearbox_vib = 1.4 + 1.1 * _clamp(rpm_base / RATED_RPM, 0.0, 1.0)
    gearbox_vib += _noise(t, 7.0, 0.12)
    gearbox_vib += 4.4 * gearbox_heat

    # --- generator cooling loss ----------------------------------------------
    gen_heat = progress if scenario_id == "generator_overheat" else 0.0
    generator_temp = 61.0 + 34.0 * _clamp(rpm_base / RATED_RPM, 0.0, 1.0)
    generator_temp += _noise(t, 13.0, 0.6)
    generator_temp += 30.0 * gen_heat

    converter_faults = 0.0
    derate = 1.0 - 0.22 * gen_heat - 0.05 * gearbox_heat
    if scenario_id == "generator_overheat" and progress > 0.35:
        converter_faults = 1.0 if int((t - onset) / 6.0) % 2 == 0 else 0.0

    # --- rotor imbalance ------------------------------------------------------
    imbalance = progress if scenario_id == "blade_imbalance" else 0.0
    blade_pass_hz = BLADE_PASS_PER_REV * rpm_base / 60.0
    rotor_angle = rotor_angle_rad(t)
    imbalance_phase = rotor_angle

    imbalance_vib = 0.0
    if imbalance > 0.0:
        imbalance_vib = 3.0 * imbalance * abs(math.sin(imbalance_phase))

    nacelle_vib = 0.6 + 0.9 * _clamp(rpm_base / RATED_RPM, 0.0, 1.0)
    nacelle_vib += _noise(t, 17.0, 0.1)
    nacelle_vib += imbalance_vib
    nacelle_vib += 0.9 * gearbox_heat

    rotor_speed_dev = 0.0
    yaw = 187.0 + 6.0 * _noise(t, 19.0, 0.5)
    if imbalance > 0.0:
        rotor_speed_dev = 0.35 * imbalance * math.sin(imbalance_phase)
        yaw += 4.0 * imbalance * math.sin(0.5 * imbalance_phase)

    # --- pitch fault ----------------------------------------------------------
    pitch_heat = progress if scenario_id == "pitch_fault" else 0.0
    pitch_target = -0.5
    pitch_angle = pitch_target + 0.8 * _noise(t, 23.0, 0.2)
    pitch_error = 0.25 + _noise(t, 29.0, 0.15)
    if pitch_heat > 0.0:
        pitch_angle += 6.0 * pitch_heat
        pitch_error += 5.0 * pitch_heat

    # --- power ---------------------------------------------------------------
    pitch_power_factor = 1.0 - 0.0045 * max(0.0, pitch_angle - pitch_target)
    expected_power_kw = active_power(wind, rpm_base, 1.0)
    power_kw = expected_power_kw * derate * pitch_power_factor
    # Fraction of the power the current wind could produce. Health rules compare
    # against this, not against rated power, so a calm morning is not a fault.
    power_ratio = power_kw / expected_power_kw if expected_power_kw > 1.0 else 1.0

    signals = (
        Signal("wind_speed_ms", wind, "m/s"),
        Signal("ambient_temp_c", ambient, "degC"),
        Signal("rotor_rpm", _clamp(rpm_base + rotor_speed_dev, 0.0, RATED_RPM * 1.2), "rpm"),
        Signal("active_power_kw", power_kw, "kW"),
        Signal("power_ratio", power_ratio, "0-1"),
        Signal("yaw_deg", yaw, "deg"),
        Signal("gearbox_temp_c", gearbox_temp, "degC"),
        Signal("gearbox_temp_rise_c", gearbox_temp_rise, "degC"),
        Signal("gearbox_vibration_mm_s", gearbox_vib, "mm/s"),
        Signal("nacelle_vibration_mm_s", nacelle_vib, "mm/s"),
        Signal("generator_winding_temp_c", generator_temp, "degC"),
        Signal("converter_faults", converter_faults, "count"),
        Signal("pitch_angle_deg", pitch_angle, "deg"),
        Signal("pitch_position_error_deg", pitch_error, "deg"),
        Signal("blade_pass_hz", blade_pass_hz, "Hz"),
        Signal("rotor_angle_deg", math.degrees(rotor_angle), "deg"),
        Signal("rotor_imbalance_index", imbalance, "0-1"),
    )
    return signals


def environment_from(signals: dict[str, float]) -> Environment:
    return Environment(
        wind_speed_ms=signals["wind_speed_ms"],
        ambient_temp_c=signals["ambient_temp_c"],
        rotor_rpm=signals["rotor_rpm"],
        active_power_kw=signals["active_power_kw"],
        yaw_deg=signals["yaw_deg"],
    )


COMPONENT_IDS = tuple(COMPONENT_LABELS.keys())