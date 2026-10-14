"""Export a telemetry frame for the Unity PlayMode tests.

The Unity side parses ``Assets/StreamingAssets/telemetry_sample.json`` with
``JsonUtility`` and asserts it matches the live DTOs, so a change to the Python
payload that the client cannot read fails the Unity test suite.

Usage: ``uv run python -m telemetry.export_sample``
"""

from __future__ import annotations

import json
import pathlib

from . import simulation
from .main import frame_at, state

ROOT = pathlib.Path(__file__).resolve().parents[4]
DEFAULT_OUT = ROOT / "Assets" / "StreamingAssets" / "telemetry_sample.json"

SAMPLE_SCENARIO = "gearbox_degradation"
SAMPLE_TIMES = (0.0, 60.0, 120.0)


def export(path: pathlib.Path = DEFAULT_OUT) -> pathlib.Path:
    state.select(SAMPLE_SCENARIO)
    frames = []
    for t in SAMPLE_TIMES:
        state.select(SAMPLE_SCENARIO)
        frame = frame_at(t, SAMPLE_SCENARIO)
        frames.append(frame.to_dict())
        state.select(SAMPLE_SCENARIO)  # avoid carrying trend between samples

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"frames": frames}, indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    written = export()
    print(f"wrote {written} ({len(SAMPLE_TIMES)} frames, scenario={SAMPLE_SCENARIO})")
    print(f"scenarios available: {', '.join(simulation.SCENARIOS)}")