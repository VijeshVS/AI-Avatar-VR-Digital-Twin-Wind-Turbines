"""Deterministic degradation trend and remaining-life estimate.

No model is trained here. Health is a pure function of simulated time, so the
trend can be measured by re-scoring the same scenario at earlier ticks and
fitting a straight line through the result. That makes the estimate
reproducible, explainable and free of training data — which is the honest
amount of "prediction" this iteration can support.

The demo compresses asset life into scenario seconds. One second of simulated
time stands for eight hours of machine life, so the roughly 90 s fault ramp
reads as about a month. The constant is declared here so the estimate can be
explained rather than asserted.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from . import health as health_mod
from . import simulation
from .models import DEFAULT_TURBINE_ID, Sample

HOURS_PER_SIM_SECOND = simulation.ASSET_HOURS_PER_SIM_SECOND

# Match health.state_for, so the estimate and the avatar agree on "critical".
CRITICAL_HEALTH = 0.45
WARNING_HEALTH = 0.75

WINDOW_S = 90.0
STEP_S = 10.0
MIN_SAMPLES = 3

BAND_STABLE = "stable"
BAND_UNKNOWN = "unknown"
BAND_CRITICAL = "critical"
BAND_UNDER_8D = "<8 d"
BAND_8_TO_30D = "8-30 d"
BAND_OVER_30D = ">30 d"


@dataclass(frozen=True)
class TrendEstimate:
    """One component's measured trend, extrapolated to the critical threshold."""

    component_id: str
    health: float
    slope_per_hour: float
    hours_to_critical: float | None
    days_to_critical: float | None
    band: str
    confidence: float
    samples: int

    def to_dict(self) -> dict[str, object]:
        return {
            "component_id": self.component_id,
            "health": round(self.health, 4),
            "slope_per_hour": round(self.slope_per_hour, 5),
            "hours_to_critical": None
            if self.hours_to_critical is None
            else round(self.hours_to_critical, 1),
            "days_to_critical": None
            if self.days_to_critical is None
            else round(self.days_to_critical, 1),
            "band": self.band,
            "confidence": round(self.confidence, 3),
            "samples": self.samples,
        }


@dataclass(frozen=True)
class PlantPrognosis:
    """Per-component estimates plus the plant roll-up."""

    t: float
    scenario: str
    plant_health: float
    components: tuple[TrendEstimate, ...]
    turbine_id: str = DEFAULT_TURBINE_ID

    def worst(self) -> TrendEstimate | None:
        return min(self.components, key=lambda c: c.health, default=None)

    def to_dict(self) -> dict[str, object]:
        worst = self.worst()
        return {
            "turbine_id": self.turbine_id,
            "t": round(self.t, 1),
            "scenario": self.scenario,
            "plant_health": round(self.plant_health, 4),
            "worst": None if worst is None else worst.component_id,
            "components": [c.to_dict() for c in self.components],
        }


def _health_at(
    t: float,
    scenario: str,
    turbine_id: str,
    sample_at_t: Callable[[float, str, str], Sample] | None = None,
) -> dict[str, float]:
    """Raw (unsmoothed) health at one instant, without touching service state.

    Only measured values are scored, on the same one-asset-hour grid the engine
    uses, so a prognosis is reproducible after a seek. The prognosis module
    never sees injections or true values directly.
    """
    sample = (
        sample_at_t(t, scenario, turbine_id)
        if sample_at_t is not None
        else simulation.sample_at_tick(
            simulation.tick_index_at(t), scenario, turbine_id=turbine_id
        )
    )
    return {c.id: c.health for c in health_mod.score_sample(sample)}


def _linear_fit(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Least-squares slope and R^2 over ``(t, health)`` samples."""
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    sxx = sum((x - mean_x) ** 2 for x, _ in points)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in points)
    slope = sxy / sxx if sxx > 1e-9 else 0.0
    intercept = mean_y - slope * mean_x

    ss_tot = sum((y - mean_y) ** 2 for _, y in points)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in points)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-9 else 1.0
    return slope, max(0.0, min(1.0, r2))


def _band(days: float | None, health: float) -> str:
    if health <= CRITICAL_HEALTH:
        return BAND_CRITICAL
    if days is None:
        return BAND_STABLE
    if days < 8.0:
        return BAND_UNDER_8D
    if days <= 30.0:
        return BAND_8_TO_30D
    return BAND_OVER_30D


def _estimate_component(component_id: str, samples: list[tuple[float, float]]) -> TrendEstimate:
    health = samples[-1][1]
    slope_per_second, r2 = _linear_fit(samples)

    # Health is a fraction per asset-hour, so a falling score has a negative slope.
    slope_per_hour = slope_per_second / HOURS_PER_SIM_SECOND

    if health <= CRITICAL_HEALTH:
        return TrendEstimate(
            component_id, health, slope_per_hour, 0.0, 0.0, BAND_CRITICAL, 1.0, len(samples)
        )

    if slope_per_hour >= -1e-6:
        return TrendEstimate(
            component_id, health, slope_per_hour, None, None, BAND_STABLE, 1.0, len(samples)
        )

    hours_to_critical = (health - CRITICAL_HEALTH) / -slope_per_hour
    days = hours_to_critical / 24.0
    return TrendEstimate(
        component_id,
        health,
        slope_per_hour,
        hours_to_critical,
        days,
        _band(days, health),
        r2,
        len(samples),
    )


def estimate(
    t: float,
    scenario: str,
    current: dict[str, float] | None = None,
    turbine_id: str = DEFAULT_TURBINE_ID,
    sample_at_t: Callable[[float, str, str], Sample] | None = None,
) -> PlantPrognosis:
    """Measure every component's trend over the window ending at ``t``.

    ``current`` lets the caller pin the newest sample to the health the client is
    actually displaying, which is smoothed. Without it the estimate uses the raw
    score at ``t`` and can disagree with the HUD by a few percent.
    """
    end = max(0.0, t)
    start = max(0.0, end - WINDOW_S)
    ticks = []
    tick = start
    while tick <= end + 1e-9:
        ticks.append(tick)
        tick += STEP_S
    if not ticks or ticks[-1] < end - 1e-9:
        ticks.append(end)

    histories: dict[str, list[tuple[float, float]]] = {}
    for tick in ticks:
        for component_id, health in _health_at(
            tick, scenario, turbine_id, sample_at_t=sample_at_t
        ).items():
            histories.setdefault(component_id, []).append((tick, health))

    components: list[TrendEstimate] = []
    for component_id, samples in histories.items():
        if current and component_id in current:
            samples[-1] = (samples[-1][0], max(0.0, min(1.0, current[component_id])))
        if len(samples) < MIN_SAMPLES:
            # Too early in the run to see a trend. Say so instead of guessing.
            components.append(
                TrendEstimate(
                    component_id,
                    samples[-1][1],
                    0.0,
                    None,
                    None,
                    BAND_UNKNOWN,
                    0.0,
                    len(samples),
                )
            )
            continue
        components.append(_estimate_component(component_id, samples))

    components.sort(key=lambda c: c.health)
    plant = health_mod.plant_health(
        tuple(
            health_mod.ComponentHealth(c.component_id, c.component_id, c.health, "", 0.0, ())
            for c in components
        )
    )
    return PlantPrognosis(
        t=end,
        scenario=scenario,
        plant_health=plant,
        components=tuple(components),
        turbine_id=turbine_id,
    )
