# PRD — AI-Driven Avatar-Based VR Digital Twin for Predictive Maintenance & Fault Visualization of Wind Turbines

**Version:** 0.3 — Scoped Pilot, Desktop-First / VR-Ready
**Status:** Draft for review
**Scope intent:** Demonstrate the concept end-to-end using **only free, downloadable, Unity-importable assets**, developed and demoed on **desktop hardware with no VR headset available**. No bespoke CAD, no photoreal geometry, no production ML accuracy claims.
**Delivery model:** The system ships as a **desktop 3D digital twin that is architecturally VR-ready**. VR input, stereo rendering and XR interaction tooling are built in and exercised through Unity's Device Simulator, but **headset validation is deferred** and is not a pilot exit criterion (see §7).

---

## 1. Problem Statement

Wind turbine maintenance is reactive and calendar-based. Interval-based servicing replaces healthy components and still misses incipient faults; an undetected gearbox or bearing degradation becomes a multi-day outage with crane and crew mobilisation cost. The difficulty is not that data is absent — SCADA and CMS data exist — but that:

- **Data is not visual.** Vibration, temperature and power signals live in 2D charts. A technician cannot form a spatial or perceptual model of *which* component is degrading or *how bad it sounds*.
- **Diagnosis depends on scarce experts.** Interpretation needs vibration analysts and OEM specialists; site staff record "abnormal noise" and defer to a visit.
- **Training is generic.** Technicians rarely witness a real failure develop, so recognition skill is built slowly and expensively.

This project builds an **immersive 3D digital twin of a wind turbine in which each component is an interactive avatar** bound to a telemetry stream, carrying a machine-learned health state, and — when degradation crosses a threshold — expressing the fault perceptually (audio, visual, motion) so the user *hears and sees* the fault rather than reading a number. One asset serves three roles: a live monitoring view, a predictive decision-support demo, and a procedural training environment. The spatial-interaction layer is authored to the **XR Interaction Toolkit / OpenXR** conventions so the same scene runs on a headset without rework.

**Feasibility framing (pilot).** This is a demonstrator, not a deployable product. It runs on one generic wind turbine model assembled from freely downloadable game assets, on one desktop workstation, against synthetic telemetry. The scientific claim is "an avatar-driven spatial twin makes degradation legible and rehearsable" — **not** that the models achieve real-world predictive accuracy, and **not** that VR ergonomics have been validated. Section 7 states this and related bounds explicitly.

---

## 2. Target Users

| # | User | Context | Primary need |
|---|------|---------|---------------|
| U1 | **Reliability / Maintenance Engineer** | Desk workstation (pilot: Apple Silicon laptop) | See which component is degrading and what to do next, without reading charts |
| U2 | **Field Technician / Trainee** | Training station; headset when available | Recognise the fault by ear and appearance; rehearse the correct repair sequence safely |
| U3 | **Condition Monitoring Analyst** | Desk | Validate a prediction, see why it was raised, and correct it |
| U4 | **Researcher / Evaluator** (project sponsor, thesis, demo audience) | Lab or presentation | Reproducible scenario, credible method, honest limits |

---

## 3. Use Cases (as User Stories)

**Epic A — Live Twin & Monitoring**
- **US-A1** As the engineer, I want to explore the turbine as an explorable 3D twin in an immersive scene so that I can locate a component by sight rather than by tag list.
- **US-A2** As the engineer, I want component avatars to change colour/emissive intensity as health degrades so that risk is visible without reading numbers.
- **US-A3** As the analyst, I want to select an avatar and see its health score, trend, and the sensor values behind it in the same view so that I can sanity-check a prediction.

**Epic B — Predictive Analytics**
- **US-B1** As the engineer, I want a health score and a failure-probability indicator per component so that attention goes to the worst asset first.
- **US-B2** As the researcher, I want the model to state its top contributing features so that the result is defensible rather than a black box.
- **US-B3** As the analyst, I want the system to flag low-confidence predictions as "needs inspection" rather than assert them, so that weak signals are not over-trusted.

**Epic C — Fault Visualisation**
- **US-C1** As the engineer, I want to inject a fault into the twin so that I can watch degradation develop before it happens in the field.
- **US-C2** As the trainee, I want the faulted avatar to emit its characteristic sound and abnormal motion so that I learn to recognise it by ear and sight.
- **US-C3** As the researcher, I want to replay a historical/synthetic failure scenario at variable speed so that I can study how degradation evolved.

