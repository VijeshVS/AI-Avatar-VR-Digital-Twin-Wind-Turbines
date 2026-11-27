"""Unit tests for the Scenario Lab injection engine, envelopes, and catalog."""

from __future__ import annotations

import pytest

from telemetry import health, prognosis, simulation
from telemetry.injection import (
    Injection,
    Progression,
    catalog_metadata,
    envelope,
    get_catalog,
)


def _inj(
    type_id: str,
    *,
    severity: float = 1.0,
    onset_asset_h: float = 80.0,
    kind: str = "ramp",
    duration_h: float = 160.0,
    params: dict | None = None,
    inj_id: str = "inj_test",
    turbine_id: str = "T1",
) -> Injection:
    return Injection(
        id=inj_id,
        turbine_id=turbine_id,
        type=type_id,
        severity=severity,
        onset_asset_h=onset_asset_h,
        progression=Progression(kind=kind, duration_h=duration_h),
        params=params or {},
    )


# -- envelopes ---------------------------------------------------------------


@pytest.mark.parametrize("kind", ["ramp", "step", "intermittent", "stepwise"])
def test_envelope_is_bounded_deterministic_and_zero_before_onset(kind: str) -> None:
    prog = Progression(kind=kind, duration_h=100.0)
    assert envelope(0.0, 50.0, prog, seed="s1") == 0.0
    assert envelope(49.99, 50.0, prog, seed="s1") == 0.0

    times = [50.0 + i * 2.5 for i in range(60)]
    first = [envelope(t, 50.0, prog, seed="s1") for t in times]
    second = [envelope(t, 50.0, prog, seed="s1") for t in times]

    assert first == second
    assert all(0.0 <= value <= 1.0 for value in first)


def test_ramp_linear_and_exponential_shapes() -> None:
    lin = Progression(kind="ramp", duration_h=100.0, curve="linear")
    exp = Progression(kind="ramp", duration_h=100.0, curve="exponential")

    assert envelope(100.0, 100.0, lin) == 0.0
    assert envelope(150.0, 100.0, lin) == pytest.approx(0.5)
    assert envelope(200.0, 100.0, lin) == pytest.approx(1.0)
    assert envelope(300.0, 100.0, lin) == pytest.approx(1.0)

    assert envelope(100.0, 100.0, exp) == 0.0
    assert 0.0 < envelope(150.0, 100.0, exp) < 0.5
    assert envelope(200.0, 100.0, exp) == pytest.approx(1.0)


def test_step_jumps_at_onset_and_settles_to_one() -> None:
    prog = Progression(kind="step", duration_h=2.0)

    assert envelope(99.0, 100.0, prog) == 0.0
    at_onset = envelope(100.0, 100.0, prog)
    settled = envelope(102.0, 100.0, prog)
    later = envelope(200.0, 100.0, prog)

    assert at_onset >= 0.5
    assert settled == pytest.approx(1.0)
    assert later == pytest.approx(1.0)


def test_intermittent_is_square_wave_with_seeded_gaps() -> None:
    prog = Progression(kind="intermittent", duration_h=48.0, period_h=4.0, duty=0.5)
    seq = [envelope(100.0 + h * 4.0, 100.0, prog, seed="inj_1") for h in range(40)]

    assert set(seq) == {0.0, 1.0}
    assert seq[0] == 1.0
    # Different seeds produce different gap patterns.
    other = [envelope(100.0 + h * 4.0, 100.0, prog, seed="inj_2") for h in range(40)]
    assert seq != other


def test_stepwise_is_monotonic_staircase() -> None:
    prog = Progression(kind="stepwise", duration_h=100.0, steps=5)
    values = [envelope(100.0 + h, 100.0, prog) for h in range(0, 105, 5)]

    assert values[0] == 0.0
    assert values[-1] == 1.0
    assert all(b >= a for a, b in zip(values, values[1:]))
    assert set(values).issubset({0.0, 0.2, 0.4, 0.6, 0.8, 1.0})


# -- catalog & signal isolation ----------------------------------------------


