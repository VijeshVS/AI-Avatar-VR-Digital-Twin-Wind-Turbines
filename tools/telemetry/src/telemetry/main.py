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

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import copilot
from . import health as health_mod
from . import prognosis as prognosis_mod
from . import simulation
from .models import COMPONENT_IDS, SCHEMA_VERSION, ComponentHealth, TelemetryFrame
from .session import SessionState

app = FastAPI(
    title="Wind Turbine Digital Twin Telemetry",
    version="0.1.0",
    description="Synthetic telemetry and explainable health scoring for the VR digital-twin PoC.",
)

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

SAMPLE_RATE_HZ = 1.0
# Exponential smoothing on the reported health. Real condition monitoring filters
# before alarming, and the avatar must not flicker amber/red on sensor noise.
SMOOTHING_ALPHA = 0.3


class ScenarioSelection(BaseModel):
    scenario: str = Field(default="", description="Optional scenario id, mirrors the path id")
    reset_clock: bool = Field(default=True, description="Restart elapsed time at zero")


class SessionCommand(BaseModel):
    """One control command for the shared clock. Every field is optional."""

    scenario: str | None = None
    t: float | None = Field(default=None, ge=0, le=3600)
    playing: bool | None = None
    speed: float | None = Field(default=None, ge=0.1, le=100)
    focus: str | None = Field(
        default=None, description="Component id to focus; empty string clears it"
    )
    reset_t: bool = Field(
        default=True, description="Restart the ramp when the scenario changes"
    )


class AssistantRequest(BaseModel):
    question: str = Field(
        default="What is wrong with the turbine?", description="Operator question in plain language"
    )
    mode: Literal["summary", "procedure"] = Field(
        default="summary", description="summary answers; procedure returns a repair plan"
    )
    t: float | None = Field(
        default=None, description="Scenario time in seconds; defaults to the latest requested tick"
    )
    scenario: str | None = Field(
        default=None, description="Optional scenario id; defaults to the active one"
    )


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


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Operator console: the same service, seen from a browser."""
    return FileResponse(STATIC_DIR / "index.html")


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
    """One full frame. Without ``t`` the shared session clock is used.

    ``?t=`` stays an explicit override: the PlayMode suite and the offline replay
    ask for a specific moment and must keep receiving exactly that frame.
    """
    elapsed = t if t is not None else state.current_elapsed()
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
    reset_clock = selection.reset_clock if selection is not None else True
    state.select(scenario_id, reset_t=reset_clock)
    frame = frame_at(state.current_elapsed(), scenario_id)
    return {
        "scenario": frame.scenario,
        "healthy_asset": frame.healthy_asset,
        "plant_health": round(health_mod.plant_health(frame.components), 4),
        "components": [c.id for c in frame.components],
        "t": round(frame.elapsed_s, 1),
    }


@app.get("/api/session")
def get_session() -> dict[str, object]:
    """The shared scenario, clock and focus command every client should follow."""
    return state.snapshot()


@app.post("/api/session")
def set_session(command: SessionCommand) -> dict[str, object]:
    """Drive the shared clock. Omitted fields are left untouched."""
    if command.scenario is not None:
        if command.scenario not in simulation.SCENARIOS:
            raise HTTPException(
                status_code=404, detail=f"unknown scenario '{command.scenario}'"
            )
        state.select(command.scenario, reset_t=command.reset_t)

    if command.t is not None:
        state.seek(command.t)
    if command.playing is not None:
        state.play(command.playing)
    if command.speed is not None:
        state.set_speed(command.speed)
    if command.focus is not None:
        if command.focus and command.focus not in COMPONENT_IDS:
            raise HTTPException(
                status_code=404, detail=f"unknown component '{command.focus}'"
            )
        state.set_focus(command.focus)

    return state.snapshot()


@app.get("/api/state")
def state_snapshot() -> dict[str, object]:
    """Everything a console needs in one coherent snapshot.

    The frame and the prognosis are computed at the same instant as the session
    time, so the page can never show health from one moment next to a clock from
    another.
    """
    elapsed = state.current_elapsed()
    frame = frame_at(elapsed, state.scenario)
    estimate = prognosis_mod.estimate(
        frame.elapsed_s, frame.scenario, {c.id: c.health for c in frame.components}
    )

    session = state.snapshot()
    session["t"] = round(frame.elapsed_s, 2)
    return {
        "session": session,
        "frame": frame.to_dict(),
        "prognosis": estimate.to_dict(),
    }


@app.get("/api/prognosis")
def prognosis(t: float | None = None, scenario: str | None = None) -> dict[str, object]:
    """Deterministic trend and remaining-life band per component, no model involved."""
    elapsed = t if t is not None else state.current_elapsed()
    frame = frame_at(elapsed, scenario)
    return prognosis_mod.estimate(
        frame.elapsed_s, frame.scenario, {c.id: c.health for c in frame.components}
    ).to_dict()


@app.post("/api/assistant")
def assistant(request: AssistantRequest) -> dict[str, object]:
    """Grounded maintenance copilot: one answer plus whitelisted client actions."""
    elapsed = request.t
    if elapsed is None:
        elapsed = state.current_elapsed()

    frame = frame_at(elapsed, request.scenario)
    estimate = prognosis_mod.estimate(
        frame.elapsed_s, frame.scenario, {c.id: c.health for c in frame.components}
    )

    if request.mode == "procedure":
        payload = copilot.ask_procedure(request.question, frame, estimate).to_dict()
    else:
        payload = copilot.ask(request.question, frame, estimate).to_dict()

    worst = min(frame.components, key=lambda c: c.health, default=None)
    payload.update(
        {
            "t": round(frame.elapsed_s, 1),
            "scenario": frame.scenario,
            "worst": None
            if worst is None
            else {
                "id": worst.id,
                "label": worst.label,
                "health": round(worst.health, 4),
                "state": worst.state,
            },
        }
    )
    return payload


def recommendation(worst) -> str:
    return health_mod.maintenance_recommendation(worst)