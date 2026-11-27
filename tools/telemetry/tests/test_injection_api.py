"""HTTP API tests for Scenario Lab injection endpoints and seek/replay parity."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from telemetry.main import app, state

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_session() -> None:
    state.injections.clear()
    state.select("nominal", reset_t=True)
    state.play(False)
    state.set_speed(1.0)
    state.set_focus("")
    yield
    state.injections.clear()
    state.select("gearbox_degradation", reset_t=True)
    state.play(True)
    state.set_speed(1.0)
    state.set_focus("")


def test_catalog_endpoint_exposes_grouped_metadata_and_presets() -> None:
    payload = client.get("/api/inject/catalog").json()

    assert [c["id"] for c in payload["categories"]] == [
        "gradual",
        "sudden",
        "weather",
        "sensor",
    ]
    ids = {entry["id"] for entry in payload["entries"]}
    assert {
        "gearbox_bearing_wear",
        "pitch_seizure",
        "extreme_weather",
        "sensor_stuck",
    } <= ids
    assert "gearbox_temp_c" in payload["signals"]
    assert len(payload["presets"]) >= 6


def test_create_list_delete_and_reset_injections() -> None:
    # Pause at t=15s -> 120 asset-hours; "now" should resolve to 120.0.
    client.post("/api/session", json={"scenario": "nominal", "t": 15.0, "playing": False})

    created = client.post(
        "/api/inject",
        json={
            "type": "gearbox_bearing_wear",
            "severity": 0.7,
            "onset_asset_h": "now",
            "progression": {"kind": "ramp", "duration_h": 240},
        },
    )
    assert created.status_code == 200
    inj = created.json()
    assert inj["id"].startswith("inj_")
    assert inj["turbine_id"] == "T1"
    assert inj["onset_asset_h"] == pytest.approx(120.0)
    assert inj["progression"]["kind"] == "ramp"

    listed = client.get("/api/inject").json()["injections"]
    assert len(listed) == 1
    assert listed[0]["id"] == inj["id"]

    # Scrub forward to 45s (360h) -> gearbox degrades and is visible via Unity's follow path.
    client.post("/api/session", json={"t": 45.0, "playing": False})
    follow_frame = client.get("/api/telemetry").json()
    gearbox = next(c for c in follow_frame["components"] if c["id"] == "gearbox")
    assert follow_frame["healthy_asset"] is False
    assert gearbox["health"] < 0.75

    # Reset returns to a clean nominal state.
    reset = client.post("/api/inject/reset")
    assert reset.status_code == 200
    assert reset.json()["scenario"] == "nominal"
    assert reset.json()["injections"] == []

    after_reset = client.get("/api/telemetry").json()
    gearbox_after = next(c for c in after_reset["components"] if c["id"] == "gearbox")
    assert after_reset["healthy_asset"] is True
    assert gearbox_after["health"] > 0.85


def test_delete_single_injection_and_404_on_missing() -> None:
    one = client.post("/api/inject", json={"type": "lightning", "onset_asset_h": 10}).json()
    two = client.post("/api/inject", json={"type": "extreme_weather", "onset_asset_h": 10}).json()

    deleted = client.delete(f"/api/inject/{one['id']}")
    assert deleted.status_code == 200
    remaining = client.get("/api/inject").json()["injections"]
    assert [item["id"] for item in remaining] == [two["id"]]

    missing = client.delete("/api/inject/inj_does_not_exist")
    assert missing.status_code == 404


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"type": "nonexistent_fault"},
        {"type": "gearbox_bearing_wear", "severity": 1.5},
        {"type": "gearbox_bearing_wear", "severity": -0.1},
        {"type": "gearbox_bearing_wear", "onset_asset_h": -5.0},
        {"type": "gearbox_bearing_wear", "progression": {"kind": "invalid", "duration_h": 10}},
        {"type": "sensor_stuck", "params": {"signal": "not_a_real_signal"}},
    ],
)
def test_inject_validation_rejects_bad_inputs(bad_payload: dict) -> None:
    response = client.post("/api/inject", json=bad_payload)
    assert response.status_code == 422


def test_export_import_round_trip_and_seek_replay_parity() -> None:
    client.post(
        "/api/inject",
        json={
            "type": "gearbox_bearing_wear",
            "severity": 0.75,
            "onset_asset_h": 80.0,
            "progression": {"kind": "ramp", "duration_h": 160.0},
        },
    )
    client.post(
        "/api/inject",
        json={
            "type": "sensor_bias_drift",
            "severity": 0.5,
            "onset_asset_h": 100.0,
            "progression": {"kind": "ramp", "duration_h": 120.0},
            "params": {"signal": "generator_winding_temp_c", "bias": 10.0},
        },
    )

    client.post("/api/session", json={"scenario": "nominal", "t": 40.0, "playing": False})
    before_frame = client.get("/api/telemetry").json()
    exported = client.get("/api/inject/export").json()

    # Reset and confirm we are nominal again.
    client.post("/api/inject/reset")
    nominal_frame = client.get("/api/telemetry").json()
    assert nominal_frame["healthy_asset"] is True

    # Import back, seek past 40.0, then scrub back to 40.0 (unsmoothed seek).
    imported = client.post("/api/inject/import", json=exported)
    assert imported.status_code == 200
    assert imported.json()["injections"] == exported["injections"]

    client.post("/api/session", json={"t": 60.0, "playing": False})
    client.get("/api/telemetry")
    client.post("/api/session", json={"t": 40.0, "playing": False})
    after_frame = client.get("/api/telemetry").json()

    assert after_frame["signals"] == before_frame["signals"]
    assert after_frame["components"] == before_frame["components"]
