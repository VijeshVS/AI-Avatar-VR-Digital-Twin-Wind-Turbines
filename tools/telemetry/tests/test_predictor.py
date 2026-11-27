"""Tests for the Phase-2 predictive engine.

Covers the issue-10 acceptance criteria:

* baseline least-squares recovery,
* EWMA / z-score maths,
* Theil-Sen on a noisy synthetic line,
* gating: noise alone never reports a prognosis,
* the step detector and the post-step trend restart,
* every sensor-guard rule,
* seek-replay consistency,
* gradual fault → days range, sudden fault → event, nominal → neither.
"""
from __future__ import annotations

import math

import pytest

from telemetry.injection.models import Injection, Progression, new_injection_id
from telemetry.models import COMPONENT_IDS, DEFAULT_TURBINE_ID, Sample
from telemetry.predictor import baseline as bl
from telemetry.predictor.config import (
    EWMA_ALPHA,
    SIGNAL_MAX_RATE,
    STEP_SETTLE_H,
)
from telemetry.predictor.engine import PredictorEngine
from telemetry.predictor.events import ResidualBuffer
from telemetry.predictor.health import fuse, z_to_health
from telemetry.predictor.registry import PredictorRegistry
from telemetry.predictor.residuals import ResidualState, SignalEWMA
from telemetry.predictor.sensor_guard import SensorGuardState
from telemetry.predictor.trend import TrendWindow, _theil_sen, estimate
from telemetry.simulation import sample_at_tick


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_sample(
    tick: int,
    measured: dict[str, float],
    scenario: str = "nominal",
    turbine_id: str = DEFAULT_TURBINE_ID,
) -> Sample:
    true = dict(measured)
    return Sample(
        turbine_id=turbine_id,
        tick=tick,
        asset_time_h=float(tick),
        elapsed_s=float(tick) * 0.125,
        scenario=scenario,
        true=true,
        measured=dict(measured),
        units={},
        meta={},
    )


def make_injection(type_id: str, severity: float = 1.0, onset: float = 0.0,
                   kind: str = "ramp", duration_h: float = 240.0,
                   params: dict | None = None) -> Injection:
    return Injection(
        id=new_injection_id(),
        turbine_id=DEFAULT_TURBINE_ID,
        type=type_id,
        severity=severity,
        onset_asset_h=onset,
        progression=Progression(kind=kind, duration_h=duration_h),
        params=params or {},
    )


def run_engine(injections=(), ticks: int = 400, scenario: str = "nominal") -> PredictorEngine:
    engine = PredictorEngine(DEFAULT_TURBINE_ID)
    for tick in range(ticks):
        engine.update(
            sample_at_tick(
                tick,
                scenario,
                turbine_id=DEFAULT_TURBINE_ID,
                injections=list(injections),
            )
        )
    return engine


# ---------------------------------------------------------------------------
# 2.2 Baseline
# ---------------------------------------------------------------------------


def test_baseline_fit_recovers_known_coefficients() -> None:
    samples = []
    for tick in range(200):
        ambient = 5.0 + 2.0 * math.sin(tick / 7.0)
        load = 0.2 + 0.004 * tick
        samples.append(
            {
                "ambient_temp_c": ambient,
                "rotor_rpm": load * bl.RATED_RPM,
                # y = 4 + 2·ambient + 5·load
                "gearbox_temp_c": 4.0 + 2.0 * ambient + 5.0 * load,
            }
        )

    fit = bl.fit_from_samples(samples)["gearbox_temp_c"]

    assert fit["intercept"] == pytest.approx(4.0, abs=1e-6)
    assert fit["ambient"] == pytest.approx(2.0, abs=1e-6)
    assert fit["load"] == pytest.approx(5.0, abs=1e-6)
    assert fit["sigma"] <= 1e-4


def test_expected_signals_use_only_measured_inputs() -> None:
    measured = {
        "ambient_temp_c": 10.0,
        "rotor_rpm": 9.0,
        "power_ratio": 0.8,
        "nacelle_vibration_mm_s": 1.5,
        "pitch_position_error_deg": 0.3,
        "converter_faults": 1.0,
    }
    view = bl.build_view(measured)

    assert view["load_fraction"] == pytest.approx(9.0 / bl.RATED_RPM)
    assert view["pitch_error_rms"] == pytest.approx(0.3)
    assert view["converter_fault_rate"] == pytest.approx(1.0)
    assert "true_gearbox_temp" not in view


# ---------------------------------------------------------------------------
# 2.3 Residuals
# ---------------------------------------------------------------------------


