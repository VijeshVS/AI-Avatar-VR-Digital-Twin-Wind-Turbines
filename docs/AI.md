# AI copilot

What the "AI" in this iteration actually is, how to run it, and what it is not.

## The honest one-paragraph version

There is **no trained model** in this iteration, and no dataset. What exists is a
deterministic health engine plus a **grounded language-model copilot**: the engine
computes every number, the model only phrases it and asks the client to perform a
whitelisted action. That split is deliberate — it is the part of an "AI
maintenance assistant" that survives scrutiny, and it needs no training data.

## Architecture

```
simulation.build_signals(t)          deterministic synthetic telemetry
        │
health.score_component()             explainable envelopes → health + factors
        │
prognosis.estimate(t)                least-squares trend → RUL band + confidence
        │
copilot.build_context()              compact JSON: health, top factor, band, ids
        │
        ├── LLM (OpenAI-compatible)  → {"answer": "...", "actions": [...]}
        └── rule narrator (no key)   → same shape, deterministic
        │
        └── validate_actions()       whitelist: component ids, scenario ids, 0..3600 s
                │
Unity CopilotPanel                   renders answer, executes actions
```

Three guarantees, all tested:

1. **Numbers are never generated.** `copilot.build_context()` is the only source
   of figures; the system prompt forbids inventing values.
2. **Actions are never trusted.** `validate_actions()` drops unknown component
   ids, unknown scenarios, out-of-range times and unknown action types, and caps
   the list at three.
3. **The demo never depends on the network.** With no key, or on any provider
   error, the rule narrator returns the same response shape with
   `source: "rules"`.

## Running it

The service reads provider settings from the environment:

```bash
cd tools/telemetry
cp .env.example .env          # then fill in the key
set -a && . ./.env && set +a  # export it into this shell
uv run uvicorn telemetry.main:app --port 8000 --reload
```

Any OpenAI-compatible endpoint works: OpenAI, Groq, OpenRouter, Together,
vLLM, LM Studio, or Ollama at `http://localhost:11434/v1`. Only two variables
matter:

| Variable | Default | Meaning |
|---|---|---|
| `VRAR_LLM_API_KEY` | *(empty)* | Empty disables the model and uses the rule narrator |
| `VRAR_LLM_BASE_URL` | `https://api.openai.com/v1` | Chat-completions base URL |
| `VRAR_LLM_MODEL` | `gpt-4o-mini` | Model id at that provider |
| `VRAR_LLM_TIMEOUT_S` | `12` | Hard timeout; the panel gives up and shows the error |

No key configured is a **supported mode**, not a failure: it is what the test
suite runs against, and what you demo if the network dies.

## The two endpoints

```bash
# Deterministic prognosis — no model involved
curl "http://127.0.0.1:8000/api/prognosis?t=50&scenario=gearbox_degradation"

# Grounded copilot — one answer plus whitelisted actions
curl -X POST http://127.0.0.1:8000/api/assistant \
  -H 'Content-Type: application/json' \
  -d '{"question":"Why is the gearbox red?","t":150,"scenario":"gearbox_degradation"}'
```

Response:

```json
{
  "answer": "Gearbox is critical at 4%: gearbox oil temperature rise is 18.09 degC, against a warning of 6 and a critical of 15 degC. It is already at the critical threshold. Plan corrective maintenance on gearbox at the next convenient window.",
  "source": "rules",
  "actions": [{ "type": "focus_component", "component_id": "gearbox" }],
  "detail": "no API key configured",
  "t": 150.0,
  "scenario": "gearbox_degradation",
  "worst": { "id": "gearbox", "label": "Gearbox", "health": 0.038, "state": "critical" }
}
```

Action types the client understands:

| Action | Payload | Effect in the twin |
|---|---|---|
| `focus_component` | `component_id` | Camera flies to the component, others dim |
| `set_scenario` | `scenario` | Switches the fault programme through the service |
| `set_time` | `seconds` | Scrubs the playback clock |

