#!/usr/bin/env python3
"""Calibrate the baseline model coefficients from 14 nominal asset-days.

Runs the nominal simulator over 336 hourly ticks (14 days × 24 h), fits
closed-form least-squares models per signal, and writes
``src/telemetry/predictor/baseline_T1.json``.

Usage::

    cd tools/telemetry
    uv run python scripts/calibrate_baseline.py
    # or
    .venv/bin/python scripts/calibrate_baseline.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add src to path so we can import without installing.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from telemetry.simulation import sample_at_tick
from telemetry.predictor import baseline as bl

TURBINE_SEED = 1
TURBINE_ID = "T1"
SCENARIO = "nominal"
N_DAYS = 14
N_TICKS = N_DAYS * 24  # one per asset-hour

OUTPUT_PATH = Path(__file__).parent.parent / "src" / "telemetry" / "predictor" / "baseline_T1.json"


def main() -> None:
    print(f"Collecting {N_TICKS} nominal samples (seed={TURBINE_SEED}) …")
    samples = []
    for tick in range(N_TICKS):
        s = sample_at_tick(
            tick,
            scenario=SCENARIO,
            turbine_id=TURBINE_ID,
            turbine_seed=TURBINE_SEED,
            modifiers=[],
        )
        # Keep the raw measured dict: fit_from_samples builds the same derived
        # view (load fraction, 1P ratio, pitch RMS, fault rate) the engine sees.
        samples.append(dict(s.measured))

    print("Fitting coefficients …")
    coeff = bl.fit_from_samples(samples)

    # Round to 6 significant figures for readability.
    for sig, c in coeff.items():
        coeff[sig] = {k: round(float(v), 6) for k, v in c.items()}

    operating_range = {
        signal: [min(s[signal] for s in samples), max(s[signal] for s in samples)]
        for signal in ("ambient_temp_c", "rotor_rpm")
    }
    payload = {"turbine_id": TURBINE_ID, "scenario": SCENARIO,
               "n_ticks": N_TICKS, "operating_range": operating_range, "signals": coeff}

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {OUTPUT_PATH}")
    for sig, c in coeff.items():
        print(f"  {sig}: {c}")


if __name__ == "__main__":
    main()
