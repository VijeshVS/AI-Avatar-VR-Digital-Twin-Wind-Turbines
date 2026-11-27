"""z-score → 0-1 signal health, then component fusion.

The map is piecewise-linear:

  z  ≤ 1  → 1.00
  z = 3   → 0.75   (warning edge)
  z = 6   → 0.45   (critical edge)
  z ≥ 10  → 0.00

Component fusion: health = 0.7·weighted_mean + 0.3·min(signal_health)

This dominance term ensures one very sick signal drags the whole component
even when other signals look fine.
"""
from __future__ import annotations

from .config import (
    DOMINANCE,
    HEALTH_CRITICAL,
    HEALTH_FAILED,
    HEALTH_OK,
    HEALTH_WARN,
    Z_CRITICAL,
    Z_FAILED,
    Z_OK,
    Z_WARN,
)

# --- signal health -----------------------------------------------------------

def z_to_health(z: float) -> float:
    """Piecewise-linear z → health in [0, 1]."""
    if z <= Z_OK:
        return HEALTH_OK
    if z <= Z_WARN:
        t = (z - Z_OK) / (Z_WARN - Z_OK)
        return HEALTH_OK + t * (HEALTH_WARN - HEALTH_OK)
    if z <= Z_CRITICAL:
        t = (z - Z_WARN) / (Z_CRITICAL - Z_WARN)
        return HEALTH_WARN + t * (HEALTH_CRITICAL - HEALTH_WARN)
    if z <= Z_FAILED:
        t = (z - Z_CRITICAL) / (Z_FAILED - Z_CRITICAL)
        return HEALTH_CRITICAL + t * (HEALTH_FAILED - HEALTH_CRITICAL)
    return HEALTH_FAILED


# --- component weights -------------------------------------------------------
# Relative importance of each modelled signal per component.
# Signals that belong to multiple components can be listed in both.
COMPONENT_SIGNAL_WEIGHTS: dict[str, dict[str, float]] = {
    "gearbox": {
        "gearbox_temp_c":           1.0,
        "gearbox_vibration_mm_s":   1.0,
    },
    "generator": {
        "generator_winding_temp_c": 1.0,
        "converter_fault_rate":     0.8,
        # A derated or tripped generator shows up as lost power relative to
        # what the wind allows, even before a temperature rises.
        "power_ratio":              0.6,
    },
    "main_bearing": {
        "main_bearing_temp":        0.9,
        "main_bearing_vibration":   1.0,
    },
    "pitch_system": {
        "pitch_error_rms":          1.0,
    },
    "blade_set": {
        "blade_1p_ratio":           1.0,
    },
}


def fuse(signal_healths: dict[str, float], component_id: str) -> float:
    """Compute component health from a dict of {signal_id: health_score}.

    Uses weighted mean + dominance of the minimum.
    Returns 1.0 (healthy) when no signals are known for the component.
    """
    weights = COMPONENT_SIGNAL_WEIGHTS.get(component_id, {})
    if not weights:
        return HEALTH_OK

    total_w = 0.0
    weighted_sum = 0.0
    min_h = HEALTH_OK

    for sig, w in weights.items():
        if sig not in signal_healths:
            continue
        h = signal_healths[sig]
        weighted_sum += h * w
        total_w += w
        min_h = min(min_h, h)

    if total_w == 0.0:
        return HEALTH_OK

    mean_h = weighted_sum / total_w
    return max(HEALTH_FAILED, min(HEALTH_OK, (1.0 - DOMINANCE) * mean_h + DOMINANCE * min_h))


def state_for(health: float) -> str:
    """Map a health score to a state label."""
    if health >= HEALTH_WARN:
        return "healthy"
    if health >= HEALTH_CRITICAL:
        return "warning"
    if health > HEALTH_FAILED:
        return "critical"
    return "failed"