**Epic D — Guided Repair & Training**
- **US-D1** As the trainee, I want a step-by-step guided procedure anchored to the actual component with correct tools and safety steps so that I execute the repair correctly the first time.
- **US-D2** As the trainee, I want a scenario scored on diagnosis, sequence, and safety compliance so that competency is measured.
- **US-D3** As the trainee, I want to make mistakes (wrong tool, skipped isolation) with visible consequences but no real equipment risk.

**Epic E — Reproducibility & Administration**
- **US-E1** As the researcher, I want the whole scenario — data, model, fault, scoring — reproducible from a single seed and config so that results can be re-run and cited.
- **US-E2** As the evaluator, I want a simple login/role switch so that the demo can present different views (engineer vs trainee) without full enterprise security.

---

## 4. Functional Requirements

### 4.1 Asset Sourcing & Licence Compliance *(hard constraint)*
- **FR-1.1** All 3D content shall originate from **free and legally downloadable** sources. No purchased asset packs, no OEM geometry, no contractor-modelled CAD.
- **FR-1.2** All source assets shall be in a format **Unity imports natively** — **FBX, OBJ, glTF/GLB, or DAE**. Assets in STEP, IGES, SolidWorks, Parasolid or native CAD formats are **out of scope** unless converted to glTF/FBX by a free tool before use.
- **FR-1.3** Accepted licence classes only: **CC0 / public domain, CC-BY, or explicit free-to-use with attribution**. The licence and source URL of every asset shall be recorded in a manifest (`ASSET_MANIFEST.md`) and attribution shall be shipped with the build.
- **FR-1.4** Preferred sources, in priority order: Sketchfab (filter CC0 / CC-BY), Poly Haven / ambientCG (CC0 textures and HDRIs), Unity Asset Store free-tier items, CGTrader free items with `.unitypackage` or FBX, and Blender-compatible `.blend` files re-exported to glTF.
- **FR-1.5** **Dimensional ground truth** for correct proportions and scale shall come from public-domain reference specifications — IEA Wind Task 37 (WP2.1 land-based geared reference turbine; NREL/TP-5000-73492) or the NREL 5 MW reference turbine (NREL/TP-500-38060). These supply numbers, not meshes.
- **FR-1.6** Where no free component model is available, the component shall be represented by a **Unity primitive or a procedurally generated mesh** (gear, bearing race, bolt ring, housing) rather than a bespoke modelled asset.
- **FR-1.7** Total unique 3D assets shall be kept small (target **≤ 40 models**, ~8 assemblies) so that the project stays within free-asset feasibility and load times stay low.
- **FR-1.8** All assets shall be optimised in-engine to a VR-appropriate budget: **≤ 100k triangles per assembly at LOD0**, compressed textures, max 3 LOD levels per assembly.

### 4.2 Asset Model & Twin Structure
- **FR-2.1** The turbine shall be represented as a hierarchical assembly of at minimum: **rotor/blades, hub, main bearing, gearbox, generator, nacelle, tower**. Additional components optional.
- **FR-2.2** Each component shall be an **avatar**: an interactive entity with its own health state, colour/emissive response, audio signature, and animation behaviour.
- **FR-2.3** The twin shall support exploded view, isolation (hide surrounding assemblies to expose internals), and first-person navigation with teleport between assemblies.
- **FR-2.4** Geometry scale and orientation shall conform to the chosen reference specification (real-world metres), so that dimensional claims are defensible.

### 4.3 Telemetry & Simulation
- **FR-3.1** A **Python simulator** shall generate realistic SCADA-like signals (wind speed, rotor speed, power, pitch, yaw) and CMS-like signals (per-bearing and per-gearbox vibration RMS and dominant-frequency, temperatures) with configurable operating regimes.
- **FR-3.2** The simulator shall embed **three labelled fault classes** with realistic onset and ramp: (a) main-bearing degradation, (b) gearbox fault, (c) blade/pitch actuator misalignment. Each class shall inject characteristic signal changes consistent with its physics.
- **FR-3.3** The system shall record historical runs to **Parquet** and replay them at variable speed (0.1×–100×), with a seed for reproducibility.
- **FR-3.4** The client shall run fully **offline** on bundled recorded data; live streaming is not required for the pilot.

