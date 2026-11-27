"""One session clock, shared by every client of the twin.

Before this module the service was stateless about time: each client counted its
own ticks and passed ``?t=``. That was fine with one client, but a web console and
the Unity twin would then disagree about which moment they were showing — the
page could say "critical" while the twin still rendered the healthy ramp.

The session now owns an anchor time and advances it from a monotonic clock, so a
single control command moves every view together. ``?t=`` remains an explicit
override for the test suite and the offline replay, which ask for a specific
moment and must keep receiving exactly that frame.

The clock is deliberately dependency-free and injectable: ``SessionState(now=...)``
lets tests advance time without sleeping.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from . import simulation

DEFAULT_SPEED = 1.0
MIN_SPEED = 0.1
MAX_SPEED = 100.0
MAX_ELAPSED_S = 3600.0

ASSET_HOURS_PER_SIM_SECOND = simulation.ASSET_HOURS_PER_SIM_SECOND
SIM_SECONDS_PER_ASSET_HOUR = simulation.SIM_SECONDS_PER_ASSET_HOUR


# -- asset-time helpers ------------------------------------------------------
#
# The session clock is expressed in simulation seconds, but the engine samples
# once per asset-hour. These helpers are the single conversion point, so the
# browser, Unity and the predictor cannot disagree about which tick "now" is.


def asset_hours(sim_seconds: float) -> float:
    """Simulation seconds -> asset-hours (the engine's clock)."""
    return simulation.asset_time_hours(sim_seconds)


def sim_seconds(asset_hours: float) -> float:
    """Asset-hours -> simulation seconds."""
    return simulation.sim_seconds_for_asset_hours(asset_hours)


def tick_index(sim_seconds: float) -> int:
    """Nearest engine tick (one asset-hour) for a simulation time."""
    return simulation.tick_index_at(sim_seconds)


def sim_time_for_tick(tick: int) -> float:
    """Simulation time of an engine tick."""
    return simulation.sim_seconds_for_tick(tick)


# Descriptive aliases, for callers that prefer the long form.
asset_time_hours = asset_hours
sim_seconds_for_asset_hours = sim_seconds
tick_index_at = tick_index
sim_seconds_for_tick = sim_time_for_tick


class SessionState:
    """Scenario, clock and the smoothing state used to report health trends."""

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._updated_at = now()

        self.scenario: str = simulation.default_scenario()
        self.elapsed_s: float = 0.0  # anchor; current time is derived from it
        self.playing: bool = True
        self.speed: float = DEFAULT_SPEED
        self.focus: str | None = None
        self.focus_seq: int = 0

        # Latest health per (turbine, component), used only to derive a trend.
        self.last_elapsed_s: float = -1.0
        self.previous_health: dict[tuple[str, str], float] = {}
        self.smoothed_health: dict[tuple[str, str], float] = {}

    # -- clock -------------------------------------------------------------

    def current_elapsed(self) -> float:
        """Scenario time now, without mutating the anchor."""
        if not self.playing:
            return self.elapsed_s
        return self.elapsed_s + max(0.0, self._now() - self._updated_at) * self.speed

    def _commit(self) -> None:
        """Fold the time that has passed into the anchor before a change."""
        self.elapsed_s = self.current_elapsed()
        self._updated_at = self._now()

    def seek(self, seconds: float) -> None:
        """Jump to a scenario time, keeping the play/pause state."""
        self.elapsed_s = min(MAX_ELAPSED_S, max(0.0, float(seconds)))
        self._updated_at = self._now()

    def play(self, playing: bool = True) -> None:
        self._commit()
        self.playing = bool(playing)

    def set_speed(self, speed: float) -> None:
        self._commit()
        self.speed = min(MAX_SPEED, max(MIN_SPEED, float(speed)))

    # -- scenario and focus -------------------------------------------------

    def select(self, scenario: str, reset_t: bool = True) -> None:
        """Switch the fault programme and, by default, restart its ramp."""
        self.scenario = scenario
        self.last_elapsed_s = -1.0
        self.previous_health.clear()
        self.smoothed_health.clear()
        if reset_t:
            self.seek(0.0)

    def set_focus(self, component_id: str | None) -> None:
        """Ask the twin to look at one component. Empty clears the focus.

        ``focus_seq`` increments only on a real change, so a client can apply the
        command once and then let the user fly the camera away again.
        """
        target = component_id or None
        if target == self.focus:
            return
        self.focus = target
        self.focus_seq += 1

    # -- wire ---------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "t": round(self.current_elapsed(), 2),
            "playing": self.playing,
            "speed": self.speed,
            "focus": self.focus,
            "focus_seq": self.focus_seq,
        }
