"""One PredictorEngine per turbine; replay-on-seek; cache by (scenario, injection hash, tick).

The registry is the single entry point that main.py uses.  It owns the engines,
decides when replay is needed, and manages the alert queue that feeds SSE.

Replay contract
---------------
The calculator is a pure function of the sample stream.  Whenever the client
seeks backwards, switches scenario, or changes an injection, the engine is
reset and replayed from ``t = 0`` to the requested tick on the 1-hour grid.  The
caller supplies a ``sample_source(tick) -> Sample`` callback, so the registry
never needs to know how the simulator works.  At ≤1000 samples this is cheap
and makes results independent of navigation history.
"""
from __future__ import annotations

import hashlib
import json
import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable

from ..models import DEFAULT_TURBINE_ID, Sample
from .engine import PredictorEngine
from .models import ComponentPrognosis

SampleSource = Callable[[int], Sample]


@dataclass(frozen=True)
class Alert:
    """One queued SSE alert."""

    turbine_id: str
    event: dict[str, Any]


class PredictorRegistry:
    """Manages per-turbine engines with seek-safe caching."""

    def __init__(self) -> None:
        self._engines: dict[str, PredictorEngine] = {}
        # {turbine_id: {(fingerprint, tick): {component: ComponentPrognosis}}}
        self._cache: dict[str, dict[tuple[str, int], dict[str, ComponentPrognosis]]] = {}
        self._high_tick: dict[str, int] = {}
        self._current_key: dict[str, tuple[str, int]] = {}
        self._published: dict[str, set[str]] = {}
        self._subscribers: dict[queue.Queue[Alert], str] = {}
        self._lock = threading.RLock()

    # -- engine lifecycle --------------------------------------------------

    def _engine(self, turbine_id: str) -> PredictorEngine:
        if turbine_id not in self._engines:
            self._engines[turbine_id] = PredictorEngine(turbine_id)
        return self._engines[turbine_id]

    def invalidate(self, turbine_id: str | None = None) -> None:
        """Forget cached results so the next update replays from t=0."""
        with self._lock:
            self._invalidate(turbine_id)

    def _invalidate(self, turbine_id: str | None = None) -> None:
        targets = [turbine_id] if turbine_id else list(self._engines)
        for tid in targets:
            if tid in self._engines:
                self._engines[tid].reset()
            self._cache.pop(tid, None)
            self._high_tick.pop(tid, None)
            self._current_key.pop(tid, None)
            self._published.pop(tid, None)

    # -- main update path --------------------------------------------------

    def update(
        self,
        sample: Sample,
        injection_fingerprint: str = "",
        sample_source: SampleSource | None = None,
        publish_events: bool = True,
    ) -> dict[str, ComponentPrognosis]:
        """Process a sample; return the prognoses for its turbine.

        ``fingerprint`` must cover everything that changes the measured stream:
        the scenario plus the active injection set.  The sample's own scenario
        is mixed in automatically.
        """
        with self._lock:
            return self._update(sample, injection_fingerprint, sample_source, publish_events)

    def _update(
        self,
        sample: Sample,
        injection_fingerprint: str,
        sample_source: SampleSource | None,
        publish_events: bool,
    ) -> dict[str, ComponentPrognosis]:
        tid = sample.turbine_id
        tick = sample.tick
        fingerprint = make_stream_fingerprint(sample.scenario, injection_fingerprint)
        cache_key = (fingerprint, tick)

        turb_cache = self._cache.setdefault(tid, {})
        # A past cached result cannot restore the engine's internal state or
        # event history. Only reuse a result when it is also the current tick.
        if cache_key == self._current_key.get(tid) and cache_key in turb_cache:
            return turb_cache[cache_key]

        engine = self._engine(tid)
        previous_high = self._high_tick.get(tid)
        current = self._current_key.get(tid)
        replay = (
            previous_high is None
            or tick <= previous_high
            or current is None
            or current[0] != fingerprint
        )

        if current is not None and current[0] != fingerprint:
            # A new scenario/injection stream is a distinct run even if its
            # deterministic event timestamps happen to match the previous one.
            self._published[tid] = set()

        high = previous_high
        if replay:
            engine.reset()
            turb_cache.clear()
            high = -1
            if sample_source is not None:
                # Replay the historical ticks strictly before the target.
                for historical_tick in range(tick):
                    self._cache_result(
                        turb_cache, engine, sample_source(historical_tick), fingerprint
                    )
                high = tick - 1
        elif sample_source is not None and tick > (high if high is not None else -1) + 1:
            # The clock jumped forward (the console polls once a second, which
            # is eight asset-hours).  Feed every skipped tick so the EWMA and
            # trend see the same stream they would during continuous playback.
            for missing_tick in range((high if high is not None else -1) + 1, tick):
                result = self._cache_result(
                    turb_cache, engine, sample_source(missing_tick), fingerprint
                )
                if publish_events:
                    self._publish(tid, result)
                high = missing_tick

        result = engine.update(sample)
        turb_cache[cache_key] = result
        self._high_tick[tid] = max(high if high is not None else -1, tick)
        self._current_key[tid] = cache_key

        if publish_events:
            self._publish(tid, result)

        return result

    @staticmethod
    def _cache_result(
        turb_cache: dict[tuple[str, int], dict[str, ComponentPrognosis]],
        engine: PredictorEngine,
        sample: Sample,
        fingerprint: str,
    ) -> dict[str, ComponentPrognosis]:
        result = engine.update(sample)
        turb_cache[(fingerprint, sample.tick)] = result
        return result

    def _publish(
        self, turbine_id: str, result: dict[str, ComponentPrognosis]
    ) -> None:
        """Queue alert events once per event id (the store keeps them active)."""
        published = self._published.setdefault(turbine_id, set())
        for prognosis in result.values():
            for event in prognosis.active_events:
                event_id = str(event.get("event_id", ""))
                if not event_id or event_id in published:
                    continue
                published.add(event_id)
                for subscriber, owner in self._subscribers.items():
                    if owner != turbine_id:
                        continue
                    try:
                        subscriber.put_nowait(Alert(turbine_id, event))
                    except queue.Full:
                        # A slow SSE consumer must never stall the telemetry clock.
                        pass

    # -- SSE / event log ---------------------------------------------------

    def subscribe(self, turbine_id: str) -> queue.Queue[Alert]:
        """Create an independent, turbine-filtered stream for one client."""
        subscriber: queue.Queue[Alert] = queue.Queue(maxsize=512)
        with self._lock:
            self._subscribers[subscriber] = turbine_id
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[Alert]) -> None:
        with self._lock:
            self._subscribers.pop(subscriber, None)

    def event_history(self, turbine_id: str = DEFAULT_TURBINE_ID) -> list[dict]:
        with self._lock:
            engine = self._engines.get(turbine_id)
            return engine.event_history() if engine else []

    def all_active_events(self, turbine_id: str = DEFAULT_TURBINE_ID) -> list[dict]:
        with self._lock:
            engine = self._engines.get(turbine_id)
            return engine.all_active_events() if engine else []

    # -- current prognosis snapshot ----------------------------------------

    def current(self, turbine_id: str = DEFAULT_TURBINE_ID) -> dict[str, ComponentPrognosis]:
        """Return the most recently computed prognoses for a turbine."""
        with self._lock:
            cache_key = self._current_key.get(turbine_id)
            if cache_key is None:
                return {}
            return self._cache.get(turbine_id, {}).get(cache_key, {})


def make_stream_fingerprint(scenario: str, injection_fingerprint: str) -> str:
    """Stable key for everything that changes the measured sample stream."""
    return f"{scenario}:{injection_fingerprint}"


def make_injection_fingerprint(injection_dicts: list[dict]) -> str:
    """Stable hash of the active injection set so the cache can key on it."""
    blob = json.dumps(injection_dicts, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]