### 4.4 Health Scoring & Prediction
- **FR-4.1** Each component shall have a normalised **health score (0–1)** computed from its feature set.
- **FR-4.2** The system shall output a **failure-probability indicator** and a coarse **remaining-life band** (e.g., >30 d / 8–30 d / <8 d) per component, with a confidence value.
- **FR-4.3** Detection shall use **explainable classical methods** — normalised baseline deviation, rolling trend, and a simple unsupervised detector (e.g., Isolation Forest / EWMA control limits on engineered features). No deep-learning claim.
- **FR-4.4** Every prediction shall return **top contributing features** and the model/config version used.
- **FR-4.5** Predictions below a configured confidence threshold shall be reported as **"insufficient evidence — inspect"** rather than as a diagnosis.
- **FR-4.6** Performance shall be reported on **held-out synthetic fault runs** (detection latency, false-alarm rate, lead time) and labelled explicitly as synthetic-data performance.

### 4.5 Fault Visualisation & Avatar Behaviour
- **FR-5.1** Fault injection shall cover the three fault classes of FR-3.2 and shall be manually triggerable and triggerable from the simulator timeline.
- **FR-5.2** A faulted avatar shall express severity through **multi-sensory cues**: audio (spectral/vibrational loop whose mix tracks severity), visual (emissive colour shift, heat glow, deformation or particle emission), and kinematic (abnormal motion amplitude/frequency).
- **FR-5.3** Avatar behaviour shall follow a severity state machine: `nominal → early → advanced → critical → failed`.
- **FR-5.4** A fault on one component shall raise visible risk indicators on dependent components (e.g., gearbox fault raises generator and main-bearing indicators) to demonstrate coupled degradation.
- **FR-5.5** Faulted and nominal states shall be **distinguishable at a glance** from across the nacelle, and distinguishable **by audio alone** with eyes closed (a testable demo criterion).

### 4.6 Guided Repair & Training Scenarios
- **FR-6.1** A procedure library shall store ordered steps with prerequisites, tool list, torque values, safety/isolation steps, and acceptance criteria, authored as **data (JSON) not code**.
- **FR-6.2** At least **two repair scenarios** shall be authored (e.g., main-bearing inspection-and-replacement; gearbox oil sampling and filter change).
- **FR-6.3** Steps shall be anchored to the relevant component with visual callouts and correct tool shown/required.
- **FR-6.4** The system shall validate step order and required tool, and block or warn on deviation (including a skipped-isolation hard block).
- **FR-6.5** Scenario outcome shall be scored on diagnosis correctness, sequence correctness, safety compliance, and time.
- **FR-6.6** Score and completion shall be exportable as a JSON/CSV report.

### 4.7 Alerts, Dashboard & Reporting
- **FR-7.1** Configurable alert rules on health score, rate of change, and probability.
- **FR-7.2** In-VR alert panel with acknowledge action and redundant audio + visual + controller-haptic notification.
- **FR-7.3** A simple **2D web dashboard** (risk list, health-over-time plot, fault log) reading the same backend APIs, for non-VR viewing and for demo screens.
- **FR-7.4** A post-session summary showing maintenance decision quality (detection → correct diagnosis → correct action).

### 4.8 Platform & Build
- **FR-8.1** The client shall be built in **Unity LTS 6000.x** (native Apple Silicon build) using **URP** with the Metal graphics API for desktop, and OpenXR/Metal for the VR path.
- **FR-8.2** Interaction shall use **XR Interaction Toolkit** for the XR path (teleport, snap turn, direct/UI interaction, physics grabbing of parts and tools).
- **FR-8.3** **Desktop input shall be a first-class, fully supported path** — mouse-look free-fly/walk navigation, click-to-select and drag-to-grab, scroll-to-zoom. All interaction logic (selection, grabbing, step validation, UI panels) shall live in **input-agnostic services** so desktop and XR input drivers are thin adapters over the same code.
- **FR-8.4** The XR path shall be **present but dormant by default**: OpenXR plugin and XR rig included and configured, with a build flag or launch flag that enables it. It shall be exercisable without hardware via the **XR Device Simulator**.
- **FR-8.5** The project shall build and run on **macOS (Apple Silicon)** as the primary target, and shall also build to a **Windows standalone** executable.
- **FR-8.6** Component state shall be data-driven via **ScriptableObject/JSON definitions**, so a new turbine variant is a config change, not new code.
- **FR-8.7** Twin state shall live in a single **central state store**; avatar visuals subscribe to it, decoupling data from scene-graph traversal.
- **FR-8.8** The data layer shall be abstracted behind one interface with an **offline replay implementation** (the pilot path); a live streaming implementation is optional and not required.
- **FR-8.9** Simple role selection at launch (Engineer / Trainee / Analyst) shall gate which UI and actions are available.
- **FR-8.10** Assembly-definition (asmdef) separation per feature module shall be maintained.
- **FR-8.11** The application shall run entirely offline against bundled recorded data, with no network dependency at runtime.

