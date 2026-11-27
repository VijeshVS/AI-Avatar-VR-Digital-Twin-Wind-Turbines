"""Phase-2 predictive engine: residual-based health, Theil-Sen TTF, event alerts.

The predictor reads only *measured* sensor values — the same view that a real
SCADA feed would supply.  It never imports the injection layer or reads ``true``
values, so the Phase-1 isolation contract is enforced at the import level.

Modules
-------
config       — all thresholds and tuning constants in one place
baseline     — expected-healthy models and frozen coefficients
residuals    — residual computation, EWMA, z-score
health       — z → 0-1 signal health, component fusion
trend        — Theil-Sen TTF forecast with confidence and gating
events       — step detector and hard-fault rules
sensor_guard — stuck / dropout / range / rate-of-change checks
engine       — PredictorEngine.update(sample) → dict[str, ComponentPrognosis]
registry     — one engine per turbine, replay-on-seek, caching
"""
from .engine import PredictorEngine
from .models import ComponentPrognosis
from .registry import PredictorRegistry

__all__ = ["PredictorEngine", "ComponentPrognosis", "PredictorRegistry"]
