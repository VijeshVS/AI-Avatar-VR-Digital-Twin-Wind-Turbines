"""Residual computation, EWMA and z-score per signal.

The residual is the difference between what the sensor reports and what the
baseline model expects for the current operating point.  An EWMA smooths the
raw residual; the z-score normalises by the EWMA's own standard deviation.

One-sided z (gating only the upward tail) is used for signals where only an
increase indicates damage (temperature, vibration).  Two-sided is used where
either direction matters (power_ratio, pitch_error).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import baseline as bl
from .config import EWMA_ALPHA, MIN_POWER_RATIO

# Signals where z < 0 is not an alarm (only high values indicate damage).
_ONE_SIDED = frozenset(
    {
        "gearbox_temp_c",
        "gearbox_vibration_mm_s",
        "generator_winding_temp_c",
        "main_bearing_temp",
        "main_bearing_vibration",
        "blade_1p_ratio",
        "converter_fault_rate",
    }
)


@dataclass
class SignalEWMA:
    """Running EWMA state for one signal on one turbine."""

    signal_id: str
    alpha: float = EWMA_ALPHA
    ewma: float = 0.0
    _initialised: bool = False

    def update(self, residual: float) -> float:
        """Feed a new residual; return the updated EWMA."""
        if not self._initialised:
            self.ewma = residual
            self._initialised = True
        else:
            self.ewma = self.alpha * residual + (1.0 - self.alpha) * self.ewma
        return self.ewma

    def reset(self) -> None:
        self.ewma = 0.0
        self._initialised = False


@dataclass
class ResidualState:
    """All EWMA accumulators for one turbine component or the full signal set."""

    _ewmas: dict[str, SignalEWMA] = field(default_factory=dict)

    def _get(self, signal_id: str) -> SignalEWMA:
        if signal_id not in self._ewmas:
            self._ewmas[signal_id] = SignalEWMA(signal_id)
        return self._ewmas[signal_id]

    def update(
        self, signal_id: str, measured: dict[str, float]
    ) -> tuple[float, float, float]:
        """Compute (residual, ewma, z) for one signal given the measured dict.

        Returns ``(0.0, 0.0, 0.0)`` for unmodelled signals.
        """
        exp = bl.expected(signal_id, measured)
        if exp is None:
            return 0.0, 0.0, 0.0

        raw_val = measured.get(signal_id, exp)
        residual = raw_val - exp
        ewma_val = self._get(signal_id).update(residual)

        # z-score of the EWMA.  Its standard deviation is calibrated on nominal
        # data (see baseline.ewma_sigma); the white-noise formula is the fallback.
        sigma_ewma = bl.ewma_sigma(signal_id)
        sigma_ewma = max(1e-9, sigma_ewma)
        z_raw = ewma_val / sigma_ewma

        # One-sided: damage only on the upward side.
        if signal_id in _ONE_SIDED:
            z = max(0.0, z_raw)
        else:
            z = abs(z_raw)

        return residual, ewma_val, z

    def reset(self, signal_id: str | None = None) -> None:
        """Reset EWMA for one signal or all signals."""
        if signal_id is None:
            for ew in self._ewmas.values():
                ew.reset()
        elif signal_id in self._ewmas:
            self._ewmas[signal_id].reset()

    def reset_all(self) -> None:
        self._ewmas.clear()


def should_skip(measured: dict[str, float]) -> bool:
    """Return True when the turbine is idling and residuals should not be updated."""
    return measured.get("power_ratio", 1.0) < MIN_POWER_RATIO
