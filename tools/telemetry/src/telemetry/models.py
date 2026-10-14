"""Wire models shared by the telemetry service and the Unity client.

The Unity client parses these payloads with ``JsonUtility``, so every field is a
lowercase primitive (or a list of objects with primitive fields). No dictionaries,
no nullable unions, no enums encoded as strings other than the plain string
fields declared here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1

# Component ids. Unity maps each id onto a transform in the turbine rig.
COMPONENT_IDS = (
    "blade_set",
    "main_bearing",
    "gearbox",
    "generator",
    "pitch_system",
)

COMPONENT_LABELS = {
    "blade_set": "Blade Set",
    "main_bearing": "Main Bearing",
    "gearbox": "Gearbox",
    "generator": "Generator",
    "pitch_system": "Pitch System",
}


@dataclass(frozen=True)
class Signal:
    """A single measured quantity with its engineering envelope."""

    id: str
    value: float
    unit: str


@dataclass(frozen=True)
class Factor:
    """One explainability row: why a component lost health."""

    signal: str
    value: float
    unit: str
    warn: float
    critical: float
    severity: float
    weight: float
    contribution: float


@dataclass(frozen=True)
class ComponentHealth:
    """Health of one turbine component, 0.0 (failed) .. 1.0 (nominal)."""

    id: str
    label: str
    health: float
    state: str
    trend: float
    factors: tuple[Factor, ...]


@dataclass(frozen=True)
class Environment:
    """Plant-level context signals that are not owned by a single component."""

    wind_speed_ms: float
    ambient_temp_c: float
    rotor_rpm: float
    active_power_kw: float
    yaw_deg: float


@dataclass(frozen=True)
class TelemetryFrame:
    """One simulation tick, serialised verbatim to the Unity client."""

    schema_version: int
    tick: int
    elapsed_s: float
    scenario: str
    healthy_asset: bool
    environment: Environment
    signals: tuple[Signal, ...]
    components: tuple[ComponentHealth, ...]

    def signal_map(self) -> dict[str, float]:
        return {s.id: s.value for s in self.signals}

    def component_map(self) -> dict[str, ComponentHealth]:
        return {c.id: c for c in self.components}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tick": self.tick,
            "elapsed_s": round(self.elapsed_s, 3),
            "scenario": self.scenario,
            "healthy_asset": self.healthy_asset,
            "environment": {
                "wind_speed_ms": round(self.environment.wind_speed_ms, 3),
                "ambient_temp_c": round(self.environment.ambient_temp_c, 3),
                "rotor_rpm": round(self.environment.rotor_rpm, 3),
                "active_power_kw": round(self.environment.active_power_kw, 2),
                "yaw_deg": round(self.environment.yaw_deg, 2),
            },
            "signals": [
                {
                    "id": s.id,
                    "value": round(s.value, 4),
                    "unit": s.unit,
                }
                for s in self.signals
            ],
            "components": [
                {
                    "id": c.id,
                    "label": c.label,
                    "health": round(c.health, 4),
                    "state": c.state,
                    "trend": round(c.trend, 5),
                    "factors": [
                        {
                            "signal": f.signal,
                            "value": round(f.value, 4),
                            "unit": f.unit,
                            "warn": f.warn,
                            "critical": f.critical,
                            "severity": round(f.severity, 4),
                            "weight": f.weight,
                            "contribution": round(f.contribution, 5),
                        }
                        for f in c.factors
                    ],
                }
                for c in self.components
            ],
        }


@dataclass(frozen=True)
class Scenario:
    """A named fault programme the simulation can run."""

    id: str
    label: str
    description: str
    healthy_asset: bool
    onset_s: float
    tags: tuple[str, ...] = field(default=())