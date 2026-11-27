"""Pure time-envelope functions returning a bounded progression in [0, 1]."""

from __future__ import annotations

import hashlib
import math

from .models import Progression

_EXP_STEEPNESS = 3.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _smoothstep01(u: float) -> float:
    u = _clamp01(u)
    return u * u * (3.0 - 2.0 * u)


def _intermittent_slot_on(seed: str | int, slot: int, duty: float) -> bool:
    if slot <= 0:
        return True
    key = f"{seed}:{slot}".encode("utf-8")
    digest = hashlib.blake2b(key, digest_size=8).digest()
    draw = int.from_bytes(digest, "big") / float((1 << 64) - 1)
    return draw < duty


def envelope(
    asset_time_h: float,
    onset_asset_h: float,
    progression: Progression,
    seed: str | int = 0,
) -> float:
    """Evaluate a progression envelope at ``asset_time_h`` in ``[0.0, 1.0]``.

    Pure and random-access: evaluating at any hour never mutates state and
    always produces identical results after seeking or replaying.
    """
    if asset_time_h < onset_asset_h:
        return 0.0

    dt = float(asset_time_h) - float(onset_asset_h)
    kind = progression.kind

    if kind == "ramp":
        if progression.duration_h <= 0.0:
            return 1.0
        u = _clamp01(dt / progression.duration_h)
        if progression.curve == "exponential":
            denom = math.exp(_EXP_STEEPNESS) - 1.0
            return _clamp01((math.exp(_EXP_STEEPNESS * u) - 1.0) / denom)
        return u

    if kind == "step":
        settle = (
            progression.settle_h
            if progression.settle_h is not None
            else (min(progression.duration_h, 2.0) if progression.duration_h > 0.0 else 0.0)
        )
        if settle <= 0.0 or dt >= settle:
            return 1.0
        # Immediate jump above half-scale at onset, settling smoothly to 1.0.
        return _clamp01(0.5 + 0.5 * _smoothstep01(dt / settle))

    if kind == "intermittent":
        slot_h = (
            progression.period_h
            if progression.period_h is not None
            else max(1.0, min(8.0, (progression.duration_h or 48.0) / 12.0))
        )
        slot = int(dt // slot_h)
        return 1.0 if _intermittent_slot_on(seed, slot, progression.duty) else 0.0

    if kind == "stepwise":
        if progression.duration_h <= 0.0:
            return 1.0
        u = _clamp01(dt / progression.duration_h)
        if u >= 1.0:
            return 1.0
        steps = max(2, int(progression.steps))
        return _clamp01(math.floor(u * steps) / float(steps))

    raise ValueError(f"unsupported progression kind '{kind}'")