def test_catalog_contains_all_required_entries() -> None:
    catalog = get_catalog()
    required = {
        "gearbox_bearing_wear",
        "generator_cooling_loss",
        "pitch_drift",
        "blade_imbalance",
        "lubrication_degradation",
        "main_bearing_wear",
        "lightning",
        "converter_trip",
        "storm_overspeed",
        "bird_strike",
        "pitch_seizure",
        "extreme_weather",
        "sensor_stuck",
        "sensor_dropout",
        "sensor_noise_burst",
        "sensor_bias_drift",
    }
    assert required <= set(catalog)
    meta = catalog_metadata()
    assert len(meta["presets"]) >= 6


EXPECTED_CHANGED_SIGNALS: dict[str, set[str]] = {
    "gearbox_bearing_wear": {
        "gearbox_temp_c",
        "gearbox_temp_rise_c",
        "gearbox_vibration_mm_s",
        "active_power_kw",
        "power_ratio",
    },
    "generator_cooling_loss": {
        "generator_winding_temp_c",
        "converter_faults",
        "active_power_kw",
        "power_ratio",
    },
    "pitch_drift": {
        "pitch_angle_deg",
        "pitch_position_error_deg",
        "active_power_kw",
        "power_ratio",
    },
    "blade_imbalance": {
        "rotor_imbalance_index",
        "nacelle_vibration_mm_s",
        "active_power_kw",
        "power_ratio",
    },
    "lubrication_degradation": {
        "gearbox_temp_c",
        "gearbox_temp_rise_c",
        "gearbox_vibration_mm_s",
        "main_bearing_temp",
    },
    "main_bearing_wear": {
        "main_bearing_temp",
        "main_bearing_vibration",
        "nacelle_vibration_mm_s",
    },
    "lightning": {
        "converter_faults",
        "generator_winding_temp_c",
        "active_power_kw",
        "power_ratio",
    },
    "converter_trip": {
        "converter_faults",
        "active_power_kw",
        "power_ratio",
    },
    "storm_overspeed": {
        "wind_speed_ms",
        "rotor_rpm",
        "nacelle_vibration_mm_s",
        "gearbox_vibration_mm_s",
    },
    "bird_strike": {
        "rotor_imbalance_index",
        "nacelle_vibration_mm_s",
        "active_power_kw",
        "power_ratio",
    },
    "pitch_seizure": {
        "pitch_angle_deg",
        "pitch_position_error_deg",
    },
}


@pytest.mark.parametrize("type_id,allowed", list(EXPECTED_CHANGED_SIGNALS.items()))
def test_physical_catalog_entry_changes_only_intended_signals(
    type_id: str, allowed: set[str]
) -> None:
    entry = get_catalog()[type_id]
    inj = Injection(
        id="inj_iso",
        turbine_id="T1",
        type=type_id,
        severity=1.0,
        onset_asset_h=100.0,
        progression=entry.default_progression,
        params=dict(entry.default_params),
    )

    tick = 400  # 400 h = 50 s, well past onset
    base = simulation.sample_at_tick(tick, "nominal")
    injected = simulation.sample_at_tick(tick, "nominal", injections=[inj])

    changed = {
        sig
        for sig in base.true
        if abs(injected.true[sig] - base.true[sig]) > 1e-6
    }
    assert changed, f"{type_id} made no signal changes"
    assert changed <= allowed, (type_id, changed - allowed)


def test_extreme_weather_drives_nominal_physics_without_fault_alarm() -> None:
    entry = get_catalog()["extreme_weather"]
    inj = Injection(
        id="inj_wx",
        turbine_id="T1",
        type="extreme_weather",
        severity=1.0,
        onset_asset_h=0.0,
        progression=entry.default_progression,
    )

    tick = 400
    base = simulation.sample_at_tick(tick, "nominal")
    wx = simulation.sample_at_tick(tick, "nominal", injections=[inj])

    # Raw temperatures and wind rise naturally.
    assert wx.true["ambient_temp_c"] > base.true["ambient_temp_c"] + 15.0
    assert wx.true["gearbox_temp_c"] > base.true["gearbox_temp_c"] + 15.0
    assert wx.true["wind_speed_ms"] > base.true["wind_speed_ms"] + 2.0

    # Fault-specific channels and temperature rise above nominal baseline stay clean.
    assert wx.true["gearbox_temp_rise_c"] == pytest.approx(base.true["gearbox_temp_rise_c"], abs=1e-4)
    assert wx.true["converter_faults"] == 0.0
    assert wx.true["rotor_imbalance_index"] == 0.0

    scores = health.score_sample(wx)
    assert all(c.state == health.STATE_HEALTHY for c in scores), [
        (c.id, c.health, c.state) for c in scores
    ]


