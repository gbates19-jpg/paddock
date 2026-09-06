"""BaselineFavouriteScalp — deliberately dumb, proves the pipeline end to
end rather than making money (see the Phase 0 brief).

Rules:
  1. From `place_seconds_before_off` before the off: identify the
     favourite (lowest available price) and back it at that price for
     `stake`, then place a lay `lay_ticks` ticks lower for the same stake.
     Once per market.
  2. From `cancel_seconds_before_off` before the off: cancel either leg
     that's still unmatched.
  3. If both legs end up fully matched: this is already risk-free (equal
     stake, lay price < back price -> win pays S*(Pb-Pl), lose nets 0), so
     "green up" here is just detecting and announcing that state, not
     placing a third order — a true generalised green (equal profit
     across every outcome) is more machinery than a deliberately dumb
     baseline needs.

Fill-model-agnostic (the point of this file, per the Basic Plan decision):
"best available" is read via runner.ex.available_to_back/lay when present
(fill_model=ladder / rich data) and falls back to runner.last_price_traded
when the ladder is empty (fill_model=ltp_cross / Basic Plan data) — see
_best_back_price/_best_lay_price. The strategy itself never checks which
fill_model is active; it just reacts to whatever the market_book actually
contains, which has the same shape either way. The *engine* (paddock.sim.
harness/fill_models) is what enforces the ladder/ltp_cross split — this
strategy is deliberately unaware of it.
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

logger = logging.getLogger(__name__)


@dataclass
class _MarketState:
    favourite_selection_id: int | None = None
    back_order: object | None = None
    lay_order: object | None = None
    cancelled: bool = False
    greened: bool = False
    placed: bool = False


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
        # Two concurrent live trades per runner by design (back leg + lay
        # leg) — flumine's BaseStrategy default (max_live_trade_count=1)
        # would reject the second leg as a STRATEGY_EXPOSURE violation.
        # Confirmed the hard way: it silently voided the lay order and the
        # backtest looked like it placed nothing.
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

        if not state.placed:
            self._place_initial_scalp(market, market_book, state)

        if not state.cancelled and seconds_to_off <= self.cancel_seconds_before_off:
            self._cancel_unmatched(market, state)

        if not state.greened:
            self._check_greened(market, state)

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

    def _place_initial_scalp(self, market, market_book, state: _MarketState) -> None:
        favourite = self._find_favourite(market_book)
        if favourite is None:
            return
        back_price, runner = favourite
        lay_price = price_ticks_away(back_price, -self.lay_ticks)

        back_trade = Trade(market.market_id, runner.selection_id, runner.handicap, self)
        back_order = back_trade.create_order(
            side="BACK",
            order_type=LimitOrder(back_price, self.stake),
            notes=OrderedDict(role="scalp_back"),
        )
        market.place_order(back_order)

        lay_trade = Trade(market.market_id, runner.selection_id, runner.handicap, self)
        lay_order = lay_trade.create_order(
            side="LAY",
            order_type=LimitOrder(lay_price, self.stake),
            notes=OrderedDict(role="scalp_lay"),
        )
        market.place_order(lay_order)

        state.placed = True
        state.favourite_selection_id = runner.selection_id
        state.back_order = back_order
        state.lay_order = lay_order

        self.bus.publish(
            StrategySignal(
                strategy=self.name,
                market_id=market.market_id,
                selection_id=runner.selection_id,
                reason=f"backed favourite @ {back_price}, laid @ {lay_price}",
                confidence=None,
            )
        )

    def _cancel_unmatched(self, market, state: _MarketState) -> None:
        for order in (state.back_order, state.lay_order):
            if order is not None and order.status == OrderStatus.EXECUTABLE:
                market.cancel_order(order)
        state.cancelled = True

    def _check_greened(self, market, state: _MarketState) -> None:
        back, lay = state.back_order, state.lay_order
        if back is None or lay is None:
            return
        both_matched = (
            back.status == OrderStatus.EXECUTION_COMPLETE
            and back.size_matched > 0
            and lay.status == OrderStatus.EXECUTION_COMPLETE
            and lay.size_matched > 0
        )
        if both_matched:
            state.greened = True
            self.bus.publish(
                StrategySignal(
                    strategy=self.name,
                    market_id=market.market_id,
                    selection_id=state.favourite_selection_id,
                    reason="both legs matched — risk-free position (win pays, lose nets 0)",
                    confidence=None,
                )
            )
