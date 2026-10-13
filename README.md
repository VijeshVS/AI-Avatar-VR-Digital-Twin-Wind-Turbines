# AI-Driven Avatar-Based VR Digital Twin for Predictive Maintenance & Fault Visualization of Wind Turbines

An immersive 3D digital twin of a wind turbine in which every component is an **AI-driven avatar** bound to a telemetry stream, carrying a computed health state, and expressing degradation perceptually — through sound, colour and motion — rather than as a number on a chart.

The same twin serves three roles: a **live monitoring view**, a **predictive-maintenance decision-support demonstrator**, and a **procedural training environment**.

## Stack

- **Client:** Unity LTS 6000.x, URP (Metal), OpenXR + XR Interaction Toolkit
- **Data & models:** Python — FastAPI, pandas/numpy, scikit-learn (simulation, feature engineering, explainable health scoring)
- **Content:** exclusively free, Unity-importable assets (FBX/OBJ/glTF), CC0/CC-BY

## Scope

This is a **scoped pilot / feasibility demonstrator**, not a production system. It runs against **synthetic telemetry**, on **desktop hardware with no VR headset available**, using **zero paid assets, plugins or tools**.

Headline limitations, stated up front:

- **Synthetic-data validity** — accuracy figures demonstrate the pipeline, not real-world predictive performance.
- **No VR hardware validation** — the XR path is authored to OpenXR/XRI conventions and exercised via Device Simulator, which validates logic but not ergonomics. No claim of a validated, comfortable VR experience is made.

## Documentation

- [`docs/PRD.md`](docs/PRD.md) — Product Requirements Document (problem statement, users, user stories, functional and non-functional requirements, assumptions, limitations)
- [`topic.md`](topic.md) — original project brief