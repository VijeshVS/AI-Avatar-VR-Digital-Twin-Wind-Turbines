"""FastAPI service: synthetic telemetry + explainable health for one turbine.

Endpoints
---------
``GET  /healthz``              liveness probe
``GET  /api/scenarios``        available fault programmes
``GET  /api/telemetry``        one frame at ``?t=`` seconds into the scenario
``GET  /api/components``       health only, for lightweight polling
``GET  /api/fault``            structured verdict + maintenance recommendation
``POST /api/scenario/{id}``    switch the active scenario
``GET  /api/predictions``      Phase-2 predictor prognoses per component
``GET  /api/events``           SSE stream of predictor alert events
``GET  /api/events/log``       full event history

The clock is explicit (``t``) rather than wall-clock: the client asks for the
frame it wants, so playback is reproducible and the Unity tests are stable.
``trend`` is reported only when frames are requested in non-decreasing time
order, i.e. when the client is actually streaming.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import copilot
from . import health as health_mod
from . import injection as injection_mod
from . import prognosis as prognosis_mod
from . import simulation
from .models import (
    COMPONENT_IDS,
    DEFAULT_TURBINE_ID,
    SCHEMA_VERSION,
    ComponentHealth,
    Sample,
    TelemetryFrame,
)
from .predictor.registry import PredictorRegistry, make_injection_fingerprint
from .session import SessionState


async def _predictor_clock() -> None:
    """Advance the default turbine even when no client is polling frames."""
    while True:
        try:
            await asyncio.to_thread(_update_shared_prediction)
        except Exception:
            logging.getLogger(__name__).exception("Predictor clock failed")
        await asyncio.sleep(simulation.SIM_SECONDS_PER_ASSET_HOUR)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    task = asyncio.create_task(_predictor_clock())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="Wind Turbine Digital Twin Telemetry",
    version="0.1.0",
    description="Synthetic telemetry and explainable health scoring for the VR digital-twin PoC.",
    lifespan=_lifespan,
)

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# The engine samples once per asset-hour. In simulation time that is 0.125 s,
# i.e. 8 ticks per simulated second. Declared here for the wire ``tick`` field.
SAMPLE_RATE_HZ = 1.0 / simulation.SIM_SECONDS_PER_ASSET_HOUR
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


class ProgressionRequest(BaseModel):
    kind: Literal["ramp", "step", "intermittent", "stepwise"] = "ramp"
    duration_h: float = Field(default=240.0, ge=0.0)
    curve: Literal["linear", "exponential"] = "linear"
    steps: int = Field(default=5, ge=2, le=50)
    settle_h: float | None = Field(default=None, ge=0.0)
    period_h: float | None = Field(default=None, gt=0.0)
    duty: float = Field(default=0.55, gt=0.0, le=1.0)


class InjectionRequest(BaseModel):
    turbine_id: str = Field(default=DEFAULT_TURBINE_ID)
    type: str = Field(..., min_length=1)
    severity: float = Field(default=1.0, ge=0.0, le=1.0)
    onset_asset_h: float | Literal["now"] | None = Field(default="now")
    progression: ProgressionRequest | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class ResetInjectionsRequest(BaseModel):
    turbine_id: str | None = None
    reset_t: bool = False


class ImportScenarioRequest(BaseModel):
    schema_version: int = 1
    scenario: str | None = None
    injections: list[dict[str, Any]]


state = SessionState()
predictor = PredictorRegistry()


def _update_shared_prediction() -> None:
    """Feed the shared clock through the same seek-safe measured stream."""
    turbine_id = DEFAULT_TURBINE_ID
    target = state.scenario
    active_injections = state.injections.for_turbine(turbine_id)
    tick = simulation.tick_index_at(state.current_elapsed())

    def source(index: int) -> Sample:
        return simulation.sample_at_tick(
            index, target, turbine_id=turbine_id, injections=active_injections
        )

    predictor.update(
        source(tick),
        injection_fingerprint=make_injection_fingerprint(
            [inj.to_dict() for inj in active_injections]
        ),
        sample_source=source,
    )


def _smooth(component, streaming: bool, turbine_id: str) -> ComponentHealth:
    """Blend the raw score towards the previous value when streaming.

    Smoothing state is keyed by ``(turbine_id, component_id)`` so two turbines
    never inherit each other's trend.
    """
    key = (turbine_id, component.id)
    if not streaming:
        state.smoothed_health[key] = component.health
        return component

    previous = state.smoothed_health.get(key)
    if previous is None:
        state.smoothed_health[key] = component.health
        return component

    alpha = SMOOTHING_ALPHA
    blended = previous + alpha * (component.health - previous)
    state.smoothed_health[key] = blended
    return ComponentHealth(
        id=component.id,
        label=component.label,
        health=blended,
        state=health_mod.state_for(blended),
        trend=component.trend,
        factors=component.factors,
    )


def _sample_for_prognosis(tick_t: float, scenario: str, turbine_id: str) -> Sample:
    """Telemetry stream sampler handed to prognosis; never exposes injections."""
    return simulation.sample_at_tick(
        simulation.tick_index_at(tick_t),
        scenario,
        turbine_id=turbine_id,
        injections=state.injections.for_turbine(turbine_id),
    )


def frame_at(
    elapsed_s: float,
    scenario: str | None = None,
    turbine_id: str = DEFAULT_TURBINE_ID,
) -> TelemetryFrame:
    target = scenario or state.scenario
    if target not in simulation.SCENARIOS:
        raise HTTPException(status_code=404, detail=f"unknown scenario '{target}'")

    turbine_id = turbine_id or DEFAULT_TURBINE_ID
    requested = max(0.0, elapsed_s)
    active_injections = state.injections.for_turbine(turbine_id)
    sample = simulation.sample_at(
        requested, target, turbine_id=turbine_id, injections=active_injections
    )
    elapsed = sample.elapsed_s

    streaming = elapsed >= state.last_elapsed_s
    previous = {
        component_id: health
        for (owner, component_id), health in state.previous_health.items()
        if streaming and owner == turbine_id
    }

    # Health is computed from the measured values only. A stuck or noisy sensor
    # can move this score; the true state is never passed to the scorer.
    components = tuple(
        _smooth(component, streaming, turbine_id)
        for component in health_mod.score_sample(sample, previous)
    )

    state.scenario = target
    state.last_elapsed_s = elapsed
    # Replace only this turbine's rows; other turbines keep their own trend.
    state.previous_health = {
        key: value
        for key, value in state.previous_health.items()
        if key[0] != turbine_id
    } | {(turbine_id, component.id): component.health for component in components}

    healthy_asset = (
        simulation.SCENARIOS[target].healthy_asset
        and not injection_mod.has_physical_fault(active_injections, sample.asset_time_h)
    )

    # Phase-2 predictor: tick on every frame (measured signals only).  The
    # registry replays from t=0 on a backward seek or injection change, using
    # the same deterministic sample source, so the result never depends on how
    # the operator navigated to this moment.
    inj_fp = make_injection_fingerprint(
        [inj.to_dict() for inj in active_injections]
    )
    predictor.update(
        sample,
        injection_fingerprint=inj_fp,
        sample_source=lambda tick: simulation.sample_at_tick(
            tick,
            target,
            turbine_id=turbine_id,
            injections=active_injections,
        ),
    )

    return TelemetryFrame(
        schema_version=SCHEMA_VERSION,
        turbine_id=turbine_id,
        tick=sample.tick,
        asset_time_h=sample.asset_time_h,
        elapsed_s=elapsed,
        scenario=target,
        healthy_asset=healthy_asset,
        environment=simulation.environment_from(sample.measured),
        signals=sample.signals,
        components=components,
    )


def _predictions_for_frame(frame: TelemetryFrame):
    """Return predictor state aligned to exactly the frame's tick and stream."""
    current = predictor.current(frame.turbine_id)
    if current and all(
        prognosis.asset_time_h == frame.asset_time_h for prognosis in current.values()
    ):
        return current

    active_injections = state.injections.for_turbine(frame.turbine_id)

    def source(tick: int) -> Sample:
        return simulation.sample_at_tick(
            tick,
            frame.scenario,
            turbine_id=frame.turbine_id,
            injections=active_injections,
        )

    return predictor.update(
        source(frame.tick),
        injection_fingerprint=make_injection_fingerprint(
            [inj.to_dict() for inj in active_injections]
        ),
        sample_source=source,
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
def telemetry(
    t: float | None = None,
    scenario: str | None = None,
    turbine_id: str = DEFAULT_TURBINE_ID,
) -> JSONResponse:
    """One full frame. Without ``t`` the shared session clock is used.

    ``?t=`` stays an explicit override: the PlayMode suite and the offline replay
    ask for a specific moment and must keep receiving exactly that frame.
    """
    elapsed = t if t is not None else state.current_elapsed()
    frame = frame_at(elapsed, scenario, turbine_id)
    payload = frame.to_dict()
    current = _predictions_for_frame(frame)
    # Only attach a snapshot from the same tick: another client may have
    # requested a different time while this request was being served.
    if all(p.asset_time_h == frame.asset_time_h for p in current.values()):
        payload["predictions"] = [p.to_dict() for p in current.values()]
    return JSONResponse(payload)


@app.get("/api/components")
def components(
    t: float = 0.0,
    scenario: str | None = None,
    turbine_id: str = DEFAULT_TURBINE_ID,
) -> dict[str, object]:
    frame = frame_at(t, scenario, turbine_id)
    return {
        "turbine_id": frame.turbine_id,
        "tick": frame.tick,
        "asset_time_h": round(frame.asset_time_h, 4),
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
def fault(
    t: float = 0.0,
    scenario: str | None = None,
    turbine_id: str = DEFAULT_TURBINE_ID,
) -> dict[str, object]:
    """Structured fault verdict: the predictive-maintenance hand-off point."""
    frame = frame_at(t, scenario, turbine_id)
    worst = min(frame.components, key=lambda c: c.health, default=None)
    return {
        "turbine_id": frame.turbine_id,
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
        "turbine_id": frame.turbine_id,
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
def state_snapshot(turbine_id: str = DEFAULT_TURBINE_ID) -> dict[str, object]:
    """Everything a console needs in one coherent snapshot.

    The frame and the prognosis are computed at the same instant as the session
    time, so the page can never show health from one moment next to a clock from
    another.
    """
    elapsed = state.current_elapsed()
    frame = frame_at(elapsed, state.scenario, turbine_id)
    estimate = prognosis_mod.estimate(
        frame.elapsed_s,
        frame.scenario,
        {c.id: c.health for c in frame.components},
        turbine_id=frame.turbine_id,
        sample_at_t=_sample_for_prognosis,
    )

    session = state.snapshot()
    session["t"] = round(frame.elapsed_s, 2)
    predictions = _predictions_for_frame(frame)
    return {
        "session": session,
        "frame": frame.to_dict(),
        "prognosis": estimate.to_dict(),
        "predictions": {
            component: prognosis.to_dict()
            for component, prognosis in predictions.items()
        },
    }


@app.get("/api/prognosis")
def prognosis(
    t: float | None = None,
    scenario: str | None = None,
    turbine_id: str = DEFAULT_TURBINE_ID,
) -> dict[str, object]:
    """Deterministic trend and remaining-life band per component, no model involved."""
    elapsed = t if t is not None else state.current_elapsed()
    frame = frame_at(elapsed, scenario, turbine_id)
    return prognosis_mod.estimate(
        frame.elapsed_s,
        frame.scenario,
        {c.id: c.health for c in frame.components},
        turbine_id=frame.turbine_id,
        sample_at_t=_sample_for_prognosis,
    ).to_dict()


@app.post("/api/assistant")
def assistant(request: AssistantRequest) -> dict[str, object]:
    """Grounded maintenance copilot: one answer plus whitelisted client actions."""
    elapsed = request.t
    if elapsed is None:
        elapsed = state.current_elapsed()

    frame = frame_at(elapsed, request.scenario)
    estimate = prognosis_mod.estimate(
        frame.elapsed_s,
        frame.scenario,
        {c.id: c.health for c in frame.components},
        turbine_id=frame.turbine_id,
        sample_at_t=_sample_for_prognosis,
    )

    if request.mode == "procedure":
        payload = copilot.ask_procedure(
            request.question, frame, estimate, _predictions_for_frame(frame)
        ).to_dict()
    else:
        payload = copilot.ask(
            request.question, frame, estimate, _predictions_for_frame(frame)
        ).to_dict()

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


# -- Scenario Lab injection endpoints ----------------------------------------


@app.get("/api/inject/catalog")
def inject_catalog() -> dict[str, object]:
    """Catalog metadata, signals, and one-click presets for the Scenario Lab UI."""
    return injection_mod.catalog_metadata()


@app.get("/api/inject")
def list_injections(turbine_id: str | None = None) -> dict[str, object]:
    """List active injections (optionally filtered by ``turbine_id``)."""
    return {
        "injections": [inj.to_dict() for inj in state.injections.list(turbine_id)]
    }


@app.post("/api/inject")
def create_injection(request: InjectionRequest) -> dict[str, object]:
    """Validate and register an injection; resolves 'now' to current asset time."""
    now_h = simulation.asset_time_hours(state.current_elapsed())
    progression = (
        request.progression.model_dump() if request.progression is not None else None
    )
    try:
        inj = state.injections.add(
            type_id=request.type,
            severity=request.severity,
            onset_asset_h=request.onset_asset_h,
            now_asset_h=now_h,
            progression=progression,
            params=request.params,
            turbine_id=request.turbine_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    state.clear_health_cache()
    predictor.invalidate(request.turbine_id)
    return inj.to_dict()


@app.post("/api/inject/reset")
def reset_injections(
    request: ResetInjectionsRequest | None = None,
) -> dict[str, object]:
    """Clear active injections and return the simulation to clean nominal."""
    turbine_id = request.turbine_id if request is not None else None
    reset_t = request.reset_t if request is not None else False
    state.injections.clear(turbine_id)
    predictor.invalidate(turbine_id)
    if turbine_id is None:
        state.select("nominal", reset_t=reset_t)
    else:
        state.clear_health_cache()
    return {
        "scenario": state.scenario,
        "injections": [inj.to_dict() for inj in state.injections.list()],
    }


@app.get("/api/inject/export")
def export_injections() -> dict[str, object]:
    """Export the active scenario and injections as reproducible JSON."""
    return state.injections.export_payload(state.scenario)


@app.post("/api/inject/import")
def import_injections(request: ImportScenarioRequest) -> dict[str, object]:
    """Validate and load an exported scenario JSON into session state."""
    if request.scenario is not None and request.scenario not in simulation.SCENARIOS:
        raise HTTPException(
            status_code=422, detail=f"unknown scenario '{request.scenario}'"
        )
    now_h = simulation.asset_time_hours(state.current_elapsed())
    try:
        imported = state.injections.import_payload(
            {
                "schema_version": request.schema_version,
                "scenario": request.scenario,
                "injections": request.injections,
            },
            now_asset_h=now_h,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if request.scenario is not None:
        state.select(request.scenario, reset_t=False)
    else:
        state.clear_health_cache()
    predictor.invalidate()
    return {
        "scenario": state.scenario,
        "injections": [inj.to_dict() for inj in imported],
    }


@app.delete("/api/inject/{injection_id}")
def delete_injection(injection_id: str) -> dict[str, object]:
    """Remove a single active injection by id."""
    if not state.injections.remove(injection_id):
        raise HTTPException(
            status_code=404, detail=f"unknown injection '{injection_id}'"
        )
    state.clear_health_cache()
    predictor.invalidate()
    return {
        "deleted": injection_id,
        "injections": [inj.to_dict() for inj in state.injections.list()],
    }


# -- Phase-2 predictor endpoints --------------------------------------------


@app.get("/api/predictions")
def predictions(turbine_id: str = DEFAULT_TURBINE_ID) -> dict[str, object]:
    """Current predictor prognoses per component for the given turbine."""
    frame = frame_at(state.current_elapsed(), state.scenario, turbine_id)
    current = _predictions_for_frame(frame)
    return {
        "turbine_id": turbine_id,
        "components": {comp: prog.to_dict() for comp, prog in current.items()},
    }


@app.get("/api/events/log")
def events_log(turbine_id: str = DEFAULT_TURBINE_ID) -> dict[str, object]:
    """Full event history for the given turbine."""
    return {
        "turbine_id": turbine_id,
        "events": predictor.event_history(turbine_id),
    }


@app.get("/api/events")
async def events_sse(turbine_id: str = DEFAULT_TURBINE_ID) -> StreamingResponse:
    """Server-Sent Events stream of predictor alert events.

    Clients subscribe with ``EventSource('/api/events')``.  Each new event is
    emitted once as a JSON payload; the client appends it to its own log.
    ``: keepalive`` comments keep idle proxies from closing the connection.
    """
    def _next(timeout: float):
        try:
            return alerts.get(timeout=timeout)
        except queue.Empty:
            return None

    async def _generator():
        nonlocal alerts
        alerts = predictor.subscribe(turbine_id)
        try:
            yield ": connected\n\n"
            while True:
                alert = await asyncio.to_thread(_next, 15.0)
                if alert is None:
                    yield ": keepalive\n\n"
                    continue
                payload = {"turbine_id": alert.turbine_id, **alert.event}
                yield f"data: {json.dumps(payload)}\n\n"
        finally:
            predictor.unsubscribe(alerts)

    alerts = None
    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def recommendation(worst) -> str:
    return health_mod.maintenance_recommendation(worst)
