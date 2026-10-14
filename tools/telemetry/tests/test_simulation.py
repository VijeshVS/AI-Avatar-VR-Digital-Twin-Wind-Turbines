"""Synthetic telemetry simulation tests."""

from __future__ import annotations

import math

import pytest

from telemetry import simulation
from telemetry.health import score_all


def signal_map(t: float, scenario: str = "nominal") -> dict[str, float]:
    return {s.id: s.value for s in simulation.build_signals(t, scenario)}


def test_every_scenario_produces_the_same_signal_set() -> None:
    reference = set(signal_map(0.0, "nominal"))
    for scenario in simulation.SCENARIOS:
        assert set(signal_map(30.0, scenario)) == reference


def test_simulation_is_deterministic() -> None:
    assert signal_map(17.5, "gearbox_degradation") == signal_map(17.5, "gearbox_degradation")


def test_wind_stays_inside_operating_envelope() -> None:
    for t in range(0, 600, 7):
        wind = simulation.wind_speed(t)
        assert simulation.CUT_IN_MS <= wind < simulation.CUT_OUT_MS


def test_rotor_speed_is_monotonic_below_rated() -> None:
    previous = 0.0
    for wind in range(4, 25):
        rpm = simulation.rotor_rpm(float(wind))
        assert rpm >= previous - 1e-9
        previous = rpm
    assert simulation.rotor_rpm(4.0) < simulation.rotor_rpm(12.0)
    assert simulation.rotor_rpm(25.0) == pytest.approx(simulation.RATED_RPM)


def test_rotor_stops_below_cut_in() -> None:
    assert simulation.rotor_rpm(2.0) == 0.0
    assert simulation.active_power(2.0, 0.0, 1.0) == 0.0


def test_power_never_exceeds_rated() -> None:
    for t in range(0, 600, 3):
        assert signal_map(t)["active_power_kw"] <= simulation.RATED_POWER_KW + 1e-6


def test_gearbox_degradation_raises_temperature_and_vibration() -> None:
    before = signal_map(0.0, "gearbox_degradation")
    after = signal_map(70.0, "gearbox_degradation")
    assert after["gearbox_temp_c"] > before["gearbox_temp_c"] + 15.0
    assert after["gearbox_vibration_mm_s"] > before["gearbox_vibration_mm_s"] + 3.0


def test_generator_fault_derates_power() -> None:
    assert signal_map(90.0, "generator_overheat")["active_power_kw"] < signal_map(90.0, "nominal")["active_power_kw"]


def test_blade_imbalance_is_a_once_per_rev_signature() -> None:
    step = 0.02
    start, window_s = 20.0, 40.0
    count = int(window_s / step)
    frames = [signal_map(start + i * step, "blade_imbalance") for i in range(count)]

    # A 1P excitation repeats at the same azimuth every revolution.
    series = [f["nacelle_vibration_mm_s"] for f in frames]
    mean = sum(series) / len(series)
    peak_angles = [
        f["rotor_angle_deg"]
        for i, f in enumerate(frames[1:-1], start=1)
        if series[i] > mean
        and series[i] > series[i - 1]
        and series[i] > series[i + 1]
    ]
    assert len(peak_angles) >= 4, len(peak_angles)
    offsets = [a % 180.0 for a in peak_angles]  # |sin| peaks twice per revolution
    mean_offset = sum(offsets) / len(offsets)
    spread = max(abs((o - mean_offset + 90.0) % 180.0 - 90.0) for o in offsets)
    assert spread < 20.0, spread

    imbalance_swing = max(f["nacelle_vibration_mm_s"] for f in frames) - min(
        f["nacelle_vibration_mm_s"] for f in frames
    )
    nominal = [signal_map(start + i * step, "nominal")["nacelle_vibration_mm_s"] for i in range(count)]
    nominal_swing = max(nominal) - min(nominal)
    assert imbalance_swing > 2.0 * nominal_swing


def test_rotor_angle_is_monotonic_and_wraps() -> None:
    angles = [simulation.rotor_angle_rad(t) for t in (0.0, 5.0, 10.0, 20.0)]
    assert all(0.0 <= a < 2.0 * math.pi for a in angles)
    assert simulation.rotor_angle_rad(5.0) == pytest.approx(simulation.rotor_angle_rad(5.0))


def test_pitch_fault_drifts_angle_and_error() -> None:
    before = signal_map(0.0, "pitch_fault")
    after = signal_map(110.0, "pitch_fault")
    assert after["pitch_angle_deg"] > before["pitch_angle_deg"] + 5.0
    assert after["pitch_position_error_deg"] > before["pitch_position_error_deg"] + 4.0


def test_nominal_scenario_stays_healthy() -> None:
    components = score_all(signal_map(30.0, "nominal"))
    assert all(c.health > 0.85 for c in components), [(c.id, c.health) for c in components]