### 4.9 MVP Scope and Build Order
The pilot is delivered in four increments; each is independently demonstrable.

| Phase | Deliverable | Exits when |
|---|---|---|
| **P1 — Twin shell** | Unity project on Apple Silicon, URP/Metal, desktop navigation, turbine assembly from free assets, component picking, XR rig present but dormant | Can navigate a correctly-proportioned turbine on the laptop at target frame rate; XR rig loads under Device Simulator |
| **P2 — Data & health** | Python simulator with 3 labelled fault classes, Parquet recording, health score + probability + contributing features | Offline replay drives the twin; health scores track the injected fault |
| **P3 — Fault visualisation** | Avatar state machine, audio/visual/motion cues, fault injection UI, alert panel | Fault is recognisable visually and by audio alone; alerts fire correctly |
| **P4 — Training** | Two guided repair scenarios, step validation, scoring, export, 2D dashboard, summary report | A first-time user completes a scenario; a scored report is produced |

---

## 5. Non-Functional Requirements

### 5.1 Performance
- **NFR-1.1** *(primary, pilot)* Sustain **≥ 60 FPS** with no visible stutter in the nacelle scene with all fault cues active, on the reference development machine: **Apple M2 (8-core GPU, Metal 4), 8 GB unified memory**, at 1600×900 or 1920×1080.
- **NFR-1.2** *(VR path, deferred)* On a headset, the target is **≥ 72 FPS** at a 90 Hz refresh rate on a discrete mid-tier GPU (RTX 3060 / RX 6700 / 8 GB VRAM class). **This target is aspirational and unvalidated** — no headset hardware is available in the pilot (§7). It is a statement of design intent, not a measured result.
- **NFR-1.3** Frame budget on the reference machine: main thread **< 8 ms**, GPU **< 10 ms** at 60 FPS. Telemetry processing off the main thread; no per-frame allocations in hot paths.
- **NFR-1.4** Scene load to interactive **< 8 s**. Given the small asset count (FR-1.7) Addressables streaming is **optional** and only introduced if profiling on the reference machine shows load is a problem. Memory ceiling: Unity working set **< 4 GB** on an 8 GB unified-memory machine.
- **NFR-1.5** Health/fault inference per component **< 200 ms**; the client must never block on it.
- **NFR-1.6** Single-user session. Multi-user and concurrent-session scaling are **not** a pilot requirement.
- **NFR-1.7** Performance shall be verified by an in-editor profiler capture at every phase exit, recorded in the repo alongside the phase deliverable.

### 5.2 Reliability & Robustness
- **NFR-2.1** The client shall run **fully offline** for all demo and training scenarios.
- **NFR-2.2** If the backend is unavailable, the client shall degrade to cached/last-known state with a visible indicator, and shall not freeze or error the scene.
- **NFR-2.3** The application shall survive an XR session loss (simulated, or real when hardware exists) without requiring a scene reload or losing session state.
- **NFR-2.4** A run shall be fully reproducible from `(config, seed)`: re-running the same configuration regenerates the same telemetry, faults and scores.
- **NFR-2.5** The project shall build and run identically on the reference machine from a clean checkout, using only documented setup steps.

### 5.3 Usability & Comfort
- **NFR-3.1** *(desktop, primary)* Mouse navigation shall be comfortable on a laptop screen for a 30-minute session; pointer acceleration and camera-jerk shall be tuned to avoid discomfort. Hotkeys shall not conflict with macOS shortcuts.
- **NFR-3.2** *(XR path)* Teleport and snap-turn enabled by default; no veering locomotion, no forced camera rotation.
- **NFR-3.3** Critical alerts presented redundantly: **audio + visual** on desktop; **audio + visual + controller haptic** on the XR path.
- **NFR-3.4** UI legible at the target viewing distance on both a laptop panel and a headset; hit targets sized for both mouse and controller-ray interaction.
- **NFR-3.5** A user unfamiliar with the system can complete a guided repair scenario using only in-app instruction.
- **NFR-3.6** Every avatar state shall be distinguishable **without relying on hue alone** (use intensity/saturation/value and form in addition) so the cue survives colour-vision deficiency.

