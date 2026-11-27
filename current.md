# Current Project Summary

## What the project is

This is a desktop-first, VR-ready digital twin of a wind turbine for predictive-maintenance demonstration and fault visualization.

Its core idea is:

> Telemetry is converted into component health, and each turbine component expresses that health visually, spatially, and audibly instead of only showing a number.

It is explicitly a pilot/feasibility demonstrator using synthetic data—not a production monitoring system or validated predictive-maintenance product.

## Current architecture

```text
Synthetic telemetry
        ↓
Rule-based health scoring + explainability
        ↓
FastAPI service and shared session clock
        ↓
Unity turbine twin + browser operator console + AI copilot
```

The project has three main parts:

1. Unity client
2. Python telemetry and health service
3. Browser-based operator console

## Features currently implemented

### 1. Procedural Unity wind-turbine twin

The Unity MVP creates a notional 3.6 MW turbine procedurally from primitives:

- Tower
- Nacelle
- Rotor and hub
- Three blades
- Main bearing
- Gearbox
- Generator
- Pitch system

Five components are represented as independent avatars:

- Blade set
- Main bearing
- Gearbox
- Generator
- Pitch system

The turbine is placed in a generated environment containing procedural hilly terrain, grass, trees, boulders, an HDR skybox, and livestock groups. Collision and separation logic reduces overlaps between environment objects and animals.

### 2. Synthetic telemetry simulation

The FastAPI service generates deterministic, reproducible telemetry for one turbine.

Signals include wind speed, ambient temperature, rotor RPM, active power, power ratio, yaw angle, gearbox temperature and vibration, nacelle vibration, generator temperature, converter faults, pitch angle and error, blade-pass frequency, rotor azimuth, and rotor imbalance.

Available scenarios:

| Scenario | Simulated fault |
|---|---|
| `nominal` | Healthy turbine |
| `gearbox_degradation` | Gearbox bearing wear, heat, vibration, and slight power derating |
| `generator_overheat` | Cooling loss, temperature rise, converter warnings, and power derating |
| `blade_imbalance` | Rotor imbalance and once-per-revolution vibration |
| `pitch_fault` | Pitch actuator/feedback drift and position error |

Faults ramp over time so degradation can be observed rather than appearing instantly.

### 3. Explainable component health scoring

Each component receives a health score from 0 to 1:

- Healthy: `>= 0.75`
- Warning: `0.45–0.75`
- Critical: `< 0.45`

Every score includes contributing signals, warning and critical thresholds, severity, weight, contribution, and trend. The scoring is transparent and rule-based.

### 4. Perceptual avatar fault visualization

Telemetry directly changes the turbine components through:

- Green, amber, and red color bands
- Increasing emission and glow
- Pulsing emission
- Component-specific tremor
- Fault-specific vibration frequency
- Critical alarm tone
- Rotor rotation and blade-pitch changes

Healthy parts remain comparatively stable while faulted parts react. The Unity HUD shows health bars, state labels, plant-level worst-component information, and the dominant factor behind each score.

### 5. Desktop navigation and focus mode

The current primary interaction path is desktop:

- WASD movement
- Q/E vertical movement
- Right-mouse camera look
- Shift for faster movement
- Component selection by clicking
- Number keys `1–5`
- Tab and arrow-key cycling
- Escape to return to overview

When a component is focused, the camera smoothly flies to it, the selected component is emphasized, other components are dimmed, structural objects become translucent, and the camera can return to its original position.

### 6. Offline replay mode

Unity can run without the Python service using bundled telemetry frames:

- `-vrar-sample` replays sample telemetry
- `-vrar-time <seconds>` jumps to a scenario time
- `-vrar-endpoint <url>` selects a service endpoint
- `-vrar-follow` makes Unity follow the shared service clock

The client displays connection status and can continue showing the last received state when the service is unavailable.

### 7. Shared session clock

