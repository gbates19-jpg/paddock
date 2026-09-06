"""BaselineFavouriteScalp — deliberately dumb, proves the pipeline end to
end rather than making money (see the Phase 0 brief).

Sequential legs, flat-at-off invariant (revised after step 3 review — the
original simultaneous back+lay design could leave a naked unhedged
position if the lay never matched):

  1. From `place_seconds_before_off` before the off: identify the
     favourite (best available back price) and place ENTRY — a BACK order
     for `stake`. Once per market.
  2. As soon as entry has ANY matched size (full or partial), place EXIT —
     a passive LAY `lay_ticks` ticks below entry's average matched price,
     sized to exactly entry's matched size at that moment (not the
     original stake — if entry only partially fills, we only ever try to
     hedge what actually got matched). Also once per market.
  3. At `cancel_seconds_before_off` before the off (a single one-shot
     transition, `_MarketState.at_off_handled`):
       a. If entry still has an unmatched remainder: cancel it. Whatever
          matched by this point is final.
       b. If nothing of entry ever matched: done, flat, no exit was ever
          needed.
       c. If entry matched but exit doesn't fully cover it (exit was never
          placed, only partially matched, or entry kept matching after
          exit was sized): cancel exit's remaining unmatched portion (if
          any) and place a CLOSER order — an aggressive LAY, sized to
          exactly the uncovered amount, at the current best-available
          crossing price — to force the position flat before settlement.
          This is "accept the red": no attempt to get a good price, just
          get matched now.
  4. This guarantees zero net position on the runner by market close in
     every reachable scenario: entry never matched (no exit ever placed);
     entry+exit both fully matched (flat by construction, exit size ==
     entry size); entry matched, exit under-filled (closer order tops up
     the shortfall). See tests/test_baseline_strategy.py for all three,
     driven through real flumine machinery against synthetic market data
     so the invariant is checked against actual order lifecycle, not a
     hand-simulated one.

Fill-model-agnostic, and the "best available" assumption under ltp_cross:
_best_back_price reads runner.ex.available_to_back (fill_model=ladder /
Advanced+Pro data) and falls back to runner.last_price_traded when that's
empty (fill_model=ltp_cross / Basic Plan data, which carries no order
book at all). That fallback is a real assumption, not a neutral default:
on Basic data we have no way to know what price is actually available to
trade at right now, so we approximate it as "the last price this
selection actually traded at" — reasonable in a liquid, actively-traded
market close to the off, optimistic (and potentially stale) right after a
market opens or during a quiet patch with no recent trades. The same
fallback is reused for the CLOSER order's crossing price at T-30s, for
the same reason: it's the least-bad proxy for "get matched immediately"
that Basic data actually offers. The strategy itself doesn't know or care
which fill_model produced the price it's looking at — that split is
enforced by the engine (paddock.sim.harness/fill_models), not here.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass

from flumine.order.order import OrderStatus
from flumine.order.ordertype import LimitOrder
from flumine.order.trade import Trade
from flumine.strategy.strategy import BaseStrategy
from flumine.utils import get_price, price_ticks_away

from paddock.bus.bus import bus as default_bus
from paddock.bus.events import StrategySignal
from paddock.sim.orders import place_order

logger = logging.getLogger(__name__)

MIN_CLOSER_SIZE = 0.01  # below this, floating point noise, not a real shortfall


@dataclass
class _MarketState:
    favourite_selection_id: int | None = None
    entry_order: object | None = None
    exit_order: object | None = None
    closer_order: object | None = None
    at_off_handled: bool = False


class BaselineFavouriteScalp(BaseStrategy):
    def __init__(
        self,
        *args,
        stake: float = 2.0,
        place_seconds_before_off: float = 300,
        cancel_seconds_before_off: float = 30,
        lay_ticks: int = 2,
        bus=None,
        **kwargs,
    ):
        # Entry and exit are separate Trade objects on the same runner, and
        # can be concurrently live (e.g. entry's unmatched remainder still
        # resting while exit is live against the matched portion) —
        # flumine's BaseStrategy default (max_live_trade_count=1) rejects
        # the second leg as a STRATEGY_EXPOSURE violation with no
        # exception raised, just a silently voided order (see
        # tests/test_logging_control.py::test_order_rejected_event_fires_
        # on_max_live_trade_count_violation for what that looks like and
        # how it's now surfaced instead of silently swallowed).
        kwargs.setdefault("max_live_trade_count", 2)
        super().__init__(*args, **kwargs)
        self.stake = stake
        self.place_seconds_before_off = place_seconds_before_off
        self.cancel_seconds_before_off = cancel_seconds_before_off
        self.lay_ticks = lay_ticks
        self.bus = bus or default_bus
        self._state: dict[str, _MarketState] = {}

    def _market_state(self, market_id: str) -> _MarketState:
        state = self._state.get(market_id)
        if state is None:
            state = _MarketState()
            self._state[market_id] = state
        return state

    def remove_market(self, market_id: str) -> None:
        super().remove_market(market_id)
        self._state.pop(market_id, None)

    def _seconds_to_off(self, market, market_book) -> float | None:
        off = market.market_start_datetime
        now = market_book.publish_time
        if off is None or now is None:
            return None
        return (off - now).total_seconds()

    @staticmethod
    def _best_back_price(runner) -> float | None:
        # See module docstring: this is also used as the CLOSER order's
        # crossing price, not just for entry price discovery.
        price = get_price(runner.ex.available_to_back, 0)
        return price if price else runner.last_price_traded

    def check_market_book(self, market, market_book) -> bool:
        if market_book.status != "OPEN":
            return False
        seconds_to_off = self._seconds_to_off(market, market_book)
        return seconds_to_off is not None and seconds_to_off <= self.place_seconds_before_off

    def process_market_book(self, market, market_book) -> None:
        state = self._market_state(market.market_id)
        seconds_to_off = self._seconds_to_off(market, market_book)
        if seconds_to_off is None:
            return

        if state.entry_order is None:
            self._place_entry(market, market_book, state)

        if (
            state.entry_order is not None
            and state.exit_order is None
            and state.entry_order.size_matched > 0
        ):
            self._place_exit(market, state)

        if not state.at_off_handled and seconds_to_off <= self.cancel_seconds_before_off:
            self._handle_at_off(market, market_book, state)

    def _find_favourite(self, market_book) -> tuple | None:
        candidates = []
        for runner in market_book.runners:
            if runner.status != "ACTIVE":
                continue
            price = self._best_back_price(runner)
            if price:
                candidates.append((price, runner))
        if not candidates:
            return None
        candidates.sort(key=lambda t: t[0])
        return candidates[0]

    def _place_entry(self, market, market_book, state: _MarketState) -> None:
        favourite = self._find_favourite(market_book)
        if favourite is None:
            return
        price, runner = favourite

        trade = Trade(market.market_id, runner.selection_id, runner.handicap, self)
        order = trade.create_order(
            side="BACK",
            order_type=LimitOrder(price, self.stake),
            notes=OrderedDict(role="entry"),
        )
        if not place_order(market, order, self.bus):
            return  # rejected — retry next tick, favourite may have changed

        state.entry_order = order
        state.favourite_selection_id = runner.selection_id
        self.bus.publish(
            StrategySignal(
                strategy=self.name,
                market_id=market.market_id,
                selection_id=runner.selection_id,
                reason=f"entry: back favourite @ {price} for {self.stake}",
                confidence=None,
            )
        )

    def _place_exit(self, market, state: _MarketState) -> None:
        entry = state.entry_order
        exit_price = price_ticks_away(entry.average_price_matched, -self.lay_ticks)

        trade = Trade(market.market_id, entry.selection_id, entry.handicap, self)
        order = trade.create_order(
            side="LAY",
            order_type=LimitOrder(exit_price, entry.size_matched),
            notes=OrderedDict(role="exit"),
        )
        if not place_order(market, order, self.bus):
            return  # rejected — retry next tick

        state.exit_order = order

        self.bus.publish(
            StrategySignal(
                strategy=self.name,
                market_id=market.market_id,
                selection_id=entry.selection_id,
                reason=f"exit: lay {entry.size_matched} @ {exit_price} (entry matched @ {entry.average_price_matched})",
                confidence=None,
            )
        )

    def _handle_at_off(self, market, market_book, state: _MarketState) -> None:
        state.at_off_handled = True
        entry = state.entry_order

        if entry is not None and entry.status == OrderStatus.EXECUTABLE:
            market.cancel_order(entry)

        matched = entry.size_matched if entry is not None else 0.0
        if matched <= 0:
            self.bus.publish(
                StrategySignal(
                    strategy=self.name,
                    market_id=market.market_id,
                    selection_id=state.favourite_selection_id,
                    reason="entry never matched — flat, nothing to close",
                    confidence=None,
                )
            )
            return

        exit_order = state.exit_order
        exit_matched = exit_order.size_matched if exit_order is not None else 0.0

        if exit_order is not None and exit_order.status == OrderStatus.EXECUTABLE:
            market.cancel_order(exit_order)

        shortfall = round(matched - exit_matched, 2)
        if shortfall <= MIN_CLOSER_SIZE:
            self.bus.publish(
                StrategySignal(
                    strategy=self.name,
                    market_id=market.market_id,
                    selection_id=state.favourite_selection_id,
                    reason="exit already covers entry — flat",
                    confidence=None,
                )
            )
            return

        favourite = next(
            (r for r in market_book.runners if r.selection_id == state.favourite_selection_id),
            None,
        )
        closing_price = self._best_back_price(favourite) if favourite else entry.average_price_matched

        trade = Trade(market.market_id, entry.selection_id, entry.handicap, self)
        closer = trade.create_order(
            side="LAY",
            order_type=LimitOrder(closing_price, shortfall),
            notes=OrderedDict(role="closer"),
        )
        if not place_order(market, closer, self.bus):
            # No retry path here — _handle_at_off is a one-shot transition
            # (at_off_handled is already True). A rejection at this point
            # would mean the flat-at-off invariant doesn't hold; that
            # should only happen if max_live_trade_count/max_order_exposure
            # are set too tight for this strategy's own 2-leg pattern —
            # which we control (see __init__) — so this is treated as an
            # edge case worth surfacing (place_order already does, via
            # OrderRejected + the ERROR heartbeat) rather than one worth
            # adding retry machinery for in a deliberately dumb baseline.
            return
        state.closer_order = closer

        self.bus.publish(
            StrategySignal(
                strategy=self.name,
                market_id=market.market_id,
                selection_id=state.favourite_selection_id,
                reason=f"closing at market: lay {shortfall} @ {closing_price} (accept the red)",
                confidence=None,
            )
        )
