"""Trend and remaining-life estimates: deterministic, no model, no network."""

from __future__ import annotations

import pytest

from telemetry import prognosis


def test_nominal_components_are_stable() -> None:
    result = prognosis.estimate(150.0, "nominal")

    assert result.plant_health > 0.75
    for component in result.components:
        assert component.band in (prognosis.BAND_STABLE, prognosis.BAND_UNKNOWN)
        assert component.days_to_critical is None


def test_gearbox_is_critical_at_the_end_of_its_ramp() -> None:
    result = prognosis.estimate(150.0, "gearbox_degradation")
    worst = result.worst()

    assert worst is not None
    assert worst.component_id in {"gearbox", "main_bearing"}
    assert worst.band == prognosis.BAND_CRITICAL
    assert worst.days_to_critical == 0.0


def test_degrading_component_gets_a_bounded_estimate() -> None:
    result = prognosis.estimate(60.0, "gearbox_degradation")
    gearbox = next(c for c in result.components if c.component_id == "gearbox")

    assert gearbox.band in (prognosis.BAND_UNDER_8D, prognosis.BAND_8_TO_30D)
    assert gearbox.days_to_critical is not None
    assert 0.0 < gearbox.days_to_critical < 60.0
    assert 0.0 <= gearbox.confidence <= 1.0


def test_early_run_admits_it_has_no_history() -> None:
    result = prognosis.estimate(0.0, "gearbox_degradation")

    assert all(c.band == prognosis.BAND_UNKNOWN for c in result.components)
    assert all(c.confidence == 0.0 for c in result.components)


def test_band_matches_the_reported_days() -> None:
    for t in (30.0, 45.0, 60.0, 75.0, 90.0):
        result = prognosis.estimate(t, "gearbox_degradation")
        for component in result.components:
            if component.band == prognosis.BAND_UNDER_8D:
                assert component.days_to_critical is not None
                assert component.days_to_critical < 8.0
            if component.band == prognosis.BAND_8_TO_30D:
                assert component.days_to_critical is not None
                assert 8.0 <= component.days_to_critical <= 30.0


def test_estimate_is_reproducible() -> None:
    first = prognosis.estimate(90.0, "generator_overheat").to_dict()
    second = prognosis.estimate(90.0, "generator_overheat").to_dict()

    assert first == second


def test_estimate_does_not_touch_streaming_state() -> None:
    from telemetry.main import state

    state.select("gearbox_degradation")
    before = state.last_elapsed_s

    prognosis.estimate(120.0, "gearbox_degradation")

    assert state.last_elapsed_s == before


@pytest.mark.parametrize("scenario", sorted(prognosis.simulation.SCENARIOS))
def test_every_scenario_produces_an_estimate(scenario: str) -> None:
    result = prognosis.estimate(120.0, scenario)

    assert len(result.components) == 5
    assert result.scenario == scenario
    assert 0.0 <= result.plant_health <= 1.0
