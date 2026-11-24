"""Grounded maintenance copilot.

The language model never computes a number. It receives a compact, already
computed context — health, top factor, trend estimate, scenario catalogue — and
turns it into a sentence plus a small set of whitelisted actions. Every value in
its answer is present in the context, and every action is validated against the
twin's real component and scenario ids before it reaches the client.

That split is deliberate: the deterministic engine owns the truth, the model
owns the phrasing. When no key is configured, or the provider fails, the same
response shape is produced by a rule-based narrator, so the demo never depends on
the network.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from . import health as health_mod
from . import prognosis as prognosis_mod
from . import simulation
from .models import COMPONENT_IDS, TelemetryFrame

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT_S = 12.0

MAX_ANSWER_CHARS = 700
MAX_ACTIONS = 3

# Human names for the engine's signal ids, so the narrator reads like a person.
STATE_WORDS = {"healthy": "nominal", "warning": "degraded", "critical": "critical"}

SIGNAL_LABELS = {
    "wind_speed_ms": "wind speed",
    "ambient_temp_c": "ambient temperature",
    "rotor_rpm": "rotor speed",
    "active_power_kw": "active power",
    "power_ratio": "power ratio",
    "yaw_deg": "yaw angle",
    "gearbox_temp_c": "gearbox oil temperature",
    "gearbox_temp_rise_c": "gearbox oil temperature rise",
    "gearbox_vibration_mm_s": "gearbox vibration",
    "nacelle_vibration_mm_s": "nacelle vibration",
    "generator_winding_temp_c": "generator winding temperature",
    "converter_faults": "converter fault count",
    "pitch_angle_deg": "pitch angle",
    "pitch_position_error_deg": "pitch position error",
    "blade_pass_hz": "blade pass frequency",
    "rotor_angle_deg": "rotor azimuth",
    "rotor_imbalance_index": "rotor imbalance index",
}

ACTION_FOCUS = "focus_component"
ACTION_SCENARIO = "set_scenario"
ACTION_TIME = "set_time"
ACTION_TYPES = (ACTION_FOCUS, ACTION_SCENARIO, ACTION_TIME)

SYSTEM_PROMPT = """You are the maintenance copilot for a wind-turbine digital twin.

You will receive CONTEXT: a JSON snapshot computed by the turbine's telemetry and
health engine, and QUESTION: what the operator asked.

Rules:
- Use only numbers that appear in CONTEXT. Never invent, average or extrapolate a value.
- If a component has health 1.0 and no top_factor, describe it as nominal.
- Be concrete: name the component, its health percentage, and its dominant factor.
- If band is "unknown", say there is not enough history yet instead of guessing a date.
- Answer in at most three sentences of plain prose. No markdown, no bullet lists.
- End with exactly one recommended next action.
- Reply with JSON only, in this shape:
  {"answer": "text", "actions": [{"type": "focus_component", "component_id": "gearbox"}]}