The backend owns a shared clock used by the browser and Unity clients. It supports play/pause, time seeking, playback speed, scenario switching, component focus commands, and synchronized Unity/browser state.

Main API endpoints include:

- `/api/state`
- `/api/session`
- `/api/telemetry`
- `/api/prognosis`
- `/api/assistant`
- `/api/scenarios`
- `/api/components`
- `/api/fault`
- `/api/scenario/{id}`

### 8. Prognosis and remaining-life estimation

The service re-scores previous scenario points, fits a health trend, extrapolates toward the critical threshold, and reports a confidence value with coarse remaining-life bands:

- Stable
- `<8 d`
- `8–30 d`
- `>30 d`
- Critical
- Unknown

This uses a time-compression assumption where one simulated second represents eight asset-hours. It is a demonstrator estimate, not a validated remaining-useful-life prediction.

### 9. AI maintenance copilot

The copilot is available from Unity and the web console. It supports preset and free-form questions such as:

- What is wrong with the turbine?
- Why is it failing?
- What should I do next?
- Explain it to a trainee.

It can use an OpenAI-compatible provider, but also works offline through a deterministic rule narrator. The model does not generate health numbers; those come from the telemetry and health engine.

Validated actions are limited to:

- Focus a component
- Change scenario
- Change playback time

### 10. Repair-procedure responses

The service contains authored generic repair procedures with diagnosis, tools, safety requirements, ordered steps, rationale, and a safety disclaimer. The web console can render these as repair plans.

This is currently an information feature, not a full interactive training simulator.

### 11. Browser operator console

The FastAPI service serves a browser console at `/`. It provides:

- Component health cards
- Health bars and state labels
- Dominant contributing factors
- Health-history sparklines
- Prognosis bands
- Scenario selection
- Play/pause
- Playback-speed control
- Timeline scrubbing
- Component focus commands for Unity
- AI copilot
- Repair-plan display

The browser and Unity client share the same backend clock.

### 12. XR-ready configuration

The project includes OpenXR, XR Interaction Toolkit, XR Management, XR input actions, OpenXR settings, and XR loader configuration. A simulated HMD rig is included for desktop-side camera/navigation testing.

Real headset comfort, stereo rendering, controller ergonomics, haptics, and headset performance have not been validated.

### 13. Automated testing

The Python service currently passes:

```text
110 passed, 1 warning
```

Python tests cover telemetry generation, fault progression, health scoring, explainability, prognosis, session-clock behavior, API contracts, copilot validation, repair procedures, and the web console.

Unity PlayMode tests cover telemetry compatibility, procedural turbine construction, avatar color/emission/tremor behavior, rotor movement, component focus, camera framing, scene loading, live/offline telemetry wiring, and livestock placement.

## What is not implemented yet

Several PRD aspirations remain planned or incomplete:

- No trained machine-learning model
- No real SCADA, OPC-UA, CMS, ERP, or site-data integration
- No real fault recordings
- No pandas, NumPy, or scikit-learn implementation in the current telemetry package
- No Parquet historical-data pipeline
- No learned anomaly detector or Isolation Forest
- No production-grade probability calibration
- No real predictive-accuracy validation
- No full interactive repair-training workflow
- No Unity tool grabbing, step validation, trainee scoring, or report export
- No role/login system
- No haptic feedback implementation
- No validated headset build or real VR hardware testing
- No fleet-scale or multi-user collaboration
- No remote turbine control or actuation
- No photorealistic/imported turbine CAD model
- No LOD or standalone-VR performance validation

## Bottom line

The project currently proves the complete telemetry → health → explainability → avatar visualization → operator-console loop, with an optional grounded language-model interface.

It is best described as an end-to-end wind-turbine digital-twin demonstrator, not yet as a production predictive-maintenance, VR-training, or machine-learning system.

## Repository state note

The working tree currently contains uncommitted local changes, including `CopilotPanel.cs`, `style.css`, `ProjectVersion.txt`, VS Code settings, and an untracked `.playwright-mcp` directory.