def test_ewma_follows_alpha() -> None:
    ewma = SignalEWMA("x", alpha=0.1)
    assert ewma.update(10.0) == 10.0
    assert ewma.update(20.0) == pytest.approx(0.1 * 20.0 + 0.9 * 10.0)
    assert ewma.update(20.0) == pytest.approx(
        EWMA_ALPHA * 20.0 + (1.0 - EWMA_ALPHA) * 11.0
    )


def test_z_score_is_one_sided_for_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bl, "expected", lambda signal_id, view: 10.0)
    monkeypatch.setattr(bl, "ewma_sigma", lambda signal_id: 1.0)

    above_state, below_state = ResidualState(), ResidualState()
    _, _, above = above_state.update("gearbox_temp_c", {"gearbox_temp_c": 12.0})
    _, _, below = below_state.update("gearbox_temp_c", {"gearbox_temp_c": 8.0})

    assert above == pytest.approx(2.0)
    assert below == pytest.approx(0.0)


def test_z_score_is_two_sided_for_power(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bl, "expected", lambda signal_id, view: 1.0)
    monkeypatch.setattr(bl, "ewma_sigma", lambda signal_id: 0.1)

    residuals = ResidualState()
    _, _, z = residuals.update("power_ratio", {"power_ratio": 0.8})

    assert z == pytest.approx(2.0)


def test_health_map_breakpoints() -> None:
    assert z_to_health(0.0) == 1.0
    assert z_to_health(1.0) == 1.0
    assert z_to_health(3.0) == pytest.approx(0.75)
    assert z_to_health(6.0) == pytest.approx(0.45)
    assert z_to_health(10.0) == 0.0

    fused = fuse({"gearbox_temp_c": 1.0, "gearbox_vibration_mm_s": 0.1}, "gearbox")
    assert 0.1 <= fused < 1.0


# ---------------------------------------------------------------------------
# 2.5 Trend / gating
# ---------------------------------------------------------------------------


def test_theil_sen_ignores_outliers() -> None:
    window = TrendWindow()
    for hour in range(60):
        value = 1.0 - 0.001 * hour
        if hour == 30:
            value += 0.25  # one bad sample
        window.push(float(hour), value)

    median, q25, q75 = _theil_sen(window.samples())
    assert median == pytest.approx(-0.001, abs=2e-4)
    assert q25 <= median <= q75


def test_noise_alone_never_reports_a_prognosis() -> None:
    engine = run_engine(ticks=300)
    for prognosis in engine.update(
        sample_at_tick(300, "nominal", turbine_id=DEFAULT_TURBINE_ID)
    ).values():
        assert prognosis.status != "degrading"
        assert prognosis.ttf_days is None
        assert prognosis.band in ("stable", "unknown")
    assert engine.event_history() == []


def test_gate_stays_closed_until_k_consecutive_warnings() -> None:
    window = TrendWindow()
    for hour in range(40):
        window.push(float(hour), 1.0 - 0.002 * hour)

    _, band, _ = estimate(window, 0.92, gate_open=False)
    assert band == "stable"

    _, band, _ = estimate(window, 0.92, gate_open=True)
    assert band in ("<8 d", "8-30 d", ">30 d")


def test_forecast_range_uses_both_quartiles_and_windows() -> None:
    window = TrendWindow()
    for hour in range(100):
        # A changing slope produces a non-degenerate interval.
        window.push(float(hour), 1.0 - 0.00002 * hour * hour)
    ttf, _, confidence = estimate(window, window.samples()[-1][1], gate_open=True)
    assert ttf is not None
    assert 0 < ttf[0] < ttf[1]
    assert confidence is not None and 0 <= confidence < 1


def test_flat_upper_slope_quartile_closes_gate() -> None:
    window = TrendWindow()
    for hour in range(100):
        window.push(float(hour), 1.0 if hour < 90 else 1.0 - (hour - 90) * 0.01)
    assert estimate(window, 0.91, gate_open=True)[0] is None


# ---------------------------------------------------------------------------
# 2.6 Events and step restart
# ---------------------------------------------------------------------------


def test_residual_buffer_detects_a_step() -> None:
    buffer = ResidualBuffer()
    for _ in range(12):
        buffer.push(0.0)
    buffer.push(2.1)
    buffer.push(2.2)
    buffer.push(2.0)

    assert buffer.detect(sigma=0.25) is True


