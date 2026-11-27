"""Data models for fault, weather, and sensor-quality injections."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from ..models import DEFAULT_TURBINE_ID

PROGRESSION_KINDS = ("ramp", "step", "intermittent", "stepwise")
RAMP_CURVES = ("linear", "exponential")
CATEGORIES = ("gradual", "sudden", "weather", "sensor")
CATEGORY_LABELS = {
    "gradual": "Gradual physical faults",
    "sudden": "Sudden events",
    "weather": "Weather conditions",
    "sensor": "Sensor modifiers",
}
EFFECT_OPS = ("add", "mul", "set")


def new_injection_id() -> str:
    """Short unique id matching the ``inj_ab12`` wire convention."""
    return f"inj_{uuid4().hex[:4]}"


@dataclass(frozen=True)
class Progression:
    """Time envelope parameters for an injection."""

    kind: str = "ramp"
    duration_h: float = 240.0
    curve: str = "linear"
    steps: int = 5
    settle_h: float | None = None
    period_h: float | None = None
    duty: float = 0.55

    def __post_init__(self) -> None:
        if self.kind not in PROGRESSION_KINDS:
            raise ValueError(
                f"unknown progression kind '{self.kind}'; expected one of {PROGRESSION_KINDS}"
            )
        if self.duration_h < 0.0:
            raise ValueError("duration_h must be non-negative")
        if self.curve not in RAMP_CURVES:
            raise ValueError(
                f"unknown ramp curve '{self.curve}'; expected one of {RAMP_CURVES}"
            )
        if self.steps < 2:
            raise ValueError("steps must be at least 2")
        if self.settle_h is not None and self.settle_h < 0.0:
            raise ValueError("settle_h must be non-negative")
        if self.period_h is not None and self.period_h <= 0.0:
            raise ValueError("period_h must be positive")
        if not 0.0 < self.duty <= 1.0:
            raise ValueError("duty must be in (0, 1]")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Progression":
        return cls(
            kind=str(data.get("kind", "ramp")),
            duration_h=float(data.get("duration_h", 240.0)),
            curve=str(data.get("curve", "linear")),
            steps=int(data.get("steps", 5)),
            settle_h=None if data.get("settle_h") is None else float(data["settle_h"]),
            period_h=None if data.get("period_h") is None else float(data["period_h"]),
            duty=float(data.get("duty", 0.55)),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "duration_h": round(self.duration_h, 4),
        }
        if self.curve != "linear":
            payload["curve"] = self.curve
        if self.steps != 5:
            payload["steps"] = self.steps
        if self.settle_h is not None:
            payload["settle_h"] = round(self.settle_h, 4)
        if self.period_h is not None:
            payload["period_h"] = round(self.period_h, 4)
        if self.duty != 0.55:
            payload["duty"] = round(self.duty, 4)
        return payload


@dataclass(frozen=True)
class Injection:
    """One active fault, weather, or sensor-quality injection.

    All fields are immutable and deterministic: ``onset_asset_h`` is resolved to
    a concrete asset-hour float at creation time so seeking and replays remain
    repeatable.
    """

    id: str
    turbine_id: str
    type: str
    severity: float
    onset_asset_h: float
    progression: Progression
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id or not isinstance(self.id, str):
            raise ValueError("injection id must be a non-empty string")
        if not 0.0 <= self.severity <= 1.0:
            raise ValueError("severity must be in [0.0, 1.0]")
        if self.onset_asset_h < 0.0:
            raise ValueError("onset_asset_h must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "turbine_id": self.turbine_id,
            "type": self.type,
            "severity": round(float(self.severity), 4),
            "onset_asset_h": round(float(self.onset_asset_h), 4),
            "progression": self.progression.to_dict(),
            "params": dict(self.params),
        }


@dataclass(frozen=True)
class EffectSpec:
    """One declarative signal modification in the scenario catalog."""

    signal: str
    op: str
    magnitude: float
    harmonic: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "signal": self.signal,
            "op": self.op,
            "magnitude": self.magnitude,
        }
        if self.harmonic:
            payload["harmonic"] = self.harmonic
        return payload


@dataclass(frozen=True)
class WeatherInputSpec:
    """An external weather input offset applied before nominal physics."""

    input: str
    op: str
    magnitude: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "op": self.op,
            "magnitude": self.magnitude,
        }


@dataclass(frozen=True)
class CatalogEntry:
    """One scenario entry loaded from ``catalog.yaml``."""

    id: str
    label: str
    category: str
    description: str
    target_component: str | None
    default_progression: Progression
    default_params: dict[str, Any] = field(default_factory=dict)
    effects: tuple[EffectSpec, ...] = ()
    weather_inputs: tuple[WeatherInputSpec, ...] = ()
    sensor_kind: str | None = None
    special: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "category": self.category,
            "description": self.description,
            "target_component": self.target_component,
            "default_progression": self.default_progression.to_dict(),
            "default_params": dict(self.default_params),
            "effects": [effect.to_dict() for effect in self.effects],
            "weather_inputs": [item.to_dict() for item in self.weather_inputs],
            "sensor_kind": self.sensor_kind,
            "special": self.special,
        }