## Repair plans: `mode: "procedure"`

The same endpoint returns a grounded repair plan when asked:

```bash
curl -X POST http://127.0.0.1:8000/api/assistant \
  -H 'Content-Type: application/json' \
  -d '{"question":"How do I fix it?","mode":"procedure","t":150,"scenario":"gearbox_degradation"}'
```

```json
{
  "answer": "Gearbox is critical at 4% ...",
  "source": "rules",
  "mode": "procedure",
  "diagnosis": { "component_id": "gearbox", "health": 0.038, "band": "critical", "top_factor": { } },
  "procedure": {
    "component_id": "gearbox",
    "title": "Gearbox bearing inspection and replacement",
    "tools": ["oil sample kit", "borescope", "bearing puller", "torque wrench"],
    "safety": ["Lock out / tag out the turbine ...", "..."],
    "steps": [
      { "n": 1, "id": "loto", "action": "Isolate and lock out the turbine", "detail": "...",
        "tool": null, "safety": true, "why": "..." }
    ]
  },
  "actions": [{ "type": "focus_component", "component_id": "gearbox" }],
  "disclaimer": "Demonstrator procedure written for this pilot. It is not a certified ..."
}
```

The steps are **authored data** in `procedures.py` — one plan per component, generic
tools, no torque values or part numbers. The model may select a subset and write
one sentence of rationale per step, but it cannot add a step, invent a tool, or
reorder the sequence. If it omits a safety step, the server discards its selection
and returns the full authored procedure. With no key, the authored procedure is
returned verbatim (`source: "rules"`).

That guardrail is the point: a model is good at phrasing, and bad at remembering
whether isolation comes before or after opening a nacelle.

## The prognosis, and its one big assumption

`prognosis.estimate()` re-scores the scenario at ten-second intervals over the
last 90 s, fits a straight line to each component's health, and extrapolates to
the 0.45 critical threshold. It reports the slope, the days to threshold, a
coarse band (`<8 d`, `8-30 d`, `>30 d`), and an R²-based confidence. At `t=50`
on `gearbox_degradation` it reports about 16 days; by `t=70` the component is
critical.

The assumption is **time compression**: one second of scenario time stands for
eight hours of asset life (`prognosis.HOURS_PER_SIM_SECOND`). The 90 s fault ramp
therefore reads as roughly a month. Change the constant and every estimate scales
with it; the docstring says so, and the HUD does not hide it.

What this is not: it is not a learned degradation model, it does not know about
load history, and it will happily extrapolate a non-linear ramp as a line. It is
a defensible trend estimate, not a prediction of field failure.

## In the client

`Assets/Scripts/Runtime/AI/CopilotPanel.cs` draws a panel on the right with four
preset questions and a free-text field. **F2** hides it. The answer renders in
place; returned actions are applied immediately — so "Why is it failing?" flies
the camera to the worst component without a second click.

The same endpoint backs the browser console at `/`, which adds the
`mode: "procedure"` view: diagnosis chips, tool list and numbered steps. See
[`WEB.md`](WEB.md) for the page and [`API.md`](API.md) for the wire format.

`MvpBootstrap` creates the panel in `Awake()`, so the scene needs no wiring.

## What to say if asked "where is the machine learning?"

Say this: the pilot's AI layer is an **explainable decision-support assistant**
grounded on computed physics, not a trained predictor. The health scores are
rule-based envelopes with per-signal contributions; the prognosis is a measured
trend with an explicit compression assumption; the language model is constrained
to narration and validated actions. The next iteration adds a learned detector
trained on nominal-only runs (PCA/SPC + IsolationForest), evaluated on held-out
synthetic faults for detection latency, false-alarm rate and lead time. That is
written down in `docs/EVAL.md` when it exists — it does not yet.

## Verification

```bash
cd tools/telemetry && uv run pytest        # includes copilot and prognosis contracts
unity test --mode PlayMode --filter CopilotTests
```

The Python suite forces the offline path, so it never calls a provider even on a
machine with a key configured.