def test_step_restarts_the_trend_window() -> None:
    engine = PredictorEngine(DEFAULT_TURBINE_ID)
    step_tick = 51

    for tick in range(130):
        sample = sample_at_tick(tick, "nominal", turbine_id=DEFAULT_TURBINE_ID)
        measured = dict(sample.measured)
        if tick >= step_tick:
            measured["gearbox_temp_c"] += 20.0
        engine.update(make_sample(tick, measured))

    steps = [
        event for event in engine.event_history() if event["type"] == "step_change"
    ]
    assert steps
    assert "gearbox_temp_c_baseline_residual" in steps[0]["evidence"]

    last_step_time = max(event["asset_time"] for event in steps)
    state = engine._components["gearbox"]
    assert state.step_settle_until == pytest.approx(last_step_time + STEP_SETTLE_H)
    # The window was cleared at the step and only resumed after the settle time.
    assert state.window.samples()
    assert min(t for t, _ in state.window.samples()) > last_step_time + STEP_SETTLE_H - 1.0


def test_step_alarm_clears_after_the_signal_returns_to_its_pre_step_level() -> None:
    engine = PredictorEngine(DEFAULT_TURBINE_ID)
    for tick in range(120):
        sample = sample_at_tick(tick, "nominal", turbine_id=DEFAULT_TURBINE_ID)
        measured = dict(sample.measured)
        if 51 <= tick < 75:
            measured["gearbox_temp_c"] += 20.0
        engine.update(make_sample(tick, measured))

    assert any(event["type"] == "step_change" for event in engine.event_history())
    assert not any(
        event["type"] == "step_change"
        for event in engine.all_active_events()
    )


def test_wear_then_storm_discards_pre_shock_trend() -> None:
    wear = make_injection("gearbox_bearing_wear", severity=0.6, duration_h=400.0)
    storm = make_injection("storm_overspeed", onset=100.0, kind="step", duration_h=2.0)
    engine = PredictorEngine(DEFAULT_TURBINE_ID)
    had_forecast = False
    saw_shock = False
    for tick in range(140):
        result = engine.update(sample_at_tick(tick, "nominal", injections=[wear, storm]))
        gearbox = result["gearbox"]
        if tick < 100:
            had_forecast |= gearbox.ttf_days is not None
        steps = [e for e in engine.event_history() if e["component"] == "gearbox" and e["type"] == "step_change"]
        if steps:
            saw_shock = True
            state = engine._components["gearbox"]
            assert all(t > steps[-1]["asset_time"] + STEP_SETTLE_H for t, _ in state.window.samples())
            if len(state.window) < 72:
                assert gearbox.ttf_days is None
    assert had_forecast and saw_shock


def test_sudden_fault_produces_an_event() -> None:
    lightning = make_injection("lightning", onset=100.0, kind="step", duration_h=1.0)
    engine = run_engine([lightning], ticks=160)

    events = engine.event_history()
    assert any(event["type"] in ("step_change", "converter_burst", "power_loss") for event in events)
    assert any(event["status"] in ("shock", "imminent", "failed") for event in events)


def test_gradual_fault_produces_a_days_range() -> None:
    wear = make_injection("gearbox_bearing_wear", severity=0.7, duration_h=240.0)
    engine = PredictorEngine(DEFAULT_TURBINE_ID)

    prognosis = None
    for tick in range(130):
        prognoses = engine.update(
            sample_at_tick(
                tick,
                "nominal",
                turbine_id=DEFAULT_TURBINE_ID,
                injections=[wear],
            )
        )
        if prognoses["gearbox"].ttf_days is not None:
            prognosis = prognoses["gearbox"]

    assert prognosis is not None
    lo, hi = prognosis.ttf_days
    assert 0.0 <= lo <= hi
    assert prognosis.band in ("<8 d", "8-30 d", ">30 d")
    assert prognosis.confidence is not None
    assert 0.0 <= prognosis.confidence <= 1.0
    assert not engine.event_history()


# ---------------------------------------------------------------------------
# 2.7 Sensor guard
# ---------------------------------------------------------------------------


def test_guard_flags_dropout() -> None:
    guard = SensorGuardState()
    assert "gearbox_temp_c" in guard.check(
        {"gearbox_temp_c": math.nan}, asset_time_h=0.0
    )
    assert "gearbox_temp_c" in guard.check(
        {"gearbox_temp_c": 0.0}, asset_time_h=1.0
    )


def test_guard_flags_out_of_range() -> None:
    guard = SensorGuardState()
    assert "gearbox_temp_c" in guard.check(
        {"gearbox_temp_c": 999.0}, asset_time_h=0.0
    )


