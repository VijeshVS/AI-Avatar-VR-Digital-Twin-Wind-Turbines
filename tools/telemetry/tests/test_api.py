"""HTTP contract tests — these lock the JSON shape the Unity client parses."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from telemetry.main import app, state
from telemetry.models import COMPONENT_IDS, SCHEMA_VERSION

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_state():
    state.select("gearbox_degradation")
    yield
    state.select("gearbox_degradation")


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_scenarios_are_listed() -> None:
    ids = [s["id"] for s in client.get("/api/scenarios").json()["scenarios"]]
    assert {"nominal", "gearbox_degradation", "generator_overheat"} <= set(ids)


def test_telemetry_frame_is_unity_parseable() -> None:
    payload = client.get("/api/telemetry", params={"t": 40.0}).json()

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["scenario"] == "gearbox_degradation"
    assert set(payload["environment"]) == {
        "wind_speed_ms",
        "ambient_temp_c",
        "rotor_rpm",
        "active_power_kw",
        "yaw_deg",
    }

    signals = {s["id"]: s for s in payload["signals"]}
    assert {"wind_speed_ms", "rotor_rpm", "gearbox_temp_c", "gearbox_vibration_mm_s"} <= set(signals)
    assert all(isinstance(s["value"], (int, float)) for s in signals.values())
    assert all(isinstance(s["unit"], str) for s in signals.values())

    components = payload["components"]
    assert [c["id"] for c in components] == list(COMPONENT_IDS)
    for component in components:
        assert 0.0 <= component["health"] <= 1.0
        assert component["state"] in {"healthy", "warning", "critical"}
        assert len(component["factors"]) <= 3
        for factor in component["factors"]:
            assert set(factor) == {
                "signal",
                "value",
                "unit",
                "warn",
                "critical",
                "severity",
                "weight",
                "contribution",
            }


def test_telemetry_is_reproducible_for_the_same_time() -> None:
    first = client.get("/api/telemetry", params={"t": 12.5}).json()
    second = client.get("/api/telemetry", params={"t": 12.5}).json()
    assert [s["value"] for s in first["signals"]] == [s["value"] for s in second["signals"]]


def test_fault_develops_over_time_in_the_client_clock() -> None:
    early = client.get("/api/fault", params={"t": 1.0}).json()
    late = client.get("/api/fault", params={"t": 90.0}).json()
    assert early["plant_health"] > late["plant_health"]
    assert late["component"]["id"] == "gearbox"
    assert late["component"]["state"] in {"warning", "critical"}
    assert late["component"]["reason"] != ""
    assert late["recommendation"] != early["recommendation"]


def test_components_endpoint_reports_reasons() -> None:
    body = client.get("/api/components", params={"t": 80.0}).json()
    gearbox = next(c for c in body["components"] if c["id"] == "gearbox")
    assert gearbox["reason"] != ""
    assert gearbox["state"] in {"healthy", "warning", "critical"}


def test_scenario_can_be_selected() -> None:
    assert client.post("/api/scenario/nominal").json()["scenario"] == "nominal"
    assert client.get("/api/telemetry", params={"t": 30.0}).json()["scenario"] == "nominal"


def test_unknown_scenario_is_404() -> None:
    assert client.get("/api/telemetry", params={"scenario": "nope"}).status_code == 404
    assert client.post("/api/scenario/nope").status_code == 404


def test_trend_appears_only_when_streaming_forward() -> None:
    client.get("/api/telemetry", params={"t": 40.0})
    forward = client.get("/api/telemetry", params={"t": 41.0}).json()
    client.get("/api/telemetry", params={"t": 90.0})
    backward = client.get("/api/telemetry", params={"t": 20.0}).json()
    gearbox_forward = next(c for c in forward["components"] if c["id"] == "gearbox")
    gearbox_backward = next(c for c in backward["components"] if c["id"] == "gearbox")
    assert gearbox_forward["trend"] != 0.0
    assert gearbox_backward["trend"] == 0.0