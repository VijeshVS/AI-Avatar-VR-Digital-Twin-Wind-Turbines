"""Copilot contract: grounded answers, validated actions, no network in tests."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from telemetry import copilot, prognosis
from telemetry.main import app, frame_at, state

client = TestClient(app)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Never reach a real provider from the test suite, even on a dev machine."""
    monkeypatch.delenv("VRAR_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    state.select("gearbox_degradation")
    yield
    state.select("gearbox_degradation")


def test_fallback_names_the_worst_component_and_its_factor() -> None:
    frame = frame_at(150.0, "gearbox_degradation")
    estimate = prognosis.estimate(150.0, "gearbox_degradation")

    reply = copilot.ask("What is wrong?", frame, estimate)

    assert reply.source == "rules"
    assert "Gearbox" in reply.answer or "Main Bearing" in reply.answer
    assert "critical" in reply.answer.lower()
    assert reply.actions[0]["type"] == copilot.ACTION_FOCUS
    assert reply.actions[0]["component_id"] in {"gearbox", "main_bearing"}


def test_early_frame_says_nominal_and_admits_no_history() -> None:
    frame = frame_at(0.0, "gearbox_degradation")
    estimate = prognosis.estimate(0.0, "gearbox_degradation")

    reply = copilot.ask("How long until failure?", frame, estimate)
    context = copilot.build_context(frame, estimate)

    assert "inside their envelopes" in reply.answer
    assert all(c["band"] == prognosis.BAND_UNKNOWN for c in context["components"])


def test_healthy_frame_says_nominal() -> None:
    frame = frame_at(120.0, "nominal")
    estimate = prognosis.estimate(120.0, "nominal")

    reply = copilot.ask("Anything wrong?", frame, estimate)

    assert "inside their envelopes" in reply.answer
    assert reply.source == "rules"


def test_actions_are_whitelisted() -> None:
    actions = copilot.validate_actions(
        [
            {"type": "focus_component", "component_id": "gearbox"},
            {"type": "focus_component", "component_id": "reactor_core"},
            {"type": "set_scenario", "scenario": "blade_imbalance"},
            {"type": "set_scenario", "scenario": "meteor_strike"},
            {"type": "set_time", "seconds": 99999},
            {"type": "delete_everything"},
            {"type": "set_time", "seconds": "soon"},
        ]
    )

    assert actions == (
        {"type": "focus_component", "component_id": "gearbox"},
        {"type": "set_scenario", "scenario": "blade_imbalance"},
        {"type": "set_time", "seconds": 3600.0},
    )


def test_actions_are_capped() -> None:
    raw = [{"type": "focus_component", "component_id": "gearbox"}] * 10

    assert len(copilot.validate_actions(raw)) == copilot.MAX_ACTIONS


def test_reply_parser_accepts_a_fenced_json_block() -> None:
    content = """```json
    {"answer": "Gearbox is critical.", "actions": [{"type": "focus_component", "component_id": "gearbox"}]}
    ```"""

    answer, actions = copilot._parse_reply(content)

    assert answer == "Gearbox is critical."
    assert actions == ({"type": "focus_component", "component_id": "gearbox"},)


@pytest.mark.parametrize(
    "content",
    ["not json at all", "{}", '{"actions": []}', '{"answer": "   "}'],
)
def test_reply_parser_rejects_unusable_output(content: str) -> None:
    with pytest.raises((ValueError, json.JSONDecodeError)):
        copilot._parse_reply(content)


def test_context_carries_only_computed_numbers() -> None:
    frame = frame_at(150.0, "gearbox_degradation")
    estimate = prognosis.estimate(150.0, "gearbox_degradation")

    context = copilot.build_context(frame, estimate)
    gearbox = next(c for c in context["components"] if c["id"] == "gearbox")

    assert gearbox["health"] == round(frame.component_map()["gearbox"].health, 3)
    assert gearbox["band"] in {
        prognosis.BAND_CRITICAL,
        prognosis.BAND_UNDER_8D,
        prognosis.BAND_8_TO_30D,
    }
    assert context["available_scenarios"]
    assert gearbox["top_factor"]["signal"] == "gearbox_temp_rise_c"


def test_assistant_endpoint_shape() -> None:
    response = client.post(
        "/api/assistant",
        json={"question": "Why is the gearbox red?", "t": 150.0, "scenario": "gearbox_degradation"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "answer",
        "source",
        "actions",
        "detail",
        "t",
        "scenario",
        "worst",
    }
    assert payload["source"] == "rules"
    assert isinstance(payload["actions"], list)
    assert payload["scenario"] == "gearbox_degradation"
    assert payload["worst"]["id"] in {"gearbox", "main_bearing"}


def test_prognosis_endpoint_shape() -> None:
    response = client.get("/api/prognosis", params={"t": 120.0, "scenario": "gearbox_degradation"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"] == "gearbox_degradation"
    assert payload["worst"] in {"gearbox", "main_bearing"}
    assert len(payload["components"]) == 5
    assert {"band", "days_to_critical", "confidence"} <= set(payload["components"][0])
