"""Baseline expected-healthy models + frozen coefficients.

Each model is a closed-form linear combination fitted once from 14 asset-days
of nominal-scenario samples (seed=1, turbine T1).  Coefficients are stored in
``baseline_T1.json`` alongside this file and loaded at import time.

Models
------
gearbox_temp_c           ≈ a0 + a1·ambient + a2·load_fraction
gearbox_vibration_mm_s   ≈ b0 + b1·rpm
generator_winding_temp_c ≈ c0 + c1·ambient + c2·load_fraction
main_bearing_temp        ≈ d0 + d1·ambient + d2·load_fraction
main_bearing_vibration   ≈ e0 + e1·rpm
blade_1p_ratio           = nacelle_1P_amplitude / rpm²  (dimensionless ratio)
pitch_error_rms          windowed RMS; baseline ≈ 0 (near-zero)
converter_fault_rate     count per window; baseline ≈ 0
power_ratio              actual / expected power; nominal = 1.0

Why ``load_fraction`` rather than the wire's ``power_ratio``?  In the nominal
simulator ``power_ratio`` is identically 1.0 (actual power equals expected
power), so a least-squares fit on it is singular and produces enormous,
meaningless coefficients.  ``load_fraction = rotor_rpm / rated_rpm`` is the
same physical driver — heat and vibration rise with load — and it actually
varies in healthy operation.  ``power_ratio`` is kept as its own model (the
nominal value is 1.0) and is still used to gate residual updates while idling.

The residual standard deviation σ per signal is used to normalise z-scores.
When a baseline file is absent (first run), the script
``tools/telemetry/scripts/calibrate_baseline.py`` generates it.
"""
from __future__ import annotations

import json
import math
from collections import deque
from pathlib import Path
from typing import Any

from .config import (
    CONVERTER_COUNT_WINDOW,
    EWMA_ALPHA,
    EWMA_SIGMA_FLOOR,
    PITCH_RMS_WINDOW,
    RESIDUAL_SIGMA_FLOOR,
)

RATED_RPM = 12.6
# Below this fraction of rated speed the turbine is idling; the 1P ratio is
# numerically unstable there, so the denominator is floored.
BLADE_MIN_RPM = RATED_RPM * 0.25
NOMINAL_POWER_RATIO = 1.0

# ---------------------------------------------------------------------------
# Hard-coded defaults so the engine never crashes without the JSON file.
# These are overwritten when the file is loaded.
# ---------------------------------------------------------------------------
_DEFAULTS: dict[str, dict[str, Any]] = {
    "gearbox_temp_c": {
        "intercept": 6.0, "ambient": 1.0, "load": 18.0, "sigma": 0.5
    },
    "gearbox_vibration_mm_s": {
        "intercept": 0.1, "rpm": 0.105, "sigma": 0.12
    },
    "generator_winding_temp_c": {
        "intercept": 61.0, "ambient": 0.0, "load": 34.0, "sigma": 0.7
    },
    "main_bearing_temp": {
        "intercept": 12.0, "ambient": 1.0, "load": 9.0, "sigma": 0.4
    },
    "main_bearing_vibration": {
        "intercept": 0.15, "rpm": 0.075, "sigma": 0.1
    },
    "blade_1p_ratio": {
        "intercept": 0.0, "inverse_rpm": 0.0, "inverse_rpm2": 0.0, "sigma": 0.01
    },
    "pitch_error_rms": {
        "intercept": 0.25, "sigma": 0.08
    },
    "converter_fault_rate": {
        "intercept": 0.0, "sigma": 0.01
    },
    "power_ratio": {
        "intercept": 1.0, "sigma": 0.002
    },
}

_BASELINE_PATH = Path(__file__).parent / "baseline_T1.json"
_coeff: dict[str, dict[str, Any]] = {}
_operating_range: dict[str, list[float]] = {}


def _load() -> None:
    """Load coefficients from the JSON file, falling back to defaults."""
    global _coeff, _operating_range
    if _BASELINE_PATH.exists():
        with _BASELINE_PATH.open() as f:
            data = json.load(f)
        _coeff = data.get("signals", data)
        _operating_range = data.get("operating_range", {})
    else:
        _coeff = {k: dict(v) for k, v in _DEFAULTS.items()}
        _operating_range = {}
    # A baseline written by an older calibrator may be missing newer models.
    for sig, defaults in _DEFAULTS.items():
        _coeff.setdefault(sig, dict(defaults))


_load()


def reload() -> None:
    """Force re-read of the JSON (useful after calibrate_baseline writes it)."""
    _load()


# ---------------------------------------------------------------------------
# Predictor view: derive the signals the SCADA wire does not carry directly.
# ---------------------------------------------------------------------------

def load_fraction(measured: dict[str, float]) -> float:
    rpm = float(measured.get("rotor_rpm", 0.0))
    return max(0.0, min(1.0, rpm / RATED_RPM))