def test_guard_flags_impossible_rate() -> None:
    guard = SensorGuardState()
    assert "gearbox_temp_c" not in guard.check(
        {"gearbox_temp_c": 20.0}, asset_time_h=0.0
    )
    rate = SIGNAL_MAX_RATE["gearbox_temp_c"] + 1.0
    assert "gearbox_temp_c" in guard.check(
        {"gearbox_temp_c": 20.0 + rate}, asset_time_h=1.0
    )


def test_guard_flags_flatline_while_power_moves() -> None:
    guard = SensorGuardState()
    flagged: list[str] = []
    for hour in range(12):
        flagged = guard.check(
            {
                "gearbox_temp_c": 60.0,
                "active_power_kw": 200.0 + hour * 50.0,
            },
            asset_time_h=float(hour),
        )
    assert "gearbox_temp_c" in flagged


def test_guard_flags_flatlined_rpm_while_power_moves() -> None:
    guard = SensorGuardState()
    flagged: list[str] = []
    for hour in range(12):
        flagged = guard.check(
            {"rotor_rpm": 8.0, "active_power_kw": 100.0 + hour * 75.0},
            asset_time_h=float(hour),
        )
    assert "rotor_rpm" in flagged


def test_stuck_sensor_raises_no_failure_alarm() -> None:
    stuck = make_injection("sensor_stuck", onset=40.0, kind="step", duration_h=0.0,
                           params={"signal": "gearbox_temp_c"})
    engine = run_engine([stuck], ticks=140)

    assert engine.event_history() == []
    prognosis = engine.update(
        sample_at_tick(140, "nominal", turbine_id=DEFAULT_TURBINE_ID, injections=[stuck])
    )["gearbox"]
    assert "gearbox_temp_c" in prognosis.sensor_faults
    assert prognosis.ttf_days is None
    assert prognosis.status == "stable"


@pytest.mark.parametrize("bad_value", [None, math.nan, math.inf, -1.0])
def test_suspect_power_cannot_raise_power_loss(bad_value) -> None:
    engine = PredictorEngine(DEFAULT_TURBINE_ID)
    sample = sample_at_tick(0, "nominal", turbine_id=DEFAULT_TURBINE_ID)
    measured = dict(sample.measured)
    measured["wind_speed_ms"] = 8.0
    measured["active_power_kw"] = bad_value
    # -1 is not physically impossible under the configured limits; use an
    # actually out-of-range negative value instead.
    if bad_value == -1.0:
        measured["active_power_kw"] = -101.0
    engine.update(make_sample(0, measured))
    assert all(event["type"] != "power_loss" for event in engine.event_history())


def test_power_channel_dropout_is_not_a_power_loss_alarm() -> None:
    sample = sample_at_tick(0, "nominal")
    measured = dict(sample.measured)
    measured.update({"wind_speed_ms": 8.0, "active_power_kw": 0.0, "power_ratio": 1.0})
    engine = PredictorEngine()

    prognosis = engine.update(make_sample(0, measured))["generator"]

    assert not any(event["type"] == "power_loss" for event in engine.event_history())
    assert "active_power_kw" in prognosis.sensor_faults


def test_power_ratio_dropout_is_excluded_from_health_fusion() -> None:
    sample = sample_at_tick(0, "nominal")
    measured = dict(sample.measured)
    measured["active_power_kw"] = 1200.0
    measured["power_ratio"] = 0.0
    engine = PredictorEngine()

    prognosis = engine.update(make_sample(0, measured))["generator"]

    assert "power_ratio" in prognosis.sensor_faults
    assert not any(event["type"] == "power_loss" for event in engine.event_history())


def test_pitch_error_alone_is_not_a_seizure() -> None:
    from telemetry.predictor.events import EventStore, check_hard_faults

    store = EventStore()
    for tick in range(10):
        check_hard_faults({"pitch_position_error_deg": 6.0, "pitch_angle_deg": tick * 0.1}, tick, store)
    assert not any(event["type"] == "pitch_seizure" for event in store.history())


def test_flat_pitch_feedback_and_changing_error_is_a_seizure() -> None:
    from telemetry.predictor.events import EventStore, check_hard_faults

    store = EventStore()
    for tick in range(6):
        check_hard_faults({"pitch_position_error_deg": tick * 0.2, "pitch_angle_deg": 2.0}, tick, store)
    assert any(event["type"] == "pitch_seizure" for event in store.history())


