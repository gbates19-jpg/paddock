"""FavouriteLongshotBias — lays runners priced above a threshold, testing
the classic "favourite-longshot bias": in fixed-odds markets, long shots
are systematically overbet (their true win probability is lower than
their price implies) and short favourites systematically underbet. It's
one of the most replicated findings in the whole betting-markets
literature — but almost all of that literature is on fixed-odds
bookmaker prices, where a built-in overround guarantees the bookmaker
some margin regardless. An exchange's Best Starting Price (BSP) has no
such guarantee (it's a real two-sided auction), so whether the bias
survives there — and at what price range — is a real empirical question
for *this* market, not something to assume. See
docs/strategy-research.md for the check this file's design is actually
based on.

Candidate strategy #2 of 3 — see drift_following.py's module docstring
for the shared context (why these exist, how they're evaluated,
BaselineFavouriteScalp's result standing untouched alongside them).

What the pre-check (docs/strategy-research.md) found, using each of the
989 markets' own settled BSP + result — the real, final, market-clearing
price and outcome, not our own execution: bucketing all ~8,400
individual runner results by BSP and computing the LAY side's naive P&L
per unit stake (no commission, no execution cost) gives a **directionally
literature-consistent but NOT statistically significant** picture across
the board (every bucket's |t| stayed under 1.4) — the one exception in
magnitude was the most extreme bucket (BSP >= 50), where laying showed
the largest positive mean of any bucket (t=+1.31 — still short of
conventional significance, but the strongest signal available, and in
the expected direction). Short favourites (BSP < 2.0) showed the
*opposite* of the classic prediction in this sample (backing them lost
money, weakly) — so this file deliberately does NOT add a
"back the favourite" leg; that would be baking in the textbook
assumption over what our own data actually showed. This strategy tests
one side only: laying above `lay_price_threshold` (default 50, chosen to
match where the pre-check's signal actually concentrated, not the
broader/weaker bucket boundaries).

Design: at a single decision point (`entry_seconds_before_off`) per
market, every ACTIVE runner whose best-available-to-lay price (falling
back to last_price_traded, same convention as the other strategies) is
>= `lay_price_threshold` gets an aggressive LAY placed at that price —
unlike the other two strategies, potentially several per market (a
big-field race can easily have 3-4 qualifying outsiders), since the
hypothesis under test is about the *class* of longshots, not a single
pick. Sized to a fixed `target_liability` regardless of price — laying a
1000-priced runner and a 55-priced one at the same STAKE would leave
wildly different worst-case losses, so stake is derived
(`target_liability / (price - 1)`) to keep risk comparable across the
whole price range this strategy plays in. No exit, no hedge — "lay it and
let it run to settlement" is the entire system being tested, same as the
real-world version of this strategy; adding an active close would just
be testing a different, made-up strategy.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from flumine.order.order import OrderStatus
from flumine.order.ordertype import LimitOrder
from flumine.order.trade import Trade
from flumine.strategy.strategy import BaseStrategy

from paddock.bus.bus import bus as default_bus
from paddock.bus.events import StrategySignal
from paddock.sim.orders import place_order
from paddock.strategies._price_utils import best_lay, min_valid_size

MIN_LAY_PRICE_FOR_LIABILITY_SIZING = 1.02  # avoids a div-by-~0 blow-up in size


@dataclass
class _MarketState:
    decided: bool = False
    orders: list = field(default_factory=list)


class FavouriteLongshotBias(BaseStrategy):
    def __init__(
        self,
        *args,
        lay_price_threshold: float = 50.0,
        entry_seconds_before_off: float = 180,
        cancel_seconds_before_off: float = 15,
        target_liability: float = 2.0,
        bus=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.lay_price_threshold = lay_price_threshold
        self.entry_seconds_before_off = entry_seconds_before_off
        self.cancel_seconds_before_off = cancel_seconds_before_off
        self.target_liability = target_liability
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

    def check_market_book(self, market, market_book) -> bool:
        if market_book.status != "OPEN":
            return False
        seconds_to_off = self._seconds_to_off(market, market_book)
        return seconds_to_off is not None and seconds_to_off <= self.entry_seconds_before_off

    def process_market_book(self, market, market_book) -> None:
        state = self._market_state(market.market_id)
        seconds_to_off = self._seconds_to_off(market, market_book)
        if seconds_to_off is None:
            return

        if not state.decided:
            state.decided = True
            self._lay_the_longshots(market, market_book, state)
            return

        if seconds_to_off <= self.cancel_seconds_before_off:
            for order in state.orders:
                if order.status == OrderStatus.EXECUTABLE:
                    market.cancel_order(order)

    def _lay_the_longshots(self, market, market_book, state: _MarketState) -> None:
        for runner in market_book.runners:
            if runner.status != "ACTIVE":
                continue
            price = best_lay(runner) or runner.last_price_traded
            if not price or price < self.lay_price_threshold:
                continue

            size_price = max(price, MIN_LAY_PRICE_FOR_LIABILITY_SIZING)
            size = round(self.target_liability / (size_price - 1.0), 2)
            size = max(size, min_valid_size(price))
            if size <= 0:
                continue

            trade = Trade(market.market_id, runner.selection_id, runner.handicap, self)
            order = trade.create_order(
                side="LAY",
                order_type=LimitOrder(price, size),
                notes=OrderedDict(role="flb_lay"),
            )
            if not place_order(market, order, self.bus):
                continue

            state.orders.append(order)
            self.bus.publish(
                StrategySignal(
                    strategy=self.name,
                    market_id=market.market_id,
                    selection_id=runner.selection_id,
                    reason=f"lay {size} @ {price} (>= threshold {self.lay_price_threshold})",
                    confidence=None,
                )
            )