def blade_1p_ratio(measured: dict[str, float]) -> float:
    """1P rotor signature normalised by speed squared.

    A real SCADA feed would expose a 1P amplitude; when this simulator does not,
    the measured rotor imbalance index is already a load-independent normalised
    quantity and is the honest fallback.  A broadband nacelle-vibration ratio is
    a last resort and is deliberately *not* used here, because bearing wear also
    raises nacelle vibration and would masquerade as a blade fault.
    """
    amplitude = measured.get("nacelle_1p_amplitude_mm_s")
    if amplitude is not None:
        rpm = max(BLADE_MIN_RPM, float(measured.get("rotor_rpm", 0.0)))
        return float(amplitude) / (rpm * rpm)
    return abs(float(measured.get("rotor_imbalance_index", 0.0)))


def build_view(measured: dict[str, float]) -> dict[str, float]:
    """Return the predictor's own signal view.

    Only values a real SCADA feed would supply are read.  The derived fields
    are pure functions of those measurements — no injection metadata, no truth.
    """
    view = dict(measured)
    view["load_fraction"] = load_fraction(measured)
    view["blade_1p_ratio"] = blade_1p_ratio(measured)
    view["pitch_error_rms"] = abs(float(measured.get("pitch_position_error_deg", 0.0)))
    view["converter_fault_rate"] = float(measured.get("converter_faults", 0.0))
    return view


class WindowedSignals:
    """Derive pitch RMS and converter count from consecutive measured samples."""

    def __init__(self) -> None:
        self.pitch = deque(maxlen=PITCH_RMS_WINDOW)
        self.converter = deque(maxlen=CONVERTER_COUNT_WINDOW)

    def reset(self) -> None:
        self.pitch.clear()
        self.converter.clear()

    def update(self, view: dict[str, float], blocked: set[str] | None = None) -> None:
        blocked = blocked or set()
        if "pitch_error_rms" in blocked:
            self.pitch.clear()
        else:
            self.pitch.append(view["pitch_error_rms"])
            view["pitch_error_rms"] = math.sqrt(sum(x * x for x in self.pitch) / len(self.pitch))
        if "converter_fault_rate" in blocked:
            self.converter.clear()
        else:
            self.converter.append(view["converter_fault_rate"])
            view["converter_fault_rate"] = sum(self.converter)


def expected(signal_id: str, view: dict[str, float]) -> float | None:
    """Compute the expected value of ``signal_id`` from other measured fields.

    Returns ``None`` when the signal is not modelled (the caller skips it).
    ``view`` is normally the output of :func:`build_view`.
    """
    c = _coeff.get(signal_id)
    if c is None:
        return None

    ambient = float(view.get("ambient_temp_c", 10.0))
    load = float(view.get("load_fraction", 0.5))
    rpm = float(view.get("rotor_rpm", RATED_RPM * 0.5))
    inverse_rpm = 1.0 / max(BLADE_MIN_RPM, rpm)
    inverse_rpm2 = inverse_rpm * inverse_rpm

    if signal_id in ("gearbox_temp_c", "generator_winding_temp_c", "main_bearing_temp"):
        return (
            c["intercept"]
            + c.get("ambient", 0.0) * ambient
            + c.get("load", 0.0) * load
        )
    if signal_id in ("gearbox_vibration_mm_s", "main_bearing_vibration"):
        return c["intercept"] + c.get("rpm", 0.0) * rpm
    if signal_id == "blade_1p_ratio":
        return (
            c["intercept"]
            + c.get("inverse_rpm", 0.0) * inverse_rpm
            + c.get("inverse_rpm2", 0.0) * inverse_rpm2
        )
    if signal_id in ("pitch_error_rms", "converter_fault_rate", "power_ratio"):
        return c["intercept"]
    return None


def sigma(signal_id: str) -> float:
    """Return the fitted residual standard deviation for ``signal_id``."""
    c = _coeff.get(signal_id)
    fitted = 1.0 if c is None else float(c.get("sigma", 1.0))
    return max(1e-4, fitted, RESIDUAL_SIGMA_FLOOR.get(signal_id, 0.0))


def ewma_sigma(signal_id: str) -> float:
    """Standard deviation of the EWMA itself, calibrated on nominal data.

    The textbook white-noise result ``σ·√(α/(2−α))`` assumes independent
    samples.  Real SCADA noise — and this simulator's band-limited noise — is
    strongly autocorrelated, so the EWMA wanders much further than that formula
    predicts.  Calibration stores the observed nominal EWMA standard deviation
    in ``ewma_sigma``; the formula remains the fallback for older baselines.
    """
    c = _coeff.get(signal_id)
    if c is not None and "ewma_sigma" in c:
        fitted = float(c["ewma_sigma"])
    else:
        fitted = sigma(signal_id) * math.sqrt(EWMA_ALPHA / (2.0 - EWMA_ALPHA))
    return max(1e-6, fitted, EWMA_SIGMA_FLOOR.get(signal_id, 0.0))


def modelled_signals() -> list[str]:
    """Signal ids that have a baseline model."""
    return list(_coeff.keys())


