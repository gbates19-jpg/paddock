"""Wall-clock pacing for FlumineSimulation.

FlumineSimulation (flumine 3.2.0) replays historic market-change files as
fast as the interpreter can go — there is no built-in notion of real time.
For the visual control room we want a market to feel like it's actually
happening, so this Middleware sleeps just enough, per tick, to keep
market-time advancing at `speed` market-seconds per real-second.

Design:

- flumine calls `middleware(market)` once per market_book update, for every
  registered market middleware, AFTER `market.market_book` has already been
  updated to the new tick (confirmed in flumine/simulation/simulation.py:
  `market(market_book)` runs, then `for middleware in self._market_middleware`).
  So on each call, `market.market_book.publish_time_epoch` (ms since epoch,
  confirmed in betfairlightweight's MarketBook resource) is the current
  tick's market-time.

- Per market_id we anchor the first tick we see: (market_epoch_0, wall_0).
  Every later tick computes how far market-time has advanced since that
  anchor, divides by `speed` to get target wall-clock elapsed, and sleeps
  off the difference against actual wall-clock elapsed since wall_0. This
  is a target-vs-actual comparison rather than a fixed per-tick sleep,
  which avoids compounding drift from the (variable) cost of strategy
  processing between ticks.

- Reset between markets: the anchor is keyed by market_id and only created
  on that market's first tick, so a new market naturally starts its own
  clock relative to its own first tick rather than the wall-clock time
  another market happened to reach. `remove_market()` (a real Middleware
  hook flumine calls when it drops a market) deletes the anchor so a long
  batch run over many market files doesn't leak memory. Markets replayed
  out of publish-time order across files are handled independently since
  each has its own anchor — but the anchors dict itself is a plain dict, so
  if the *same* market_id were ever replayed twice in one process (not a
  real scenario for historic files) it would reuse the stale anchor; not
  guarded against since it can't happen with flumine's normal one-shot
  historic streams.

- speed <= 0 means "as fast as possible" (the current bulk-backtest
  default): the middleware becomes a no-op past the first anchor tick, so
  bulk multi-month backtests aren't slowed down by anchor bookkeeping. It
  is not "speed 0 pauses forever" — 0 is the escape hatch, matching the
  `--speed 0` CLI flag in the brief.

- No clamping/max-sleep: a market with big historic-file publish-time gaps
  (e.g. hours between pre-off and in-play data on this exact fixture) would
  sleep for real hours at speed=1. That's intentional for a genuine replay
  at speed=1, but means realistic demo usage should pick a speed high
  enough (tens to thousands) that gaps collapse into something watchable —
  the CLI default is not speed=1.
"""
from __future__ import annotations

import time
from typing import Callable

from flumine.markets.middleware import Middleware


class WallClockPacingMiddleware(Middleware):
    def __init__(
        self,
        speed: float = 20.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.speed = speed
        self._clock = clock
        self._sleep = sleep
        self._anchors: dict[str, tuple[float, float]] = {}  # market_id -> (market_epoch_0, wall_0)

    def __call__(self, market) -> None:
        if self.speed <= 0:
            return
        market_book = market.market_book
        if market_book is None or market_book.publish_time_epoch is None:
            return

        market_epoch = market_book.publish_time_epoch / 1000.0
        wall_now = self._clock()

        anchor = self._anchors.get(market.market_id)
        if anchor is None:
            self._anchors[market.market_id] = (market_epoch, wall_now)
            return

        market_epoch_0, wall_0 = anchor
        target_wall_elapsed = (market_epoch - market_epoch_0) / self.speed
        actual_wall_elapsed = wall_now - wall_0
        sleep_for = target_wall_elapsed - actual_wall_elapsed
        if sleep_for > 0:
            self._sleep(sleep_for)

    def remove_market(self, market) -> None:
        self._anchors.pop(market.market_id, None)
