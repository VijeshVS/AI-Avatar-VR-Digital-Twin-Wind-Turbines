"""FastAPI service: synthetic telemetry + explainable health for one turbine.

Endpoints
---------
``GET  /healthz``              liveness probe
``GET  /api/scenarios``        available fault programmes
``GET  /api/telemetry``        one frame at ``?t=`` seconds into the scenario
``GET  /api/components``       health only, for lightweight polling
``GET  /api/fault``            structured verdict + maintenance recommendation
``POST /api/scenario/{id}``    switch the active scenario

The clock is explicit (``t``) rather than wall-clock: the client asks for the
frame it wants, so playback is reproducible and the Unity tests are stable.
``trend`` is reported only when frames are requested in non-decreasing time
order, i.e. when the client is actually streaming.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import health as health_mod
from . import simulation
from .models import SCHEMA_VERSION, ComponentHealth, TelemetryFrame

app = FastAPI(
    title="Wind Turbine Digital Twin Telemetry",
    version="0.1.0",
    description="Synthetic telemetry and explainable health scoring for the VR digital-twin PoC.",
)

SAMPLE_RATE_HZ = 1.0
# Exponential smoothing on the reported health. Real condition monitoring filters
# before alarming, and the avatar must not flicker amber/red on sensor noise.
SMOOTHING_ALPHA = 0.3


class ScenarioSelection(BaseModel):
    scenario: str = Field(default="", description="Optional scenario id, mirrors the path id")
    reset_clock: bool = Field(default=True, description="Restart elapsed time at zero")


@dataclass
class SessionState:
    """Latest health per component, used only to derive a streaming trend."""

    scenario: str = field(default_factory=simulation.default_scenario)
    last_elapsed_s: float = -1.0
    previous_health: dict[str, float] = field(default_factory=dict)
    smoothed_health: dict[str, float] = field(default_factory=dict)

    def select(self, scenario: str) -> None:
        self.scenario = scenario
        self.last_elapsed_s = -1.0
        self.previous_health.clear()
        self.smoothed_health.clear()


state = SessionState()


def _smooth(component, streaming: bool) -> ComponentHealth:
    """Blend the raw score towards the previous value when streaming."""
    if not streaming:
        state.smoothed_health[component.id] = component.health
        return component

    previous = state.smoothed_health.get(component.id)
    if previous is None:
        state.smoothed_health[component.id] = component.health
        return component

    alpha = SMOOTHING_ALPHA
    blended = previous + alpha * (component.health - previous)
    state.smoothed_health[component.id] = blended
    return ComponentHealth(
        id=component.id,
        label=component.label,
        health=blended,
        state=health_mod.state_for(blended),
        trend=component.trend,
        factors=component.factors,
    )


def frame_at(elapsed_s: float, scenario: str | None = None) -> TelemetryFrame:
    target = scenario or state.scenario
    if target not in simulation.SCENARIOS:
        raise HTTPException(status_code=404, detail=f"unknown scenario '{target}'")

    elapsed = max(0.0, elapsed_s)
    streaming = elapsed >= state.last_elapsed_s
    previous = state.previous_health if streaming else {}

    signals = simulation.build_signals(elapsed, target)
    values = {s.id: s.value for s in signals}
    components = tuple(_smooth(c, streaming) for c in health_mod.score_all(values, previous))

    state.scenario = target
    state.last_elapsed_s = elapsed
    state.previous_health = {c.id: c.health for c in components}

    return TelemetryFrame(
        schema_version=SCHEMA_VERSION,
        tick=int(round(elapsed * SAMPLE_RATE_HZ)),
        elapsed_s=elapsed,
        scenario=target,
        healthy_asset=simulation.SCENARIOS[target].healthy_asset,
        environment=simulation.environment_from(values),
        signals=signals,
        components=components,
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "scenario": state.scenario}


@app.get("/api/scenarios")
def scenarios() -> dict[str, list[dict[str, object]]]:
    return {
        "scenarios": [
            {
                "id": s.id,
                "label": s.label,
                "description": s.description,
                "healthy_asset": s.healthy_asset,
                "onset_s": s.onset_s,
                "tags": list(s.tags),
            }
            for s in simulation.SCENARIOS.values()
        ]
    }


@app.get("/api/telemetry")
def telemetry(t: float | None = None, scenario: str | None = None) -> JSONResponse:
    """One full frame. ``t`` defaults to a wall-clock-derived time for curl use."""
    elapsed = t if t is not None else round(time.monotonic() % 3600.0, 3)
    return JSONResponse(frame_at(elapsed, scenario).to_dict())


@app.get("/api/components")
def components(t: float = 0.0, scenario: str | None = None) -> dict[str, object]:
    frame = frame_at(t, scenario)
    return {
        "tick": frame.tick,
        "scenario": frame.scenario,
        "plant_health": round(health_mod.plant_health(frame.components), 4),
        "components": [
            {
                "id": c.id,
                "label": c.label,
                "health": round(c.health, 4),
                "state": c.state,
                "reason": health_mod.dominant_reason(c),
            }
            for c in frame.components
        ],
    }


@app.get("/api/fault")
def fault(t: float = 0.0, scenario: str | None = None) -> dict[str, object]:
    """Structured fault verdict: the predictive-maintenance hand-off point."""
    frame = frame_at(t, scenario)
    worst = min(frame.components, key=lambda c: c.health, default=None)
    return {
        "scenario": frame.scenario,
        "healthy_asset": frame.healthy_asset,
        "plant_health": round(health_mod.plant_health(frame.components), 4),
        "component": None
        if worst is None
        else {
            "id": worst.id,
            "label": worst.label,
            "health": round(worst.health, 4),
            "state": worst.state,
            "reason": health_mod.dominant_reason(worst),
        },
        "recommendation": recommendation(worst),
    }


@app.post("/api/scenario/{scenario_id}")
def select_scenario(scenario_id: str, selection: ScenarioSelection | None = None) -> dict[str, object]:
    if selection is not None and selection.scenario:
        scenario_id = selection.scenario
    if scenario_id not in simulation.SCENARIOS:
        raise HTTPException(status_code=404, detail=f"unknown scenario '{scenario_id}'")
    state.select(scenario_id)
    frame = frame_at(0.0, scenario_id)
    return {
        "scenario": frame.scenario,
        "healthy_asset": frame.healthy_asset,
        "plant_health": round(health_mod.plant_health(frame.components), 4),
        "components": [c.id for c in frame.components],
    }


def recommendation(worst) -> str:
    if worst is None or worst.state == health_mod.STATE_HEALTHY:
        return "continue routine monitoring"
    if worst.state == health_mod.STATE_WARNING:
        return f"schedule inspection of {worst.label.lower()} within 14 days"
    return f"plan corrective maintenance on {worst.label.lower()} at the next convenient window"