def within_operating_range(signal_id: str, view: dict[str, float]) -> bool:
    """Do not extrapolate a fitted model beyond its measured input range."""
    thermal = {"gearbox_temp_c", "generator_winding_temp_c", "main_bearing_temp"}
    speed_dependent = thermal | {"gearbox_vibration_mm_s", "main_bearing_vibration", "blade_1p_ratio"}
    features = []
    if signal_id in thermal:
        features.append("ambient_temp_c")
    if signal_id in speed_dependent:
        features.append("rotor_rpm")
    for feature in features:
        limits = _operating_range.get(feature)
        if limits and (feature not in view or not limits[0] <= view[feature] <= limits[1]):
            return False
    return True


def coefficients() -> dict[str, dict[str, Any]]:
    """Return a copy of the loaded coefficient dictionary (for diagnostics)."""
    return {k: dict(v) for k, v in _coeff.items()}


# ---------------------------------------------------------------------------
# Least-squares fit helpers used by calibrate_baseline.py
# ---------------------------------------------------------------------------

def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(vector)
    a = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[pivot] = a[pivot], a[col]
        p = a[col][col]
        if abs(p) < 1e-12:
            continue
        for row in range(col + 1, n):
            factor = a[row][col] / p
            for j in range(col, n + 1):
                a[row][j] -= factor * a[col][j]
    solution = [0.0] * n
    for row in range(n - 1, -1, -1):
        solution[row] = a[row][n]
        for col in range(row + 1, n):
            solution[row] -= a[row][col] * solution[col]
        p = a[row][row]
        solution[row] = solution[row] / p if abs(p) > 1e-12 else 0.0
    return solution


def _lstsq(features: list[list[float]], ys: list[float]) -> list[float]:
    """Fit y = b0 + b1·f1 + … + bk·fk.  Returns coefficients in feature order."""
    if not ys:
        return [0.0] * (len(features[0]) + 1 if features else 1)
    columns = [[1.0] * len(ys)] + features
    k = len(columns)
    normal = [[0.0] * k for _ in range(k)]
    rhs = [0.0] * k
    for row, y in enumerate(ys):
        values = [col[row] for col in columns]
        for i in range(k):
            rhs[i] += values[i] * y
            for j in range(k):
                normal[i][j] += values[i] * values[j]
    return _solve(normal, rhs)


def _sigma(residuals: list[float]) -> float:
    n = len(residuals)
    if n < 2:
        return 1e-4
    mean = sum(residuals) / n
    var = sum((r - mean) ** 2 for r in residuals) / (n - 1)
    return max(1e-4, math.sqrt(var))


def fit_from_samples(samples: list[dict]) -> dict[str, dict]:
    """Fit baseline coefficients from a list of measured-signal dicts.

    ``samples`` is a list of ``sample.measured`` dicts from the nominal
    simulator.  Derived signals are built here so calibration uses exactly the
    same view the online engine sees.
    """
    windows = WindowedSignals()
    views = []
    for sample in samples:
        view = build_view(sample)
        windows.update(view)
        views.append(view)

    result: dict[str, dict] = {}

    def _fit_named(signal_id: str, features: list[list[float]], names: list[str]) -> None:
        ys = [float(view.get(signal_id, 0.0)) for view in views]
        coeff = _lstsq(features, ys)
        predictions = [
            coeff[0]
            + sum(coeff[i + 1] * features[i][row] for i in range(len(features)))
            for row in range(len(ys))
        ]
        entry = {"intercept": coeff[0]}
        entry.update({name: coeff[i + 1] for i, name in enumerate(names)})
        residuals = [y - p for y, p in zip(ys, predictions)]
        entry["sigma"] = _sigma(residuals)

        # Calibrate the EWMA's own spread on the nominal residual series.  This
        # is the quantity the online z-score divides by.
        ewma = 0.0
        initialised = False
        ewma_values: list[float] = []
        for residual in residuals:
            if not initialised:
                ewma = residual
                initialised = True
            else:
                ewma = EWMA_ALPHA * residual + (1.0 - EWMA_ALPHA) * ewma
            ewma_values.append(ewma)
        entry["ewma_sigma"] = max(1e-6, _sigma(ewma_values[1:]))
        result[signal_id] = entry

    ambient = [float(v.get("ambient_temp_c", 10.0)) for v in views]
    load = [float(v["load_fraction"]) for v in views]
    rpm = [float(v.get("rotor_rpm", 0.0)) for v in views]
    inverse_rpm = [1.0 / max(BLADE_MIN_RPM, r) for r in rpm]
    inverse_rpm2 = [x * x for x in inverse_rpm]

    for signal_id in (
        "gearbox_temp_c",
        "generator_winding_temp_c",
        "main_bearing_temp",
    ):
        _fit_named(signal_id, [ambient, load], ["ambient", "load"])

    for signal_id in ("gearbox_vibration_mm_s", "main_bearing_vibration"):
        _fit_named(signal_id, [rpm], ["rpm"])

    _fit_named(
        "blade_1p_ratio",
        [inverse_rpm, inverse_rpm2],
        ["inverse_rpm", "inverse_rpm2"],
    )

    # Signals with a near-zero baseline: fit only the mean.
    _fit_named("pitch_error_rms", [], [])
    _fit_named("converter_fault_rate", [], [])
    _fit_named("power_ratio", [], [])

    return result