### 5.4 Licensing, Reproducibility & Security
- **NFR-4.1** **Zero paid assets, zero paid plugins, zero paid tools.** Full open-source / free-tier stack only.
- **NFR-4.2** Complete `ASSET_MANIFEST.md` with source URL + licence for every asset, shipped with the build.
- **NFR-4.3** Pinned dependency versions (Unity packages, Python `requirements.txt` with hashes) so the build is reproducible.
- **NFR-4.4** Simulated data only in the pilot; no site or personal data collected. If real data is ever introduced, encryption in transit/at rest and a data-retention policy apply.
- **NFR-4.5** Lightweight action logging (who selected what, what fault was injected, what score resulted) sufficient to audit a demo session. Enterprise RBAC, SSO and IEC 62443 compliance are **out of pilot scope**.

### 5.5 Maintainability & Code Quality
- **NFR-5.1** Adding a new turbine variant, fault class, or repair scenario requires **data/config changes only** — no modification to core client code.
- **NFR-5.2** Input handling shall be isolated behind adapters (`IDesktopInputDriver` / `IXRInputDriver`) with all domain logic input-agnostic, so a desktop-to-VR switch requires no domain code changes.
- **NFR-5.3** Python side as a versioned package with unit tests for the simulator, feature extraction and scoring logic.
- **NFR-5.4** Unity side: EditMode tests for the state store, the severity state machine and step-validation logic; ≥ 60% coverage of core logic modules.
- **NFR-5.5** CI that builds the Unity project, runs both test suites, and produces a **macOS** standalone build (Windows build optional, and expected to require a Windows runner).
- **NFR-5.6** Asset budget validated at build time (triangle counts, texture size, material/shader variant counts) with a failing check on breach.
- **NFR-5.7** All public APIs documented (docstrings in Python, XML docs on public Unity types); README covers setup-to-running in under 20 steps.
- **NFR-5.8** XR-related code shall be behind compile symbols where practical so the desktop build path is unaffected by XR package issues.

---

## 6. Assumptions

1. **Free assets are sufficient.** Freely downloadable FBX/OBJ/glTF models plus Unity primitives and procedural generation can represent a credible wind turbine at pilot fidelity. No bespoke modelling is required beyond simple procedural geometry.
2. **Dimensional fidelity is enough.** Taking proportions and dimensions from a public-domain reference specification (IEA Wind Task 37 / NREL reference turbine) makes scale claims defensible, even though the geometry is not OEM-accurate.
3. **Unity import formats are respected.** All assets will be sourced in FBX/OBJ/glTF/GLB. No paid CAD-to-mesh converter is assumed available.
4. **Licences are compatible.** CC0, CC-BY and free-tier store assets are acceptable for an academic/portfolio project with attribution. If the project is ever commercialised, OEM and store licence terms must be re-reviewed.
5. **Fidelity is deliberately low.** Visual target is a clean, readable, technically credible industrial look — not photoreal. Health state is communicated by colour, emissive intensity and motion, which costs nothing in art budget.
6. **Synthetic data is acceptable and honest.** No partner site data or CMMS records are available or assumed. All telemetry and faults are simulated. Performance figures are labelled as synthetic and do not represent field performance.
7. **Simple classical ML is sufficient and preferable.** Feature engineering + statistical control limits + an unsupervised detector is explainable, trainable on synthetic data, and appropriate for demonstrating feasibility. Deep learning is deferred.
8. **Single pilot machine, single workstation, single user.** One turbine, one developer laptop, one user at a time. Fleet scale, multi-user and concurrent sessions are out of scope.
9. **Development hardware is an Apple Silicon Mac (M2, 8 GB unified memory), with no VR headset available.** SteamVR has no macOS runtime and Meta Quest Link requires Windows, so no HMD can be driven from the reference machine. All VR-specific behaviour is therefore authored to XRI/OpenXR conventions but exercised through Unity's Device Simulator rather than hardware.
10. **VR is a design target, not a validated deliverable.** The pilot ships as a desktop application. Stereo comfort, headset frame rate, motion-to-photon latency and real controller ergonomics are **unmeasured**. Any claim that the system "works in VR" must be qualified as *architecturally prepared and unvalidated on hardware*.
11. **Unity LTS 6000.x with URP on Metal, plus OpenXR and XR Interaction Toolkit** is the client stack; Python (FastAPI + pandas/numpy/sklearn) is the data and model stack.
12. **An 8 GB unified-memory machine is the binding resource constraint.** Unity, the OS and the Python services share the same memory. The asset budget (FR-1.7, FR-1.8) is set by this limit, not by GPU capability.
13. **Advisory, not safety-certified.** The system is a demonstrator and training aid. It does not replace LOTO procedures, OEM manuals, or qualified engineering judgement, and it is not approved for any control function.
14. **Human-in-the-loop.** Every prediction is advisory; a qualified human authorises any action.
15. **Free tooling is sufficient.** Blender (or equivalent) for any asset conversion and cleanup, plus open-source Python libraries, covers the pipeline at no cost.

