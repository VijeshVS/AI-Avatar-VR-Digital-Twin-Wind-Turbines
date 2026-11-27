"""Phase 0 foundations: layering, deterministic sampling and the wire contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from telemetry import session, simulation
from telemetry.models import DEFAULT_TURBINE_ID

FIXTURE = Path(__file__).parent / "fixtures" / "nominal_golden.json"


def measured(t: float, scenario: str = "nominal") -> dict[str, float]:
    return simulation.sample_at(t, scenario).measured


def test_nominal_output_is_byte_identical_to_the_golden_file() -> None:
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))

    for frame in golden["frames"]:
        values = {
            signal.id: signal.value
            for signal in simulation.build_signals(frame["t"], "nominal")
        }
        for signal_id, expected in frame["signals"].items():
            assert values[signal_id] == expected, (frame["t"], signal_id)


def test_empty_modifier_list_is_a_valid_nominal_pipeline() -> None:
    sample = simulation.build_sample(30.0, "gearbox_degradation", modifiers=[])

    assert sample.scenario == "gearbox_degradation"
    assert sample.true == sample.measured
    assert sample.measured["gearbox_temp_c"] == pytest.approx(
        simulation.nominal_sample(30.0).measured["gearbox_temp_c"]
    )


def test_physical_modifiers_change_truth_and_measurement_together() -> None:
    sample = simulation.build_sample(70.0, "gearbox_degradation")
    nominal = simulation.nominal_sample(70.0)

    assert sample.true["gearbox_temp_c"] > nominal.true["gearbox_temp_c"]
    assert sample.measured["gearbox_temp_c"] == sample.true["gearbox_temp_c"]


def test_sensor_noise_corrupts_measurement_but_not_truth() -> None:
    modifier = simulation.SensorNoiseModifier("gearbox_temp_c", scale=5.0)
    sample = simulation.build_sample(30.0, "nominal", modifiers=[modifier])

    assert sample.measured["gearbox_temp_c"] != sample.true["gearbox_temp_c"]
    assert sample.measured["wind_speed_ms"] == sample.true["wind_speed_ms"]


def test_stuck_sensor_holds_the_reading_while_the_machine_moves() -> None:
    modifier = simulation.StuckSensorModifier("gearbox_temp_c", held_value=41.0)
    sample = simulation.build_sample(70.0, "gearbox_degradation", modifiers=[modifier])

    assert sample.measured["gearbox_temp_c"] == 41.0
    assert sample.true["gearbox_temp_c"] != 41.0


def test_sampling_is_random_access_even_with_seeded_sensor_noise() -> None:
    modifier = simulation.SensorNoiseModifier("nacelle_vibration_mm_s", scale=0.4)
    target = 240

    direct = simulation.sample_at_tick(target, "nominal", modifiers=[modifier])

    # Walk forward, then scrub back to the same tick: a stateful RNG would now
    # return a different draw.
    for tick in range(target + 1, target + 20):
        simulation.sample_at_tick(tick, "nominal", modifiers=[modifier])
    replayed = simulation.sample_at_tick(target, "nominal", modifiers=[modifier])

    assert replayed.true == direct.true
    assert replayed.measured == direct.measured


def test_noise_is_seeded_per_turbine_signal_and_tick() -> None:
    a = simulation.deterministic_noise(1, "gearbox_temp_c", 12)
    b = simulation.deterministic_noise(1, "gearbox_temp_c", 12)
    c = simulation.deterministic_noise(2, "gearbox_temp_c", 12)
    d = simulation.deterministic_noise(1, "gearbox_vibration_mm_s", 12)
    e = simulation.deterministic_noise(1, "gearbox_temp_c", 13)

    assert a == b
    assert len({a, c, d, e}) == 4


def test_engine_grid_is_one_asset_hour_per_sample() -> None:
    assert simulation.SIM_SECONDS_PER_ASSET_HOUR == pytest.approx(0.125)

    sample = simulation.sample_at_tick(240, "nominal")

    assert sample.tick == 240
    assert sample.asset_time_h == pytest.approx(240.0)
    assert sample.elapsed_s == pytest.approx(30.0)
    assert session.tick_index(30.0) == 240
    assert session.asset_hours(30.0) == pytest.approx(240.0)
    assert session.sim_seconds(240.0) == pytest.approx(30.0)


def test_every_sample_carries_the_phase_zero_fields() -> None:
    sample = simulation.sample_at_tick(8, "gearbox_degradation")

    assert sample.turbine_id == DEFAULT_TURBINE_ID == "T1"
    assert sample.asset_time_h == pytest.approx(8.0)
    assert sample.true and sample.measured
    assert set(sample.true) == set(sample.measured)

    custom = simulation.sample_at_tick(8, "nominal", turbine_id="T7")
    assert custom.turbine_id == "T7"


def test_main_bearing_channels_exist_in_the_nominal_generator() -> None:
    values = simulation.nominal_sample(30.0).measured

    assert "main_bearing_temp" in values
    assert "main_bearing_vibration" in values
    assert values["main_bearing_temp"] > 0.0
    assert values["main_bearing_vibration"] > 0.0