def test_pitch_seizure_freezes_feedback_while_command_moves() -> None:
    inj = _inj("pitch_seizure", onset_asset_h=200.0, kind="step", duration_h=1.0)
    samples = [
        simulation.sample_at_tick(tick, "nominal", injections=[inj])
        for tick in range(205, 240, 5)
    ]

    pitches = [s.true["pitch_angle_deg"] for s in samples]
    commands = [s.meta["commanded_pitch_deg"] for s in samples]
    errors = [s.true["pitch_position_error_deg"] for s in samples]

    # Feedback flat-lines across ticks.
    assert max(pitches) - min(pitches) == pytest.approx(0.0, abs=1e-6)
    # Commanded pitch keeps moving and creates a growing/varying position error.
    assert max(commands) - min(commands) > 1.0
    assert max(errors) > 2.0


@pytest.mark.parametrize(
    "sensor_type,params",
    [
        ("sensor_stuck", {"signal": "gearbox_temp_c"}),
        ("sensor_dropout", {"signal": "gearbox_temp_c"}),
        ("sensor_noise_burst", {"signal": "gearbox_vibration_mm_s", "scale": 4.0}),
        ("sensor_bias_drift", {"signal": "gearbox_temp_c", "bias": 15.0}),
    ],
)
def test_sensor_modifiers_corrupt_measured_only_never_true(
    sensor_type: str, params: dict
) -> None:
    inj = _inj(
        sensor_type,
        onset_asset_h=100.0,
        kind="step",
        duration_h=0.0 if sensor_type != "sensor_bias_drift" else 100.0,
        params=params,
    )
    target_signal = params["signal"]

    tick = 320
    clean = simulation.sample_at_tick(tick, "gearbox_degradation")
    corrupted = simulation.sample_at_tick(tick, "gearbox_degradation", injections=[inj])

    # True machine state is completely identical.
    assert corrupted.true == clean.true
    # Only the targeted measured channel differs.
    for sig_id in clean.measured:
        if sig_id == target_signal:
            assert corrupted.measured[sig_id] != clean.measured[sig_id]
        else:
            assert corrupted.measured[sig_id] == clean.measured[sig_id]


def test_stuck_sensor_holds_value_at_onset_while_machine_degrades() -> None:
    wear = _inj("gearbox_bearing_wear", onset_asset_h=100.0, kind="ramp", duration_h=200.0, inj_id="inj_wear")
    stuck = _inj(
        "sensor_stuck",
        onset_asset_h=200.0,
        kind="step",
        duration_h=0.0,
        params={"signal": "gearbox_temp_c"},
        inj_id="inj_stuck",
    )

    at_onset = simulation.sample_at_tick(200, "nominal", injections=[wear, stuck])
    much_later = simulation.sample_at_tick(450, "nominal", injections=[wear, stuck])

    assert much_later.measured["gearbox_temp_c"] == pytest.approx(
        at_onset.true["gearbox_temp_c"]
    )
    assert much_later.true["gearbox_temp_c"] > at_onset.true["gearbox_temp_c"] + 5.0


def test_seeking_and_replaying_with_injections_is_deterministic() -> None:
    injections = [
        _inj("gearbox_bearing_wear", severity=0.7, onset_asset_h=120.0, kind="ramp", duration_h=240.0, inj_id="inj_1"),
        _inj("sensor_noise_burst", severity=0.8, onset_asset_h=100.0, kind="intermittent", duration_h=48.0, params={"signal": "gearbox_vibration_mm_s"}, inj_id="inj_2"),
    ]

    direct = simulation.sample_at_tick(360, "nominal", turbine_seed=3, injections=injections)
    # Scrub around across other ticks.
    for tick in (50, 600, 120, 480):
        simulation.sample_at_tick(tick, "nominal", turbine_seed=3, injections=injections)
    replayed = simulation.sample_at_tick(360, "nominal", turbine_seed=3, injections=injections)

    assert replayed.true == direct.true
    assert replayed.measured == direct.measured


def test_prognosis_module_does_not_import_injection_layer() -> None:
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(prognosis))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported.extend(alias.name for alias in node.names)
    assert not any("injection" in name for name in imported), imported
