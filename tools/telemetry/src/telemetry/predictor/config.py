"""All predictor thresholds and tuning constants in one place.

Change here — not scattered through engine code.
"""
from __future__ import annotations

# ── EWMA / residual ──────────────────────────────────────────────────────────
# Smoothing factor per asset-hour sample.  α=0.1 gives a 9-hour half-life,
# long enough to filter turbulence noise but short enough to track wear.
EWMA_ALPHA: float = 0.1

# Skip residual updates when the turbine is idling (power_ratio < threshold).
MIN_POWER_RATIO: float = 0.05
PITCH_RMS_WINDOW: int = 12
CONVERTER_COUNT_WINDOW: int = 12

# ── Health index (z → [0,1]) ─────────────────────────────────────────────────
# Piecewise-linear breakpoints.  z ≤ Z_OK → 1.0 health; z ≥ Z_FAILED → 0.0.
Z_OK: float = 1.0
Z_WARN: float = 3.0        # → health 0.75
Z_CRITICAL: float = 6.0   # → health 0.45
Z_FAILED: float = 10.0    # → health 0.0

HEALTH_OK: float = 1.0
HEALTH_WARN: float = 0.75
HEALTH_CRITICAL: float = 0.45
HEALTH_FAILED: float = 0.0

# Component health fusion: dominance weight of the worst signal.
DOMINANCE: float = 0.3

# ── Trend / TTF ──────────────────────────────────────────────────────────────
# Short and long trend windows (in asset-hours).
TREND_SHORT_H: int = 48
TREND_LONG_H: int = 168

# Consecutive z > Z_WARN samples required before a prognosis is reported.
PROGNOSIS_GATE_K: int = 12

# TTF critical threshold (health at which we say the component has failed).
TTF_CRITICAL_HEALTH: float = HEALTH_CRITICAL

# ── Step / event detector ────────────────────────────────────────────────────
# How many σ a step must jump to fire.
STEP_K_SIGMA: float = 8.0

# Recent window (samples) and baseline window (samples) for step detection.
STEP_RECENT: int = 3
STEP_BASELINE: int = 12

# Minimum of STEP_RECENT that must exceed the threshold.
STEP_MIN_BREACHES: int = 2

# Hard-fault thresholds.
ROTOR_OVERSPEED_RATIO: float = 1.10        # > 110 % of rated RPM
POWER_LOSS_WIND_MIN_MS: float = 4.0        # cut-in; below this, low power is normal
POWER_LOSS_THRESHOLD_KW: float = 50.0      # near-zero power above cut-in
CONVERTER_FAULT_BURST: float = 0.8         # count threshold for burst

# Settle time before restarting trend after a step (asset-hours).
STEP_SETTLE_H: int = 6

# ── Sensor guard ─────────────────────────────────────────────────────────────
# Variance window for flatline detection (samples).
FLATLINE_WINDOW: int = 12
# Variance below this (relative to signal range) is flagged as stuck.
FLATLINE_VAR_THRESHOLD: float = 1e-6

# ── Residual scale floors ────────────────────────────────────────────────────
# The simulator's clean, band-limited noise makes a 14-day least-squares fit
# look far more precise than a real SCADA channel.  Without a floor a 3 °C
# sustained rise would exceed 15σ and slam a component straight to zero health,
# producing no usable trend or time-to-failure.  These floors make one σ mean
# roughly "a change an operator would notice", which is what the health map and
# event thresholds were designed around.
RESIDUAL_SIGMA_FLOOR: dict[str, float] = {
    "gearbox_temp_c":           2.0,
    "generator_winding_temp_c": 3.0,
    "main_bearing_temp":        2.0,
    "gearbox_vibration_mm_s":   0.25,
    "main_bearing_vibration":   0.20,
    "blade_1p_ratio":           0.06,
    "pitch_error_rms":          0.50,
    "converter_fault_rate":     0.50,
    "power_ratio":              0.05,
}

# The EWMA is smoother than raw residuals, so its floor is lower.  The ratio
# matches what the nominal calibration observes on these channels.
EWMA_SIGMA_FLOOR: dict[str, float] = {
    "gearbox_temp_c":           1.0,
    "generator_winding_temp_c": 1.5,
    "main_bearing_temp":        1.8,
    "gearbox_vibration_mm_s":   0.15,
    "main_bearing_vibration":   0.20,
    "blade_1p_ratio":           0.04,
    "pitch_error_rms":          0.30,
    "converter_fault_rate":     0.35,
    "power_ratio":              0.03,
}

# Physical range limits [min, max] per signal id.
SIGNAL_RANGE: dict[str, tuple[float, float]] = {
    "wind_speed_ms":            (0.0, 50.0),
    "ambient_temp_c":           (-40.0, 60.0),
    "rotor_rpm":                (0.0, 25.0),
    "active_power_kw":          (-100.0, 4500.0),
    "power_ratio":              (-0.1, 1.05),
    "gearbox_temp_c":           (0.0, 200.0),
    "gearbox_temp_rise_c":      (-5.0, 60.0),
    "gearbox_vibration_mm_s":   (0.0, 30.0),
    "nacelle_vibration_mm_s":   (0.0, 30.0),
    "generator_winding_temp_c": (0.0, 200.0),
    "converter_faults":         (0.0, 10.0),
    "pitch_angle_deg":          (-5.0, 90.0),
    "pitch_position_error_deg": (0.0, 30.0),
    "main_bearing_temp":        (0.0, 150.0),
    "main_bearing_vibration":   (0.0, 30.0),
    "rotor_imbalance_index":    (0.0, 2.0),
}

# Maximum plausible change per asset-hour (rate-of-change guard).
SIGNAL_MAX_RATE: dict[str, float] = {
    "gearbox_temp_c":           5.0,
    "generator_winding_temp_c": 8.0,
    "ambient_temp_c":           3.0,
    "main_bearing_temp":        5.0,
    # A healthy drivetrain cannot change vibration this fast in one asset-hour;
    # this is also the rule that catches a bursting noise channel.
    "gearbox_vibration_mm_s":   0.6,
    "main_bearing_vibration":   0.5,
    "nacelle_vibration_mm_s":   0.8,
    "pitch_position_error_deg": 2.0,
    "converter_faults":         2.0,
}
