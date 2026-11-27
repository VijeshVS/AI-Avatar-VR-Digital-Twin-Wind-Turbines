# Service API

The FastAPI service is the single source of truth for the twin. Two clients read
it — the Unity twin and (next) the web console — and they share one clock, so a
scenario change or a seek moves both views together.

Base URL in development: `http://127.0.0.1:8000`. Interactive docs: `/docs`.

## The shared clock

The session owns the clock:

| Field | Meaning |
|---|---|
| `scenario` | Active fault programme |
| `t` | Scenario time in seconds |
| `playing` | Whether `t` advances |
| `speed` | Time multiplier, clamped to `0.1–100` |
| `focus` | Component the twin should look at, or `null` |
| `focus_seq` | Increments only when `focus` changes, so a client applies a camera move once |

Rules:

- Switching scenario **restarts the ramp at `t=0`** unless `reset_t: false`.
- `t` is clamped to `0–3600`; `speed` to `0.1–100`.
- `focus: ""` clears the focus.
- `?t=` on `/api/telemetry` remains an **explicit override** for tests, replay and
  `-vrar-time`. It never moves the session clock.
- Unity follows the session with `-vrar-follow` (or `VRAR_FOLLOW=1`); without it,
  the client keeps its own token clock and only scenario changes propagate.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/state` | One snapshot: `session`, `frame`, legacy `prognosis`, Phase-2 `predictions` — poll this |
| `GET` | `/api/session` | Session only |
| `POST` | `/api/session` | Control the clock, scenario and focus |
| `GET` | `/api/telemetry?t=&scenario=&turbine_id=` | One frame; `t` omitted → session clock |
| `GET` | `/api/prognosis?t=&scenario=&turbine_id=` | Deterministic trend and RUL band |
| `POST` | `/api/assistant` | Grounded copilot: `mode: "summary"` or `"procedure"` |
| `GET` | `/api/scenarios` | Catalogue |
| `GET` | `/api/components?t=&turbine_id=` | Health-only roll-up |
| `GET` | `/api/fault?t=&turbine_id=` | Worst component + recommendation |
| `POST` | `/api/scenario/{id}` | Legacy switch; honours `reset_clock` |
| `GET` | `/api/inject/catalog` | Scenario Lab catalog metadata, signals, and demo presets |
| `GET` | `/api/inject` | List active injections (optional `?turbine_id=`) |
| `POST` | `/api/inject` | Create an injection (`onset_asset_h: "now"` resolves to current asset time) |
| `DELETE` | `/api/inject/{id}` | Remove one injection |
| `POST` | `/api/inject/reset` | Clear all injections and return to `nominal` |
| `GET` | `/api/inject/export` | Export active scenario and injections as JSON |
| `POST` | `/api/inject/import` | Validate and load an exported scenario JSON |
| `GET` | `/api/predictions?turbine_id=` | Latest Phase-2 component health and failure prognosis |
| `GET` | `/api/events` | Server-Sent Events stream of new predictor alerts |
| `GET` | `/api/events/log?turbine_id=` | Event history for the latest replay of a turbine |

`turbine_id` defaults to `"T1"`, so every pre-fleet client keeps working.

## Driving it from curl

```bash
# Pause at t=60 on the gearbox scenario
curl -X POST http://127.0.0.1:8000/api/session \
  -H 'Content-Type: application/json' \
  -d '{"scenario":"gearbox_degradation","t":60,"playing":false}'

# Read the whole snapshot
curl http://127.0.0.1:8000/api/state

# Trigger the fault from the beginning, at 2x
curl -X POST http://127.0.0.1:8000/api/session \
  -H 'Content-Type: application/json' \
  -d '{"scenario":"gearbox_degradation","playing":true,"speed":2}'

# Ask the twin to look at a component
curl -X POST http://127.0.0.1:8000/api/session \
  -H 'Content-Type: application/json' \
  -d '{"focus":"gearbox"}'

# Ask the copilot about the current moment
curl -X POST http://127.0.0.1:8000/api/assistant \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is wrong?"}'

# Ask for a grounded repair plan instead of a summary
curl -X POST http://127.0.0.1:8000/api/assistant \
  -H 'Content-Type: application/json' \
  -d '{"question":"How do I fix it?","mode":"procedure"}'