Allowed actions (use at most two, and only when they help):
- {"type": "focus_component", "component_id": "<one of the component ids in CONTEXT>"}
- {"type": "set_scenario", "scenario": "<one of available_scenarios in CONTEXT>"}
- {"type": "set_time", "seconds": <number between 0 and 3600>}
"""


@dataclass(frozen=True)
class AssistantReply:
    """What the copilot returns to the client."""

    answer: str
    source: str  # "llm" or "rules"
    actions: tuple[dict[str, Any], ...]
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "source": self.source,
            "actions": list(self.actions),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class LlmConfig:
    api_key: str
    base_url: str
    model: str
    timeout_s: float


def config_from_env() -> LlmConfig:
    """Read the provider settings. Any OpenAI-compatible endpoint works."""
    return LlmConfig(
        api_key=os.environ.get("VRAR_LLM_API_KEY", os.environ.get("OPENAI_API_KEY", "")).strip(),
        base_url=os.environ.get("VRAR_LLM_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/"),
        model=os.environ.get("VRAR_LLM_MODEL", DEFAULT_MODEL).strip(),
        timeout_s=float(os.environ.get("VRAR_LLM_TIMEOUT_S", DEFAULT_TIMEOUT_S)),
    )


def _top_factor(component) -> dict[str, Any] | None:
    if not component.factors:
        return None
    factor = component.factors[0]
    if factor.severity <= 0.0:
        return None
    return {
        "signal": factor.signal,
        "value": round(factor.value, 3),
        "unit": factor.unit,
        "warn": factor.warn,
        "critical": factor.critical,
        "severity": round(factor.severity, 3),
        "share": round(factor.contribution, 3),
    }


def build_context(frame: TelemetryFrame, estimate: prognosis_mod.PlantPrognosis) -> dict[str, Any]:
    """The compact, model-readable view of one frame. Numbers come from here only."""
    by_id = {c.component_id: c for c in estimate.components}
    components = []
    for component in frame.components:
        trend = by_id.get(component.id)
        components.append(
            {
                "id": component.id,
                "label": component.label,
                "health": round(component.health, 3),
                "health_pct": round(component.health * 100.0),
                "state": component.state,
                "trend": round(component.trend, 4),
                "reason": health_mod.dominant_reason(component),
                "top_factor": _top_factor(component),
                "band": trend.band if trend else prognosis_mod.BAND_UNKNOWN,
                "days_to_critical": None
                if trend is None or trend.days_to_critical is None
                else round(trend.days_to_critical, 1),
                "confidence": round(trend.confidence, 2) if trend else 0.0,
            }
        )

    components.sort(key=lambda c: c["health"])
    return {
        "t": round(frame.elapsed_s, 1),
        "scenario": frame.scenario,
        "plant_health": round(health_mod.plant_health(frame.components), 3),
        "environment": {
            "wind_speed_ms": round(frame.environment.wind_speed_ms, 1),
            "rotor_rpm": round(frame.environment.rotor_rpm, 1),
            "active_power_kw": round(frame.environment.active_power_kw),
        },
        "components": components,
        "available_scenarios": list(simulation.SCENARIOS),
        "recommendation": health_mod.maintenance_recommendation(
            min(frame.components, key=lambda c: c.health, default=None)
        ),
        "time_compression": f"1 second of scenario time = {prognosis_mod.HOURS_PER_SIM_SECOND:g} hours of asset life",
    }


def _fallback_answer(frame: TelemetryFrame, estimate: prognosis_mod.PlantPrognosis) -> str:
    worst = min(frame.components, key=lambda c: c.health, default=None)
    if worst is None:
        return "No telemetry is available yet, so there is nothing to assess. Start the telemetry service and try again."

    pct = worst.health * 100.0
    trend = next((c for c in estimate.components if c.component_id == worst.id), None)
    recommendation = health_mod.maintenance_recommendation(worst)
    if trend is not None and trend.band in (
        prognosis_mod.BAND_CRITICAL,
        prognosis_mod.BAND_UNDER_8D,
    ):
        # A measured trend toward the threshold outranks the static state band.
        recommendation = (
            f"plan corrective maintenance on {worst.label.lower()} at the next convenient window"
        )

    if worst.state == health_mod.STATE_HEALTHY:
        return (
            f"All five components are inside their envelopes; the worst is {worst.label} at {pct:.0f}%. "
            f"{recommendation.capitalize()}."
        )

    factor = worst.factors[0] if worst.factors else None
    if factor is not None and factor.severity > 0.0:
        name = SIGNAL_LABELS.get(factor.signal, factor.signal.replace("_", " "))
        cause = (
            f"{name} is {factor.value:.2f} {factor.unit}, against a warning of "
            f"{factor.warn:g} and a critical of {factor.critical:g} {factor.unit}"
        )
    else:
        cause = "no single signal dominates"

    if trend is None or trend.band == prognosis_mod.BAND_UNKNOWN:
        outlook = "there is not enough history yet to estimate time to failure"
    elif trend.band == prognosis_mod.BAND_CRITICAL:
        outlook = "it is already at the critical threshold"
    elif trend.days_to_critical is None:
        outlook = "the score is stable over the measured window"
    elif trend.days_to_critical < 1.0:
        outlook = (
            f"the trend puts it at the critical threshold in about "
            f"{trend.days_to_critical * 24.0:.0f} hours"
        )
    else:
        outlook = f"the trend puts it at the critical threshold in about {trend.days_to_critical:.0f} days"

    return (
        f"{worst.label} is {STATE_WORDS.get(worst.state, worst.state)} at {pct:.0f}%: {cause}. "
        f"{outlook.capitalize()}. {recommendation.capitalize()}."
    )


def _fallback_actions(frame: TelemetryFrame) -> tuple[dict[str, Any], ...]:
    worst = min(frame.components, key=lambda c: c.health, default=None)
    if worst is None:
        return ()
    return ({"type": ACTION_FOCUS, "component_id": worst.id},)


def fallback_reply(
    frame: TelemetryFrame, estimate: prognosis_mod.PlantPrognosis, detail: str = ""
) -> AssistantReply:
    """Deterministic narrator used when no model is configured or it fails."""
    return AssistantReply(
        answer=_fallback_answer(frame, estimate),
        source="rules",
        actions=_fallback_actions(frame),
        detail=detail,
    )


def _strip_code_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.removesuffix("```").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("model reply contained no JSON object")
    return text[start : end + 1]


def validate_actions(raw: Any) -> tuple[dict[str, Any], ...]:
    """Drop anything the twin cannot actually execute."""
    if not isinstance(raw, list):
        return ()

    actions: list[dict[str, Any]] = []
    for item in raw:
        if len(actions) >= MAX_ACTIONS:
            break
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == ACTION_FOCUS:
            component_id = item.get("component_id")
            if component_id in COMPONENT_IDS:
                actions.append({"type": kind, "component_id": component_id})
        elif kind == ACTION_SCENARIO:
            scenario = item.get("scenario")
            if scenario in simulation.SCENARIOS:
                actions.append({"type": kind, "scenario": scenario})
        elif kind == ACTION_TIME:
            seconds = item.get("seconds")
            if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
                actions.append({"type": kind, "seconds": max(0.0, min(3600.0, float(seconds)))})
    return tuple(actions)


def _parse_reply(content: str) -> tuple[str, tuple[dict[str, Any], ...]]:
    payload = json.loads(_strip_code_fence(content))
    if not isinstance(payload, dict):
        raise ValueError("model reply was not a JSON object")

    answer = payload.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("model reply had no answer text")

    return answer.strip()[:MAX_ANSWER_CHARS], validate_actions(payload.get("actions"))


def _call_model(question: str, context: dict[str, Any], config: LlmConfig) -> str:
    payload = {
        "model": config.model,
        "temperature": 0.2,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "CONTEXT:\n"
                + json.dumps(context, separators=(",", ":"))
                + "\n\nQUESTION: "
                + question.strip(),
            },
        ],
    }

    with httpx.Client(timeout=config.timeout_s) as client:
        response = client.post(
            f"{config.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {config.api_key}"},
            json=payload,
        )
        response.raise_for_status()
        body = response.json()

    return body["choices"][0]["message"]["content"]


def ask(question: str, frame: TelemetryFrame, estimate: prognosis_mod.PlantPrognosis) -> AssistantReply:
    """Answer one operator question, degrading to the rule-based narrator."""
    config = config_from_env()
    if not config.api_key:
        return fallback_reply(frame, estimate, detail="no API key configured")

    context = build_context(frame, estimate)
    try:
        content = _call_model(question or "What is wrong with the turbine?", context, config)
        answer, actions = _parse_reply(content)
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as error:
        return fallback_reply(frame, estimate, detail=f"{type(error).__name__}: {error}")

    if not actions:
        actions = _fallback_actions(frame)
    return AssistantReply(answer=answer, source="llm", actions=actions)
