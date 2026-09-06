"""Emits throttled `runner.price` bus events per active runner.

Real Pro-tier data ticks at ~50ms (confirmed empirically — see README) —
publishing every single tick straight to the UI would flood the
websocket regardless of sim `--speed`, since throttling-by-wall-clock is
the only thing that actually bounds what a browser has to render:
`--speed 0` (as-fast-as-possible) has no pacing at all, and even a paced
run can bunch many ticks into the same wall-clock instant. So this
throttles by wall-clock time (time.monotonic()), independent of pacing —
at most `max_per_second` events per (market_id, selection_id), regardless
of how many ticks actually arrived in between.

Basic Plan markets naturally produce events with empty back/lay and only
ltp populated (no ladder in the data at all) — that's the real signal a
Ladder-scene "no depth data" state should key off, not a separate flag.
"""
from __future__ import annotations

import time
from typing import Callable

from flumine.markets.middleware import Middleware
from flumine.utils import get_price, get_size

from paddock.bus.bus import EventBus
from paddock.bus.bus import bus as default_bus
from paddock.bus.events import PriceLevel, RunnerPrice

DEFAULT_MAX_PER_SECOND = 10.0
LADDER_DEPTH = 3


def _levels(raw: list | None) -> list[PriceLevel]:
    if not raw:
        return []
    out = []
    for i in range(LADDER_DEPTH):
        price = get_price(raw, i)
        size = get_size(raw, i)
        if price is None:
            break
        out.append(PriceLevel(price=price, size=size or 0.0))
    return out


class RunnerPriceMiddleware(Middleware):
    def __init__(
        self,
        bus: EventBus = default_bus,
        max_per_second: float = DEFAULT_MAX_PER_SECOND,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.bus = bus
        self._min_interval = 1.0 / max_per_second if max_per_second > 0 else 0.0
        self._clock = clock
        self._last_emit: dict[tuple[str, int], float] = {}

    def __call__(self, market) -> None:
        market_book = market.market_book
        if market_book is None:
            return
        now = self._clock()
        for runner in market_book.runners:
            if runner.status != "ACTIVE":
                continue
            key = (market.market_id, runner.selection_id)
            last = self._last_emit.get(key)
            if last is not None and (now - last) < self._min_interval:
                continue
            self._last_emit[key] = now
            self.bus.publish(
                RunnerPrice(
                    market_id=market.market_id,
                    selection_id=runner.selection_id,
                    back=_levels(runner.ex.available_to_back),
                    lay=_levels(runner.ex.available_to_lay),
                    ltp=runner.last_price_traded,
                    traded_volume=(
                        sum(level["size"] for level in runner.ex.traded_volume)
                        if runner.ex.traded_volume
                        else None
                    ),
                )
            )

    def remove_market(self, market) -> None:
        stale = [k for k in self._last_emit if k[0] == market.market_id]
        for k in stale:
            del self._last_emit[k]
