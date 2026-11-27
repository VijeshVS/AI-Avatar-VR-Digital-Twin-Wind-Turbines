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


def test_predictions_are_in_the_copilot_context() -> None:
    frame = frame_at(15.0, "nominal")
    estimate = prognosis.estimate(15.0, "nominal")
    predictions = {
        "gearbox": {
            "health": 0.72,
            "state": "warning",
            "status": "degrading",
            "band": "8-30 d",
            "ttf_days": [8.0, 30.0],
            "confidence": 0.66,
            "top_contributors": [{"text": "Gearbox temperature 4.20 °C above expected"}],
            "active_events": [],
            "sensor_faults": [],
        }
    }

    context = copilot.build_context(frame, estimate, predictions)

    assert context["predictions"]["gearbox"]["ttf_days"] == [8.0, 30.0]
    assert context["predictions"]["gearbox"]["band"] == "8-30 d"
    ok, _ = copilot._grounded("The gearbox is degrading, forecast 8 to 30 days.", context)
    assert ok


def test_grounding_rejects_invented_numbers() -> None:
    context = {"health_pct": 72, "band": "<8 d", "ttf_days": [6.0, 14.0]}

    ok, invented = copilot._grounded("The gearbox will fail in 3 days at 72%.", context)

    assert ok is False
    assert invented == [3.0]


def test_grounding_checks_numbers_in_model_actions_too() -> None:
    context = {"t": 10.0}
    raw_reply = '{"answer":"Review the current frame.","actions":[{"type":"set_time","seconds":999}]}'

    ok, invented = copilot._grounded(raw_reply, context)

    assert ok is False
    assert invented == [999.0]


def test_ungrounded_llm_answer_falls_back_to_the_narrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        copilot,
        "config_from_env",
        lambda: copilot.LlmConfig("key", "http://localhost", "model", 1.0),
    )
    monkeypatch.setattr(
        copilot,
        "_call_model",
        lambda question, context, config, system=None: json.dumps(
            {"answer": "The gearbox will fail in exactly 3 days.", "actions": []}
        ),
    )

    frame = frame_at(150.0, "gearbox_degradation")
    estimate = prognosis.estimate(150.0, "gearbox_degradation")
    reply = copilot.ask("When will it fail?", frame, estimate)

    assert reply.source == "rules"
    assert "ungrounded numbers" in reply.detail


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


def test_fallback_does_not_repeat_the_deadline() -> None:
    frame = frame_at(50.0, "gearbox_degradation")
    estimate = prognosis.estimate(50.0, "gearbox_degradation")

    reply = copilot.ask("What should I do?", frame, estimate)

    assert "within 14 days" not in reply.answer
    assert "schedule an inspection" in reply.answer.lower()


# -- procedure mode ---------------------------------------------------------


def test_procedure_fallback_returns_the_authored_plan() -> None:
    frame = frame_at(150.0, "gearbox_degradation")
    estimate = prognosis.estimate(150.0, "gearbox_degradation")

    reply = copilot.fallback_procedure(frame, estimate)
    payload = reply.to_dict()

    assert reply.source == "rules"
    assert payload["mode"] == "procedure"
    assert payload["procedure"]["component_id"] == "gearbox"
    assert [s["n"] for s in payload["procedure"]["steps"]] == list(range(1, 7))
    assert payload["procedure"]["steps"][0]["id"] == "loto"
    assert payload["disclaimer"]
    assert "Gearbox" in payload["answer"] or "Main Bearing" in payload["answer"]


def test_validate_step_ids_drops_unknown_and_deduplicates() -> None:
    procedure = copilot.procedures.for_component("gearbox")

    selected = copilot.validate_step_ids(
        ["loto", "invented", "replace_bearing", "loto"], procedure
    )

    assert selected == ("loto", "replace_bearing")


def test_validate_step_ids_forces_the_authored_procedure_without_safety() -> None:
    procedure = copilot.procedures.for_component("gearbox")

    selected = copilot.validate_step_ids(["oil_sample", "replace_bearing"], procedure)

    assert selected == procedure.step_ids(), "a missing safety step must void the subset"


def test_validate_step_ids_uses_everything_when_empty() -> None:
    procedure = copilot.procedures.for_component("generator")

    assert copilot.validate_step_ids(None, procedure) == procedure.step_ids()
    assert copilot.validate_step_ids([], procedure) == procedure.step_ids()


def test_procedure_model_path_keeps_authored_order(monkeypatch) -> None:
    monkeypatch.setenv("VRAR_LLM_API_KEY", "test-key")
    monkeypatch.setattr(
        copilot,
        "_call_model",
        lambda *a, **k: json.dumps(
            {
                "answer": "Gearbox is critical; replace the bearing.",
                "step_ids": ["replace_bearing", "loto", "invented_step"],
                "why": {
                    "replace_bearing": "vibration and temperature both point at the bearing",
                    "loto": "zero energy before opening the nacelle",
                    "invented_step": "should be ignored",
                },
            }
        ),
    )

    frame = frame_at(150.0, "gearbox_degradation")
    estimate = prognosis.estimate(150.0, "gearbox_degradation")

    payload = copilot.ask_procedure("How do I fix it?", frame, estimate).to_dict()
    steps = payload["procedure"]["steps"]

    assert payload["source"] == "llm"
    assert [s["id"] for s in steps] == ["loto", "replace_bearing"]
    assert steps[0]["why"] == "zero energy before opening the nacelle"
    assert steps[1]["why"] == "vibration and temperature both point at the bearing"


def test_procedure_model_cannot_skip_isolation(monkeypatch) -> None:
    monkeypatch.setenv("VRAR_LLM_API_KEY", "test-key")
    monkeypatch.setattr(
        copilot,
        "_call_model",
        lambda *a, **k: json.dumps(
            {"answer": "Just swap it.", "step_ids": ["replace_bearing"], "why": {}}
        ),
    )

    frame = frame_at(150.0, "gearbox_degradation")
    estimate = prognosis.estimate(150.0, "gearbox_degradation")

    payload = copilot.ask_procedure("How do I fix it?", frame, estimate).to_dict()
    ids = [s["id"] for s in payload["procedure"]["steps"]]

    assert ids == list(copilot.procedures.for_component("gearbox").step_ids())


def test_procedure_endpoint_shape() -> None:
    response = client.post(
        "/api/assistant",
        json={
            "question": "How do I fix it?",
            "mode": "procedure",
            "t": 150.0,
            "scenario": "gearbox_degradation",
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["mode"] == "procedure"
    assert payload["source"] == "rules"
    assert payload["diagnosis"]["component_id"] in {"gearbox", "main_bearing"}
    assert payload["procedure"]["title"]
    assert payload["procedure"]["steps"]
    assert payload["procedure"]["steps"][0]["n"] == 1
    assert payload["disclaimer"]
    assert payload["t"] == 150.0


def test_unknown_mode_is_422() -> None:
    response = client.post("/api/assistant", json={"mode": "poetry"})

    assert response.status_code == 422
