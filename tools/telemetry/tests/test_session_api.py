"""The session endpoints: one clock driven by any client, without sleeping."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from telemetry.main import app, state

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_session(monkeypatch):
    monkeypatch.delenv("VRAR_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    state.select("gearbox_degradation")
    state.play(False)
    state.seek(0.0)
    state.set_speed(1.0)
    state.set_focus("")
    yield
    state.play(True)
    state.set_speed(1.0)
    state.set_focus("")


def test_session_has_the_agreed_shape() -> None:
    payload = client.get("/api/session").json()

    assert set(payload) == {"scenario", "t", "playing", "speed", "focus", "focus_seq"}
    assert payload["scenario"] == "gearbox_degradation"
    assert payload["playing"] is False
    assert payload["speed"] == 1.0
    assert payload["focus"] is None
    assert isinstance(payload["t"], float)
    assert isinstance(payload["focus_seq"], int)


def test_pause_holds_the_clock() -> None:
    client.post("/api/session", json={"playing": False, "t": 42.0})

    first = client.get("/api/session").json()
    second = client.get("/api/session").json()

    assert first["t"] == second["t"] == 42.0
    assert first["playing"] is False


def test_seek_moves_the_clock() -> None:
    payload = client.post("/api/session", json={"t": 120.0, "playing": False}).json()

    assert payload["t"] == 120.0
    assert client.get("/api/session").json()["t"] == 120.0


def test_speed_is_applied() -> None:
    payload = client.post("/api/session", json={"speed": 2.0}).json()

    assert payload["speed"] == 2.0
    assert client.get("/api/session").json()["speed"] == 2.0


def test_scenario_switch_restarts_the_ramp() -> None:
    client.post("/api/session", json={"t": 100.0, "playing": False})

    payload = client.post("/api/session", json={"scenario": "nominal"}).json()

    assert payload["scenario"] == "nominal"
    assert payload["t"] == 0.0


def test_scenario_switch_can_keep_the_clock() -> None:
    client.post("/api/session", json={"t": 100.0, "playing": False})

    payload = client.post(
        "/api/session", json={"scenario": "nominal", "reset_t": False}
    ).json()

    assert payload["scenario"] == "nominal"
    assert payload["t"] == 100.0


def test_focus_round_trip_and_sequence() -> None:
    before = client.get("/api/session").json()["focus_seq"]

    focused = client.post("/api/session", json={"focus": "gearbox"}).json()
    assert focused["focus"] == "gearbox"
    assert focused["focus_seq"] == before + 1

    # Repeating the same focus must not bump the sequence, or the twin would
    # re-grab the camera every poll while the user tries to fly away.
    again = client.post("/api/session", json={"focus": "gearbox"}).json()
    assert again["focus_seq"] == focused["focus_seq"]

    cleared = client.post("/api/session", json={"focus": ""}).json()
    assert cleared["focus"] is None
    assert cleared["focus_seq"] == focused["focus_seq"] + 1


def test_empty_command_changes_nothing() -> None:
    before = client.get("/api/session").json()

    after = client.post("/api/session", json={}).json()

    assert after == before


def test_unknown_scenario_is_404() -> None:
    assert client.post("/api/session", json={"scenario": "meteor_strike"}).status_code == 404


def test_unknown_component_is_404() -> None:
    assert client.post("/api/session", json={"focus": "reactor_core"}).status_code == 404


@pytest.mark.parametrize(
    "command",
    [
        {"speed": 0.0},
        {"speed": 101.0},
        {"t": -1.0},
        {"t": 5000.0},
    ],
)
def test_out_of_range_commands_are_422(command: dict[str, float]) -> None:
    assert client.post("/api/session", json=command).status_code == 422


def test_telemetry_follows_the_session_clock() -> None:
    client.post(
        "/api/session",
        json={"scenario": "blade_imbalance", "t": 30.0, "playing": False},
    )

    frame = client.get("/api/telemetry").json()

    assert frame["scenario"] == "blade_imbalance"
    assert frame["elapsed_s"] == 30.0


def test_state_is_one_coherent_snapshot() -> None:
    client.post(
        "/api/session",
        json={"scenario": "gearbox_degradation", "t": 60.0, "playing": False},
    )

    payload = client.get("/api/state").json()

    assert set(payload) == {"session", "frame", "prognosis"}
    assert payload["session"]["t"] == payload["frame"]["elapsed_s"] == 60.0
    assert payload["prognosis"]["t"] == 60.0
    assert payload["session"]["scenario"] == payload["frame"]["scenario"]
    assert payload["frame"]["components"]
    assert payload["prognosis"]["components"]


def test_state_tracks_a_scenario_switch() -> None:
    client.post("/api/session", json={"scenario": "generator_overheat", "playing": False})

    first = client.get("/api/state").json()
    second = client.get("/api/state").json()

    assert first["frame"]["scenario"] == second["frame"]["scenario"] == "generator_overheat"
    assert first["frame"]["elapsed_s"] == second["frame"]["elapsed_s"] == 0.0


def test_explicit_t_still_overrides_the_session() -> None:
    client.post("/api/session", json={"t": 30.0, "playing": False})

    frame = client.get("/api/telemetry", params={"t": 90.0}).json()

    assert frame["elapsed_s"] == 90.0
    assert client.get("/api/session").json()["t"] == 30.0


def test_scenario_endpoint_restarts_the_clock() -> None:
    client.post("/api/session", json={"t": 100.0, "playing": False})

    body = client.post("/api/scenario/nominal").json()

    assert body["scenario"] == "nominal"
    assert body["t"] == 0.0
    assert client.get("/api/session").json()["t"] == 0.0


def test_scenario_endpoint_can_keep_the_clock() -> None:
    client.post("/api/session", json={"t": 100.0, "playing": False})

    body = client.post("/api/scenario/nominal", json={"reset_clock": False}).json()

    assert body["scenario"] == "nominal"
    assert body["t"] == 100.0


def test_assistant_defaults_to_the_session_clock() -> None:
    client.post(
        "/api/session",
        json={"scenario": "generator_overheat", "t": 60.0, "playing": False},
    )

    payload = client.post("/api/assistant", json={"question": "What is wrong?"}).json()

    assert payload["t"] == 60.0
    assert payload["scenario"] == "generator_overheat"


def test_prognosis_defaults_to_the_session_clock() -> None:
    client.post("/api/session", json={"t": 45.0, "playing": False})

    payload = client.get("/api/prognosis").json()

    assert payload["t"] == 45.0