def test_hard_fault_events_require_three_normal_samples_to_clear() -> None:
    from telemetry.predictor.events import EventStore, check_hard_faults

    store = EventStore()
    failed = {
        "wind_speed_ms": 8.0,
        "active_power_kw": 0.0,
        "rotor_rpm": 0.0,
        "converter_faults": 0.0,
        "pitch_position_error_deg": 0.0,
        "pitch_angle_deg": 0.0,
    }
    normal = {**failed, "wind_speed_ms": 3.0, "active_power_kw": 300.0, "rotor_rpm": 8.0}
    check_hard_faults(failed, 0.0, store)
    assert any(event["type"] == "power_loss" for event in store.all_active())
    check_hard_faults(normal, 1.0, store)
    check_hard_faults(normal, 2.0, store)
    assert any(event["type"] == "power_loss" for event in store.all_active())
    check_hard_faults(normal, 3.0, store)
    assert not any(event["type"] == "power_loss" for event in store.all_active())


# ---------------------------------------------------------------------------
# 2.9 Seek / replay
# ---------------------------------------------------------------------------


def test_registry_replays_independently_of_navigation() -> None:
    registry = PredictorRegistry()

    def source(tick: int) -> Sample:
        return sample_at_tick(tick, "nominal", turbine_id=DEFAULT_TURBINE_ID)

    def read(tick: int):
        return registry.update(source(tick), sample_source=source)["gearbox"]

    # Jump forward, seek back, then jump forward again.
    first = read(120).to_dict()
    read(40)
    second = read(120).to_dict()

    assert second["health"] == pytest.approx(first["health"])
    assert second["status"] == first["status"]
    assert second["band"] == first["band"]


def test_backward_seek_rewinds_event_history_even_for_cached_tick() -> None:
    registry = PredictorRegistry()
    trip = make_injection("converter_trip", onset=50.0, kind="step", duration_h=1.0)

    def source(tick: int) -> Sample:
        return sample_at_tick(tick, "nominal", injections=[trip])

    registry.update(source(80), sample_source=source)
    first = registry.event_history()
    assert first
    registry.update(source(40), sample_source=source)
    assert registry.event_history() == []
    registry.update(source(80), sample_source=source)
    assert registry.event_history() == first


def test_alert_subscribers_receive_independent_turbine_filtered_events() -> None:
    registry = PredictorRegistry()
    first = registry.subscribe("T1")
    second = registry.subscribe("T1")
    other = registry.subscribe("T2")
    trip = make_injection("converter_trip", onset=10.0, kind="step", duration_h=1.0)

    def source(tick: int) -> Sample:
        return sample_at_tick(tick, "nominal", injections=[trip])

    registry.update(source(0), sample_source=source)
    registry.update(source(20), sample_source=source)
    assert first.get_nowait() == second.get_nowait()
    assert other.empty()
    registry.unsubscribe(first)
    registry.unsubscribe(second)
    registry.unsubscribe(other)


def test_registry_fills_skipped_ticks() -> None:
    registry = PredictorRegistry()

    def source(tick: int) -> Sample:
        return sample_at_tick(tick, "nominal", turbine_id=DEFAULT_TURBINE_ID)

    jumped = registry.update(source(120), sample_source=source)["gearbox"].health

    sequential = PredictorEngine(DEFAULT_TURBINE_ID)
    for tick in range(120):
        sequential.update(source(tick))
    expected_120 = sequential.update(source(120))["gearbox"].health
    expected_121 = sequential.update(source(121))["gearbox"].health

    registry.invalidate()
    replayed_121 = registry.update(source(121), sample_source=source)["gearbox"].health

    assert jumped == pytest.approx(expected_120, abs=1e-9)
    assert replayed_121 == pytest.approx(expected_121, abs=1e-9)


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


def test_prediction_endpoints_expose_component_prognoses() -> None:
    from fastapi.testclient import TestClient

    from telemetry.main import app

    client = TestClient(app)
    client.post("/api/inject/reset", json={"reset_t": True})
    frame = client.get("/api/telemetry", params={"t": 1.0}).json()
    assert {item["component"] for item in frame["predictions"]} == set(COMPONENT_IDS)

    payload = client.get("/api/predictions").json()
    assert payload["turbine_id"] == DEFAULT_TURBINE_ID
    assert set(payload["components"]) == {
        "gearbox",
        "generator",
        "main_bearing",
        "pitch_system",
        "blade_set",
    }
    assert client.get("/api/events/log").json()["turbine_id"] == DEFAULT_TURBINE_ID


def test_predictions_endpoint_initializes_without_a_prior_frame_request() -> None:
    from fastapi.testclient import TestClient

    from telemetry.main import app, predictor

    predictor.invalidate("T-new")
    client = TestClient(app)
    payload = client.get("/api/predictions", params={"turbine_id": "T-new"}).json()

    assert set(payload["components"]) == {
        "gearbox", "generator", "main_bearing", "pitch_system", "blade_set"
    }
