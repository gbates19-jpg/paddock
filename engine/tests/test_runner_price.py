from __future__ import annotations

from types import SimpleNamespace

from paddock.bus.bus import EventBus
from paddock.sim.runner_price import RunnerPriceMiddleware


def _runner(selection_id, status="ACTIVE", atb=None, atl=None, ltp=None, trd=None):
    return SimpleNamespace(
        selection_id=selection_id,
        status=status,
        last_price_traded=ltp,
        ex=SimpleNamespace(
            available_to_back=atb or [],
            available_to_lay=atl or [],
            traded_volume=trd or [],
        ),
    )


def _market(market_id, runners):
    return SimpleNamespace(
        market_id=market_id, market_book=SimpleNamespace(runners=runners)
    )


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_throttles_to_max_rate_per_runner():
    bus = EventBus()
    published = []
    bus.publish = lambda e: published.append(e)  # type: ignore

    clock = FakeClock()
    mw = RunnerPriceMiddleware(bus=bus, max_per_second=10.0, clock=clock)
    runner = _runner(1, ltp=2.5)
    market = _market("1.1", [runner])

    mw(market)  # t=0, first emit
    clock.t = 0.05  # 50ms later — under the 100ms (1/10s) interval
    mw(market)
    clock.t = 0.15  # now past the interval
    mw(market)

    assert len(published) == 2


def test_emits_empty_ladder_for_basic_plan_shape():
    bus = EventBus()
    published = []
    bus.publish = lambda e: published.append(e)  # type: ignore

    mw = RunnerPriceMiddleware(bus=bus, max_per_second=10.0, clock=FakeClock())
    runner = _runner(1, ltp=2.5, atb=[], atl=[])  # Basic Plan shape: no ladder at all
    market = _market("1.1", [runner])

    mw(market)

    assert len(published) == 1
    event = published[0]
    assert event.back == []
    assert event.lay == []
    assert event.ltp == 2.5


def test_ignores_non_active_runners():
    bus = EventBus()
    published = []
    bus.publish = lambda e: published.append(e)  # type: ignore

    mw = RunnerPriceMiddleware(bus=bus, max_per_second=10.0, clock=FakeClock())
    runner = _runner(1, status="REMOVED", ltp=2.5)
    market = _market("1.1", [runner])

    mw(market)

    assert published == []
