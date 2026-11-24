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
| `GET` | `/api/state` | One snapshot: `session`, `frame`, `prognosis` — poll this |
| `GET` | `/api/session` | Session only |
| `POST` | `/api/session` | Control the clock, scenario and focus |
| `GET` | `/api/telemetry?t=&scenario=` | One frame; `t` omitted → session clock |
| `GET` | `/api/prognosis?t=&scenario=` | Deterministic trend and RUL band |
| `POST` | `/api/assistant` | Grounded copilot: `mode: "summary"` or `"procedure"` |
| `GET` | `/api/scenarios` | Catalogue |
| `GET` | `/api/components?t=` | Health-only roll-up |
| `GET` | `/api/fault?t=` | Worst component + recommendation |
| `POST` | `/api/scenario/{id}` | Legacy switch; honours `reset_clock` |

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

## `/api/state`

```json
{
  "session":   { "scenario": "gearbox_degradation", "t": 60.0, "playing": false,
                 "speed": 1.0, "focus": null, "focus_seq": 0 },
  "frame":     { "schema_version": 1, "tick": 600, "elapsed_s": 60.0, "...": "..." },
  "prognosis": { "t": 60.0, "worst": "gearbox", "components": [ "...": "..." ] }
}
```

`session.t`, `frame.elapsed_s` and `prognosis.t` are computed from the same
instant, so the page cannot show a clock and a health score from different
moments.

## Tests

```bash
cd tools/telemetry
uv run pytest                    # 110 tests, no network
uv run uvicorn telemetry.main:app --port 8000 --reload
```

The suite never sleeps: `SessionState(now=...)` takes an injected clock, and the
HTTP tests freeze the clock with `playing: false` before asserting.