```

`mode: "procedure"` returns authored steps from `procedures.py`, optionally
selected and explained by the model. See [`AI.md`](AI.md) for the guardrails.

## Sampling grid and frame shape

The engine samples **once per asset-hour**. The demo compresses eight
asset-hours into one simulation second, so one tick is `0.125 s` of scenario
time. A 30-day horizon is therefore 720 points — cheap to recompute after a
seek.

Each sample carries:

| Field | Meaning |
|---|---|
| `turbine_id` | Machine identity, `"T1"` by default |
| `tick` | Engine tick index; one tick = one asset-hour |
| `asset_time_h` | Machine time in hours (`tick` as a float) |
| `elapsed_s` | Scenario time in seconds; snapped to the nearest tick |
| `signals[].value` | Measured value, the only thing the health engine sees |
| `signals[].true` | True machine value, before sensor corruption |
| `signals[].measured` | Sensor-reported value (equal to `true` for healthy sensors) |
| `predictions[]` | Optional Phase-2 predictor snapshot when requested through `/api/telemetry` |

The simulator is layered:

```text
nominal generator -> physical modifiers -> sensor-quality modifiers -> sample
```

Physical modifiers change `true` and `measured` together. Sensor-quality
modifiers (stuck, dropout, noise) change only `measured`. This separation is
what lets a later predictor distinguish a real fault from a bad sensor.

Noise is seeded per `(turbine_seed, signal, tick)`, so scrubbing backward or
jumping directly to an hour returns byte-identical data.

## `/api/state`

```json
{
  "session":   { "scenario": "gearbox_degradation", "t": 60.0, "playing": false,
                 "speed": 1.0, "focus": null, "focus_seq": 0 },
  "frame":     { "schema_version": 1, "turbine_id": "T1", "tick": 480,
                 "asset_time_h": 480.0, "elapsed_s": 60.0, "...": "..." },
  "prognosis": { "t": 60.0, "worst": "gearbox", "components": [ "...": "..." ] },
  "predictions": { "gearbox": { "health": 0.8, "status": "degrading", "band": "8-30 d" } }
}
```

`session.t`, `frame.elapsed_s` and `prognosis.t` are computed from the same
instant, so the page cannot show a clock and a health score from different
moments.

`prognosis` is the pre-existing health trend. `predictions` is the Phase-2
raw-measurement predictor and is keyed by component id. A component prognosis
includes `health`, `state`, `status`, optional `ttf_days: [low, high]`, a `band`,
heuristic `confidence`, explainability contributors, active events, and
suspected sensor faults. The frame endpoint returns the same component
prognoses as an array in `predictions`, which Unity can parse with `JsonUtility`.

The predictor never reads injected/true values: it consumes `sample.measured`.
It replays chronologically on the 1-asset-hour grid after a seek, scenario
switch, or injection change. The runtime clock also advances the default
turbine predictor when no client is polling, so `/api/predictions` stays current.

### Baseline commissioning

Baseline coefficients and residual spreads are checked in at
`tools/telemetry/src/telemetry/predictor/baseline_T1.json`. Recreate them from
14 nominal asset-days with:

```bash
cd tools/telemetry
uv run python scripts/calibrate_baseline.py
```

The simulator's `power_ratio` is nominally constant, so thermal baselines use
measured rotor-speed load fraction rather than fitting a singular power-ratio
feature. The JSON records the fitted input range; residual models are disabled
outside that commissioned range. EWMA spread is calibrated from nominal residual
sequences because the simulator's band-limited noise is autocorrelated; a
conservative residual floor prevents this synthetic commissioning set from
overstating statistical certainty.

### Predictor and alert requests

```bash
curl http://127.0.0.1:8000/api/predictions
curl http://127.0.0.1:8000/api/events/log
curl -N http://127.0.0.1:8000/api/events
```

The SSE endpoint emits `data: {json}` records and keepalive comments. Events
carry `event_id`, `component`, `type`, `severity`, `asset_time`, `message`,
`evidence`, and `status` (`shock`, `imminent`, or `failed`).

## Tests

```bash
cd tools/telemetry
uv run pytest                    # includes predictor math, replay and API tests
uv run uvicorn telemetry.main:app --port 8000 --reload
```

The suite never sleeps: `SessionState(now=...)` takes an injected clock, and the
HTTP tests freeze the clock with `playing: false` before asserting.
