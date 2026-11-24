"""The shared clock: pure state, injected time, no HTTP and no sleeping."""

from __future__ import annotations

import pytest

from telemetry.session import MAX_SPEED, MIN_SPEED, SessionState


class FakeClock:
    """Monotonic clock a test can advance by hand."""

    def __init__(self, start: float = 100.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def session(clock: FakeClock) -> SessionState:
    return SessionState(now=clock)


def test_clock_advances_one_to_one(session: SessionState, clock: FakeClock) -> None:
    clock.advance(3.5)

    assert session.current_elapsed() == pytest.approx(3.5)


def test_pause_freezes_the_clock(session: SessionState, clock: FakeClock) -> None:
    clock.advance(2.0)
    session.play(False)
    clock.advance(60.0)

    assert session.current_elapsed() == pytest.approx(2.0)

    session.play(True)
    clock.advance(1.0)

    assert session.current_elapsed() == pytest.approx(3.0)


def test_speed_scales_the_clock(session: SessionState, clock: FakeClock) -> None:
    session.set_speed(5.0)
    clock.advance(10.0)

    assert session.current_elapsed() == pytest.approx(50.0)


def test_speed_change_keeps_elapsed_time(session: SessionState, clock: FakeClock) -> None:
    clock.advance(4.0)
    session.set_speed(0.5)
    clock.advance(4.0)

    # 4 s at 1x, then 4 s at 0.5x.
    assert session.current_elapsed() == pytest.approx(6.0)


def test_seek_moves_the_anchor_and_keeps_playing(session: SessionState, clock: FakeClock) -> None:
    session.seek(120.0)
    clock.advance(1.0)

    assert session.current_elapsed() == pytest.approx(121.0)
    assert session.playing is True


def test_seek_while_paused_stays_paused(session: SessionState, clock: FakeClock) -> None:
    session.play(False)
    session.seek(150.0)
    clock.advance(30.0)

    assert session.current_elapsed() == pytest.approx(150.0)


def test_seek_is_clamped(session: SessionState) -> None:
    session.seek(-10.0)
    assert session.current_elapsed() == 0.0

    session.seek(99_999.0)
    assert session.current_elapsed() == 3600.0


def test_speed_is_clamped(session: SessionState) -> None:
    session.set_speed(0.0)
    assert session.speed == MIN_SPEED

    session.set_speed(1_000.0)
    assert session.speed == MAX_SPEED


def test_scenario_switch_restarts_the_ramp(session: SessionState, clock: FakeClock) -> None:
    clock.advance(30.0)
    session.select("nominal")

    assert session.scenario == "nominal"
    assert session.current_elapsed() == 0.0


def test_scenario_switch_can_keep_the_clock(session: SessionState, clock: FakeClock) -> None:
    clock.advance(30.0)
    session.select("nominal", reset_t=False)

    assert session.current_elapsed() == pytest.approx(30.0)


def test_scenario_switch_clears_trend_history(session: SessionState) -> None:
    session.last_elapsed_s = 42.0
    session.previous_health["gearbox"] = 0.4
    session.smoothed_health["gearbox"] = 0.5

    session.select("blade_imbalance")

    assert session.last_elapsed_s == -1.0
    assert session.previous_health == {}
    assert session.smoothed_health == {}


def test_focus_sequence_only_moves_on_change(session: SessionState) -> None:
    assert session.focus is None

    session.set_focus("gearbox")
    assert (session.focus, session.focus_seq) == ("gearbox", 1)

    session.set_focus("gearbox")
    assert session.focus_seq == 1, "re-focusing the same part must not re-grab the camera"

    session.set_focus("generator")
    assert (session.focus, session.focus_seq) == ("generator", 2)

    session.set_focus("")
    assert (session.focus, session.focus_seq) == (None, 3)


def test_snapshot_is_json_ready(session: SessionState, clock: FakeClock) -> None:
    clock.advance(12.346)
    session.set_speed(2.0)
    session.set_focus("gearbox")

    payload = session.snapshot()

    assert payload == {
        "scenario": "gearbox_degradation",
        "t": 12.35,
        "playing": True,
        "speed": 2.0,
        "focus": "gearbox",
        "focus_seq": 1,
    }
    assert isinstance(payload["t"], float)
