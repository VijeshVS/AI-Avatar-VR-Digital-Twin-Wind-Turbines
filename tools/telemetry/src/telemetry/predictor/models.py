"""Shared output dataclass for the predictive engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComponentPrognosis:
    """Engine output for one turbine component at one asset-hour tick."""

    turbine_id: str
    component: str
    asset_time_h: float
    health: float
    # State bucket: healthy | warning | critical | failed
    state: str
    # Forecast status: stable | degrading | insufficient_data | event
    status: str
    # (lo, hi) days-to-failure estimate, or None when not degrading
    ttf_days: tuple[float, float] | None
    # Human-readable band: "<8 d", "8-30 d", ">30 d", "critical", "stable", "unknown"
    band: str
    confidence: float | None
    # [{signal, residual, z, text}, ...]
    top_contributors: list[dict[str, Any]] = field(default_factory=list)
    # [{event_id, component, type, severity, asset_time, message, evidence, status}, ...]
    active_events: list[dict[str, Any]] = field(default_factory=list)
    # signal ids that the sensor guard flagged suspect
    sensor_faults: list[str] = field(default_factory=list)

    # -- helpers -----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "turbine_id": self.turbine_id,
            "component": self.component,
            "asset_time_h": round(self.asset_time_h, 2),
            "health": round(self.health, 4),
            "state": self.state,
            "status": self.status,
            "ttf_days": (
                [round(self.ttf_days[0], 1), round(self.ttf_days[1], 1)]
                if self.ttf_days is not None
                else None
            ),
            "band": self.band,
            "confidence": round(self.confidence, 3) if self.confidence is not None else None,
            "top_contributors": self.top_contributors,
            "active_events": self.active_events,
            "sensor_faults": self.sensor_faults,
        }
