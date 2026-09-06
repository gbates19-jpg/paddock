from types import SimpleNamespace

from paddock.sim.pacing import WallClockPacingMiddleware


def _market_at(market_id: str, publish_time_epoch_ms: int):
    market_book = SimpleNamespace(publish_time_epoch=publish_time_epoch_ms)
    return SimpleNamespace(market_id=market_id, market_book=market_book)


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_first_tick_only_anchors_no_sleep():
    clock = FakeClock()
    sleeps: list[float] = []
    mw = WallClockPacingMiddleware(speed=1.0, clock=clock, sleep=sleeps.append)

    mw(_market_at("1.1", 0))

    assert sleeps == []


def test_paces_to_speed_between_ticks():
    clock = FakeClock()
    sleeps: list[float] = []
    mw = WallClockPacingMiddleware(speed=2.0, clock=clock, sleep=sleeps.append)

    mw(_market_at("1.1", 0))  # anchor at market_epoch=0, wall=0
    # market time advances 10s; at speed=2 that should take 5s wall-clock.
    # No real wall-clock time has passed (FakeClock didn't advance), so we
    # expect a sleep of ~5s to make up the difference.
    mw(_market_at("1.1", 10_000))

    assert len(sleeps) == 1
    assert sleeps[0] == 5.0


def test_no_sleep_if_wall_clock_already_caught_up():
    clock = FakeClock()
    sleeps: list[float] = []
    mw = WallClockPacingMiddleware(speed=2.0, clock=clock, sleep=sleeps.append)

    mw(_market_at("1.1", 0))
    clock.advance(5.0)  # wall-clock already advanced as much as target
    mw(_market_at("1.1", 10_000))

    assert sleeps == []


def test_speed_zero_never_sleeps():
    clock = FakeClock()
    sleeps: list[float] = []
    mw = WallClockPacingMiddleware(speed=0, clock=clock, sleep=sleeps.append)

    mw(_market_at("1.1", 0))
    mw(_market_at("1.1", 100_000))

    assert sleeps == []


def test_each_market_gets_its_own_clock():
    clock = FakeClock()
    sleeps: list[float] = []
    mw = WallClockPacingMiddleware(speed=1.0, clock=clock, sleep=sleeps.append)

    # market A anchors far in the future relative to market B
    mw(_market_at("1.A", 1_000_000_000))
    mw(_market_at("1.B", 0))  # unrelated market — must not inherit A's anchor
    mw(_market_at("1.B", 1_000))  # +1s market time for B, speed=1 -> ~1s sleep

    assert len(sleeps) == 1
    assert sleeps[0] == 1.0


def test_remove_market_clears_anchor_so_it_restarts_clean():
    clock = FakeClock()
    sleeps: list[float] = []
    mw = WallClockPacingMiddleware(speed=1.0, clock=clock, sleep=sleeps.append)

    market = _market_at("1.1", 0)
    mw(market)
    mw.remove_market(market)

    # after removal, the next tick re-anchors instead of computing a huge
    # sleep against the old anchor
    mw(_market_at("1.1", 50_000))
    assert sleeps == []
