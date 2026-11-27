"""Wire models shared by the telemetry service and the Unity client.

The Unity client parses these payloads with ``JsonUtility``, so every field is a
lowercase primitive (or a list of objects with primitive fields). No dictionaries,
no nullable unions, no enums encoded as strings other than the plain string
fields declared here.

Two ideas live here and drive the whole simulator:

* a :class:`Sample` is the engine's output. It keeps the *true* state of the
  machine apart from what the sensors *measured*. Physical faults change the
  true state; sensor-quality problems only corrupt the measurement.
* every sample is stamped with ``turbine_id`` and ``asset_time_h`` so a fleet
  can key its caches and a client can scrub to an exact hour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1

# Until Phase 4 there is one turbine, but every layer already carries the id so
# the fleet work is a data change rather than a schema migration.
DEFAULT_TURBINE_ID = "T1"

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
    """A single measured quantity with its engineering envelope.

    Kept for the existing health and simulation helpers. New engine code works
    with :class:`SampleSignal`, which carries both the true and measured value.
    """

    id: str
    value: float
    unit: str


@dataclass(frozen=True)
class SampleSignal:
    """One signal at one engine tick, with truth and measurement separated."""

    id: str
    unit: str
    true_value: float
    measured_value: float

    @property
    def value(self) -> float:
        """The measured value, for clients that only know the old shape."""
        return self.measured_value

    @property
    def true(self) -> float:
        return self.true_value

    @property
    def measured(self) -> float:
        return self.measured_value

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "unit": self.unit,
            # ``value`` is what a real SCADA feed reports; the predictor reads it.
            "value": round(self.measured_value, 4),
            # The pair below is the Phase 0 contract: truth vs. measurement.
            "true": round(self.true_value, 4),
            "measured": round(self.measured_value, 4),
        }


@dataclass(frozen=True)
class Sample:
    """The engine's output for one turbine at one asset-hour tick.

    ``true`` and ``measured`` are keyed by signal id and intentionally plain
    dictionaries: modifiers copy-and-update them, and the predictor only ever
    receives ``measured``.
    """

    turbine_id: str
    tick: int
    asset_time_h: float
    elapsed_s: float
    scenario: str
    true: dict[str, float]
    measured: dict[str, float]
    units: dict[str, str]
    meta: dict[str, float] = field(default_factory=dict)

    def signal(self, signal_id: str, measured: bool = True) -> float:
        values = self.measured if measured else self.true
        return values.get(signal_id, 0.0)

    def signal_map(self, measured: bool = True) -> dict[str, float]:
        return dict(self.measured if measured else self.true)

    @property
    def signals(self) -> tuple[SampleSignal, ...]:
        return tuple(
            SampleSignal(
                id=signal_id,
                unit=self.units.get(signal_id, ""),
                true_value=true_value,
                measured_value=self.measured.get(signal_id, true_value),
            )
            for signal_id, true_value in self.true.items()
        )

    def with_true(self, updates: dict[str, float]) -> "Sample":
        """Return a copy with true values changed, measurement refreshed.

        Physical modifiers use this: if the machine itself changed, a healthy
        sensor reports the new truth.
        """
        true = {**self.true, **updates}
        return Sample(
            turbine_id=self.turbine_id,
            tick=self.tick,
            asset_time_h=self.asset_time_h,
            elapsed_s=self.elapsed_s,
            scenario=self.scenario,
            true=true,
            measured=dict(true),
            units=self.units,
            meta=dict(self.meta),
        )

    def with_measured(self, updates: dict[str, float]) -> "Sample":
        """Return a copy with only the reported values changed."""
        return Sample(
            turbine_id=self.turbine_id,
            tick=self.tick,
            asset_time_h=self.asset_time_h,
            elapsed_s=self.elapsed_s,
            scenario=self.scenario,
            true=dict(self.true),
            measured={**self.measured, **updates},
            units=self.units,
            meta=dict(self.meta),
        )

    def with_meta(self, updates: dict[str, float]) -> "Sample":
        return Sample(
            turbine_id=self.turbine_id,
            tick=self.tick,
            asset_time_h=self.asset_time_h,
            elapsed_s=self.elapsed_s,
            scenario=self.scenario,
            true=dict(self.true),
            measured=dict(self.measured),
            units=self.units,
            meta={**self.meta, **updates},
        )


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
    turbine_id: str
    tick: int
    asset_time_h: float
    elapsed_s: float
    scenario: str
    healthy_asset: bool
    environment: Environment
    signals: tuple[SampleSignal, ...]
    components: tuple[ComponentHealth, ...]

    def signal_map(self) -> dict[str, float]:
        return {s.id: s.measured_value for s in self.signals}

    def true_map(self) -> dict[str, float]:
        return {s.id: s.true_value for s in self.signals}

    def component_map(self) -> dict[str, ComponentHealth]:
        return {c.id: c for c in self.components}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "turbine_id": self.turbine_id,
            "tick": self.tick,
            "asset_time_h": round(self.asset_time_h, 4),
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
            "signals": [s.to_dict() for s in self.signals],
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
