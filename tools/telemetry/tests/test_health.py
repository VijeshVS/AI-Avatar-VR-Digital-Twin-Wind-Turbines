"""Explainable health scoring tests."""

from __future__ import annotations

import pytest

from telemetry import health, simulation


def score(scenario: str, t: float):
    values = {s.id: s.value for s in simulation.build_signals(t, scenario)}
    return {c.id: c for c in health.score_all(values)}


def test_states_map_to_documented_thresholds() -> None:
    assert health.state_for(1.0) == health.STATE_HEALTHY
    assert health.state_for(0.75) == health.STATE_HEALTHY
    assert health.state_for(0.74) == health.STATE_WARNING
    assert health.state_for(0.45) == health.STATE_WARNING
    assert health.state_for(0.44) == health.STATE_CRITICAL


def test_rule_severity_is_clamped_and_monotonic() -> None:
    rule = health.Rule("t", "degC", warn=60.0, critical=80.0, weight=1.0)
    assert rule.severity(40.0) == 0.0
    assert rule.severity(60.0) == 0.0
    assert rule.severity(70.0) == pytest.approx(0.5)
    assert rule.severity(80.0) == 1.0
    assert rule.severity(400.0) == 1.0


def test_inverted_rule_severity() -> None:
    rule = health.Rule("power", "kW", warn=2000.0, critical=900.0, weight=1.0, higher_is_worse=False)
    assert rule.severity(3600.0) == 0.0
    assert rule.severity(2000.0) == 0.0
    assert rule.severity(1450.0) == pytest.approx(0.5)
    assert rule.severity(500.0) == 1.0


def test_healthy_component_reports_no_drivers() -> None:
    component = score("nominal", 25.0)["main_bearing"]
    assert component.health > 0.9
    assert component.state == health.STATE_HEALTHY
    assert health.dominant_reason(component) == "all signals within envelope"


def test_gearbox_fault_is_localised_to_the_gearbox() -> None:
    components = score("gearbox_degradation", 70.0)
    gearbox = components["gearbox"]
    assert gearbox.state == health.STATE_CRITICAL
    assert gearbox.health < 0.5
    assert gearbox.factors[0].signal in {"gearbox_vibration_mm_s", "gearbox_temp_rise_c"}
    assert gearbox.factors[0].severity > 0.4
    assert gearbox.factors[0].contribution > 0.4
    # Healthy neighbours stay healthy: the fault must be discriminative.
    # The main bearing shares the heat signature, so it degrades with the gearbox.
    assert components["blade_set"].health > 0.9
    assert components["pitch_system"].health > 0.9
    assert components["generator"].health > 0.9
    assert components["main_bearing"].health < gearbox.health + 0.3


def test_each_fault_scenario_degrades_its_own_component() -> None:
    expected = {
        "gearbox_degradation": "gearbox",
        "generator_overheat": "generator",
        "blade_imbalance": "blade_set",
        "pitch_fault": "pitch_system",
    }
    for scenario, target in expected.items():
        components = score(scenario, 90.0)
        assert components[target].health < 0.75, (scenario, components[target].health)
        assert components[target].state != health.STATE_HEALTHY


def test_health_degrades_after_onset_without_wild_oscillation() -> None:
    series = [score("gearbox_degradation", t)["gearbox"].health for t in range(0, 140, 10)]
    assert series[0] > 0.9
    assert series[-1] < 0.1
    # Past onset the fault ramps monotonically: signalled noise may wiggle a
    # little, but health must never recover on its own.
    steps = [earlier - later for earlier, later in zip(series[4:], series[5:])]
    assert min(steps) > -0.05, series


def test_factor_contributions_form_a_distribution() -> None:
    gearbox = score("gearbox_degradation", 70.0)["gearbox"]
    assert sum(f.contribution for f in gearbox.factors) <= 1.0 + 1e-6
    contributions = [f.contribution for f in gearbox.factors]
    assert contributions == sorted(contributions, reverse=True)


def test_plant_health_is_the_worst_component() -> None:
    components = score("pitch_fault", 90.0)
    expected = min(c.health for c in components.values())
    assert health.plant_health(tuple(components.values())) == pytest.approx(expected)


def test_trend_only_reported_when_previous_health_supplied() -> None:
    values = {s.id: s.value for s in simulation.build_signals(70.0, "gearbox_degradation")}
    first = health.score_all(values)[2]
    second = health.score_all(values, {"gearbox": 0.95})[2]
    assert first.trend == 0.0
    assert second.trend > 0.0