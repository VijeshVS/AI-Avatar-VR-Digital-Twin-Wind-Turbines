"""Explainable, rule-based health scoring.

Each component owns a small set of weighted signals. A signal's severity is the
normalised distance between its warning and critical envelope; component health
is a weighted blend that is dominated by the worst offender. Every score ships
with the factor rows that produced it, which is what the Unity avatar turns into
perceptual cues and what the HUD prints as a reason string.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import COMPONENT_LABELS, ComponentHealth, Factor, Sample

WEIGHT_CRITICAL_ONLY = 0.35  # relative weight kept for healthy contributors


@dataclass(frozen=True)
class Rule:
    """Health envelope for one signal."""

    signal: str
    unit: str
    warn: float
    critical: float
    weight: float
    higher_is_worse: bool = True

    def severity(self, value: float) -> float:
        if self.higher_is_worse:
            span = self.critical - self.warn
            raw = 0.0 if span == 0 else (value - self.warn) / span
        else:
            span = self.warn - self.critical
            raw = 0.0 if span == 0 else (self.warn - value) / span
        return max(0.0, min(1.0, raw))


# Signal envelopes are deliberately coarse: they read as "warning band" and
# "interlock/inspection band" for a 3.6 MW class machine.
COMPONENT_RULES: dict[str, tuple[Rule, ...]] = {
    "blade_set": (
        Rule("nacelle_vibration_mm_s", "mm/s", 2.6, 6.0, 1.0),
        Rule("rotor_imbalance_index", "0-1", 0.20, 0.80, 0.7),
    ),
    "main_bearing": (
        Rule("nacelle_vibration_mm_s", "mm/s", 2.2, 5.2, 1.0),
        Rule("gearbox_temp_rise_c", "degC", 6.0, 15.0, 0.45),
        Rule("wind_speed_ms", "m/s", 18.0, 24.0, 0.25),
        # Dedicated main-bearing channels. The built-in scenarios do not raise
        # them yet; Phase 1's bearing-wear injection does.
        Rule("main_bearing_temp", "degC", 70.0, 95.0, 0.8),
        Rule("main_bearing_vibration", "mm/s", 2.2, 5.2, 0.9),
    ),
    "gearbox": (
        Rule("gearbox_vibration_mm_s", "mm/s", 3.2, 7.5, 1.0),
        Rule("gearbox_temp_rise_c", "degC", 6.0, 15.0, 0.85),
        Rule("nacelle_vibration_mm_s", "mm/s", 2.8, 6.0, 0.4),
    ),
    "generator": (
        Rule("generator_winding_temp_c", "degC", 105.0, 140.0, 1.0),
        Rule("converter_faults", "count", 0.25, 1.0, 0.8),
        # Power is judged against what the current wind can produce, so the
        # envelope is inverted: warn below ~55 %, critical below ~25 %.
        Rule("power_ratio", "0-1", 0.55, 0.25, 0.55, higher_is_worse=False),
    ),
    "pitch_system": (
        Rule("pitch_position_error_deg", "deg", 1.2, 5.0, 1.0),
        Rule("pitch_angle_deg", "deg", 2.5, 9.0, 0.6),
        Rule("nacelle_vibration_mm_s", "mm/s", 2.6, 5.6, 0.3),
    ),
}

STATE_HEALTHY = "healthy"
STATE_WARNING = "warning"
STATE_CRITICAL = "critical"


def state_for(health: float) -> str:
    if health >= 0.75:
        return STATE_HEALTHY
    if health >= 0.45:
        return STATE_WARNING
    return STATE_CRITICAL


def score_component(
    component_id: str, signal_values: dict[str, float], previous_health: float | None = None
) -> ComponentHealth:
    rules = COMPONENT_RULES.get(component_id)
    if not rules:
        return ComponentHealth(component_id, COMPONENT_LABELS.get(component_id, component_id), 1.0, STATE_HEALTHY, 0.0, ())

    factors: list[Factor] = []
    weighted_sum = 0.0
    weight_total = 0.0
    worst_severity = 0.0

    for rule in rules:
        if rule.weight <= 0.0:
            continue
        value = signal_values.get(rule.signal, 0.0)
        severity = rule.severity(value)
        weighted_sum += severity * rule.weight
        weight_total += rule.weight
        worst_severity = max(worst_severity, severity)
        factors.append(
            Factor(
                signal=rule.signal,
                value=value,
                unit=rule.unit,
                warn=rule.warn,
                critical=rule.critical,
                severity=severity,
                weight=rule.weight,
                contribution=severity * rule.weight,
            )
        )

    mean_severity = weighted_sum / weight_total if weight_total else 0.0
    # Blend: the worst signal dominates, but several mild signals still add up.
    severity = max(0.85 * worst_severity + 0.15 * mean_severity, mean_severity)
    health = max(0.0, min(1.0, 1.0 - severity))

    factors.sort(key=lambda f: f.contribution, reverse=True)
    total_contribution = sum(f.contribution for f in factors) or 1.0
    factors = [
        Factor(
            signal=f.signal,
            value=f.value,
            unit=f.unit,
            warn=f.warn,
            critical=f.critical,
            severity=f.severity,
            weight=f.weight,
            contribution=f.contribution / total_contribution,
        )
        for f in factors
    ]

    trend = 0.0 if previous_health is None else (previous_health - health) / max(1e-3, 1.0)
    return ComponentHealth(
        id=component_id,
        label=COMPONENT_LABELS.get(component_id, component_id),
        health=health,
        state=state_for(health),
        trend=trend,
        factors=tuple(factors[:3]),
    )


def score_all(
    signal_values: dict[str, float], previous: dict[str, float] | None = None
) -> tuple[ComponentHealth, ...]:
    previous = previous or {}
    return tuple(
        score_component(cid, signal_values, previous.get(cid)) for cid in COMPONENT_RULES
    )


def plant_health(components: tuple[ComponentHealth, ...]) -> float:
    """Worst-component health, so a single failure drags the plant down."""
    if not components:
        return 1.0
    return min(c.health for c in components)


def maintenance_recommendation(component: ComponentHealth | None) -> str:
    """One-line next action for a component, shared by the API and the copilot."""
    if component is None or component.state == STATE_HEALTHY:
        return "continue routine monitoring"
    if component.state == STATE_WARNING:
        return f"schedule inspection of {component.label.lower()} within 14 days"
    return f"plan corrective maintenance on {component.label.lower()} at the next convenient window"


def dominant_reason(component: ComponentHealth) -> str:
    if not component.factors:
        return "no measurable deviation"
    top = component.factors[0]
    if top.severity <= 0.0:
        return "all signals within envelope"
    return (
        f"{top.signal} {top.value:.2f} {top.unit} "
        f"(warn {top.warn:.2f}, critical {top.critical:.2f})"
    )


def score_sample(
    sample: Sample, previous: dict[str, float] | None = None
) -> tuple[ComponentHealth, ...]:
    """Score a sample from *measured* values only.

    The predictor never sees ``sample.true``: a stuck sensor must not be able to
    make the health engine believe the machine failed.
    """
    return score_all(sample.measured, previous)


@dataclass
class HealthModel:
    """Instance-scoped scorer.

    Holds the previous scores used for trend reporting, so two turbines never
    share smoothing state. Module-level functions remain available for the
    existing tests and one-off scoring.
    """

    rules: dict[str, tuple[Rule, ...]] = field(
        default_factory=lambda: dict(COMPONENT_RULES)
    )
    previous: dict[str, float] = field(default_factory=dict)

    def score(self, signal_values: dict[str, float]) -> tuple[ComponentHealth, ...]:
        components = tuple(
            score_component(component_id, signal_values, self.previous.get(component_id))
            for component_id in self.rules
        )
        self.previous = {component.id: component.health for component in components}
        return components

    def score_sample(self, sample: Sample) -> tuple[ComponentHealth, ...]:
        return self.score(sample.measured)

    def reset(self) -> None:
        self.previous.clear()