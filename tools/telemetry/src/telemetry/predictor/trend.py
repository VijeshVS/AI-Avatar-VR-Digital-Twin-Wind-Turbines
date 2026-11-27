"""Theil-Sen TTF forecast with confidence score and gating.

The issue specifies:
  • Ring buffer of component health (asset-hour samples).
  • Theil-Sen slope = median of all pairwise slopes.
  • TTF = (health_now − 0.45) / (−slope), in asset-hours → days.
  • Range: 25th–75th percentile of pairwise slopes → lo/hi TTF.
  • Confidence = 0.4·|Kendall τ| + 0.3·persistence + 0.3·(1 − width/upper).
  • Gate: report only when EWMA z > Z_WARN for K consecutive samples
    AND the upper slope quartile is still negative.
  • After a step event the window is restarted at step_time + settle.
"""
from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field

from .config import (
    HEALTH_CRITICAL,
    PROGNOSIS_GATE_K,
    TREND_LONG_H,
    TREND_SHORT_H,
    Z_WARN,
)


@dataclass
class TrendWindow:
    """Ring buffer of (asset_time_h, health) pairs."""

    max_size: int = TREND_LONG_H
    _buf: deque = field(default_factory=lambda: deque(maxlen=TREND_LONG_H))

    def __post_init__(self) -> None:
        self._buf = deque(self._buf, maxlen=self.max_size)

    def push(self, asset_time_h: float, health: float) -> None:
        self._buf.append((asset_time_h, health))

    def reset_after(self, asset_time_h: float) -> None:
        """Drop all samples at or before ``asset_time_h`` (post-step restart)."""
        self._buf = deque(
            ((t, h) for t, h in self._buf if t > asset_time_h),
            maxlen=self.max_size,
        )

    def reset_all(self) -> None:
        self._buf.clear()

    def samples(self, max_h: int | None = None) -> list[tuple[float, float]]:
        pts = list(self._buf)
        if max_h is not None:
            pts = pts[-max_h:]
        return pts

    def __len__(self) -> int:
        return len(self._buf)


def _pairwise_slopes(pts: list[tuple[float, float]]) -> list[float]:
    """All (y2 - y1) / (x2 - x1) pairs; O(n²), fine for n ≤ 168."""
    slopes = []
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            dt = pts[j][0] - pts[i][0]
            if abs(dt) < 1e-9:
                continue
            slopes.append((pts[j][1] - pts[i][1]) / dt)
    return slopes


def _kendall_tau(pts: list[tuple[float, float]]) -> float:
    """Kendall τ-b correlation between time and health values."""
    n = len(pts)
    if n < 2:
        return 0.0
    concordant = discordant = tied_x = tied_y = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx = pts[j][0] - pts[i][0]
            dy = pts[j][1] - pts[i][1]
            if dx == 0:
                tied_x += 1
            elif dy == 0:
                tied_y += 1
            elif (dx > 0) == (dy > 0):
                concordant += 1
            else:
                discordant += 1
    denom_sq = (concordant + discordant + tied_x) * (concordant + discordant + tied_y)
    return (concordant - discordant) / (denom_sq ** 0.5) if denom_sq > 0 else 0.0


def _theil_sen(pts: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Return (median_slope, q25_slope, q75_slope) in health-per-asset-hour."""
    slopes = _pairwise_slopes(pts)
    if not slopes:
        return 0.0, 0.0, 0.0
    slopes.sort()
    n = len(slopes)
    q25 = slopes[int(n * 0.25)]
    q75 = slopes[int(n * 0.75)]
    return statistics.median(slopes), q25, q75


@dataclass
class GateState:
    """Tracks consecutive ticks where z > Z_WARN for one component."""

    consecutive: int = 0

    def update(self, z_max: float) -> bool:
        """Return True when the prognosis gate is open (K consecutive ticks)."""
        if z_max > Z_WARN:
            self.consecutive += 1
        else:
            self.consecutive = 0
        return self.consecutive >= PROGNOSIS_GATE_K

    def reset(self) -> None:
        self.consecutive = 0


def estimate(
    window: TrendWindow,
    health_now: float,
    gate_open: bool,
) -> tuple[tuple[float, float] | None, str, float | None]:
    """Return (ttf_days, band, confidence) for the given window and gate.

    ``ttf_days`` is a (lo, hi) tuple or None when no prognosis is applicable.
    ``band`` is one of "<8 d", "8-30 d", ">30 d", "critical", "stable", "unknown".
    ``confidence`` is in [0, 1] or None.
    """
    pts_long = window.samples(TREND_LONG_H)
    pts_short = window.samples(TREND_SHORT_H)

    if len(pts_long) < 3:
        return None, "unknown", None

    if health_now <= HEALTH_CRITICAL:
        return None, "critical", 1.0

    if not gate_open:
        return None, "stable", None

    slope_med_l, q25_l, q75_l = _theil_sen(pts_long)
    slope_med_s, q25_s, q75_s = _theil_sen(pts_short)

    # Both windows must continue declining, even at their upper quartile.
    if max(q75_l, q75_s) >= 0:
        return None, "stable", None

    # Theil-Sen forecast using the more pessimistic (steeper-decline) slope.
    slope_med = min(slope_med_l, slope_med_s)

    if slope_med >= 0:
        return None, "stable", None

    # TTF from median slope and from quartile slopes.
    def _ttf(slope: float) -> float | None:
        if slope >= 0:
            return None
        h = (health_now - HEALTH_CRITICAL) / (-slope)  # asset-hours
        return h / 24.0  # → days

    ttf_med  = _ttf(slope_med)
    # q25 is the more negative (steeper) slope. Use the extremes across
    # both windows rather than collapsing the interval to one endpoint.
    ttf_lo_d = _ttf(min(q25_l, q25_s))
    ttf_hi_d = _ttf(max(q75_l, q75_s))

    if ttf_med is None:
        return None, "stable", None

    if ttf_lo_d is None:
        ttf_lo_d = ttf_med * 0.5
    if ttf_hi_d is None:
        ttf_hi_d = ttf_med * 2.0

    ttf_lo_d = max(0.0, ttf_lo_d)
    ttf_hi_d = max(ttf_lo_d, ttf_hi_d)

    # Band from median estimate.
    if ttf_med < 8.0:
        band = "<8 d"
    elif ttf_med <= 30.0:
        band = "8-30 d"
    else:
        band = ">30 d"

    # Confidence heuristic.
    tau = abs(_kendall_tau(pts_long))
    # Persistence: fraction of samples where health is falling.
    slopes_all = _pairwise_slopes(pts_long)
    persistence = (sum(1 for s in slopes_all if s < 0) / len(slopes_all)) if slopes_all else 0.0
    width = ttf_hi_d - ttf_lo_d
    upper = max(ttf_hi_d, 1.0)
    conf = 0.4 * tau + 0.3 * persistence + 0.3 * max(0.0, 1.0 - width / upper)
    conf = max(0.0, min(1.0, conf))

    return (ttf_lo_d, ttf_hi_d), band, conf