---

## 7. Limitations

1. **Synthetic-data validity (the central limitation).** The entire pilot runs on simulated telemetry. Simulators encode the physics and failure modes the developer understood; they cannot capture real site-specific behaviour, manufacturing variation, or rare combined faults. Accuracy figures are a demonstration of the pipeline, **not evidence of real-world predictive performance**. Any external claim must carry this caveat.
2. **Free assets cap visual fidelity.** CC0/CC-BY game assets are stylised, often low-detail, sometimes inconsistent in scale and origin. The turbine will look like a credible technical model, not a photoreal OEM machine. Visual polish is limited by what is free and correctly licensed.
3. **Gearbox and drivetrain interiors are rarely free.** Detailed planetary gearbox internals at OEM fidelity are essentially unavailable for free. The gearbox will be a simplified or procedurally generated representation — adequate to demonstrate fault *behaviour*, not to teach real disassembly geometry.
4. **Component-level realism is schematic.** Bearings, generators and actuators are represented by generic geometry. Tag-level sensor mapping is plausible and spec-derived, not vendor-accurate.
5. **No real fault signatures.** Avatars express faults through designed cues (spectral audio loops, emissive shift, abnormal motion) informed by published failure signatures. They approximate the perceptual experience and **cannot substitute for real equipment** or for an expert ear trained on genuine recordings.
6. **No validated predictive accuracy.** Targets are deliberately modest: detection of injected faults in synthetic data with measurable lead time and an acceptable false-alarm rate. There is no 7-day-early-warning claim, no AUC-ROC ≥ 0.9 claim, and no field validation.
7. **No VR hardware validation — a headline limitation.** The pilot is developed and demonstrated entirely on a laptop with no headset. Stereo comfort, motion sickness, real frame rate at 90 Hz, motion-to-photon latency, controller ergonomics and headset UI legibility are **all unmeasured**. The XR code path is written to OpenXR/XRI conventions and exercised via Device Simulator, which validates *logic* but not *ergonomics*. **No claim of a working, comfortable VR experience can be supported by this pilot.** A single session on real headset hardware is required before any VR capability is asserted.
8. **Haptics are absent.** Even with a headset, consumer controllers give button feedback only. Torque, heat and vibration are conveyed visually and aurally. Force-feedback exoskeletons are out of scope.
9. **VR-to-field transfer is unproven.** Immersive training does not guarantee real-world competence and is not certification-grade. It supplements supervised hands-on training.
10. **Single-machine, single-user scope.** One turbine model, one workstation, one user. Fleet-scale dashboards, multi-user collaboration, concurrent sessions and mobile VR are not addressed.
11. **Performance is capped by the reference machine, and the cap is memory rather than graphics.** An M2 with 8 GB unified memory has ample GPU capability for this scene but a tight memory ceiling shared with the OS. The asset budget must stay conservative; exceeding it yields editor stalls and dropped frames rather than graceful degradation. This also means the pilot cannot demonstrate the visual richness the project would target on proper hardware.
12. **Simulation ≠ physics.** The twin models degradation *behaviour* for visualisation and decision support. It is not a certified multiphysics, FEA or fatigue model, and the twin's component states are driven by telemetry simulation, not by a mechanical solver.
13. **Not safety- or certification-grade.** The system cannot serve as the primary safety-training record without formal validation and is not approved for autonomous control or for actuation of any turbine equipment.
14. **Unexplored component scope.** Lightning damage, blade structural fatigue, foundation and offshore monopile assessment, and true multi-component cascading failure are all out of scope.
15. **Licensing is a live obligation, not a one-off.** Free-store licences can change or be revoked. The manifest must be maintained, and every asset re-checked before any public release or academic submission.
15. **Explainability is correlational.** Feature contribution explains what the model reacted to, not true physical causation. Outputs must be presented as advisory correlation.
16. **Out of scope entirely:** live SCADA/OPC-UA site integration, drone inspection integration, ERP integration, remote actuator control, multi-user VR collaboration, standalone-headset support, and any paid/licensed asset or plugin.