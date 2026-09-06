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
          any) and start the CLOSER retry loop for the uncovered amount
          (see below).
  4. Closer retry loop — "take liquidity, don't rest" (revised again after
     real-data validation showed a resting closer can fail to match under
     fill_model=ladder if nothing actually trades at that price before the
     market shuts): each attempt places an aggressive LAY at the CURRENT
     best available_to_lay price (the price actually on offer right now,
     not a passive level we hope gets traded through), sized to whatever
     of the target is still unmatched. If still unmatched after one full
     tick of the stream, cancel and re-place one tick worse (lower, for a
     LAY) — up to `slippage_ticks` (config, default 3) times. If the last
     attempt is still unmatched after its own tick, give up: log ERROR and
     publish `position.unhedged` — a real, naked position is left open,
     reported loudly rather than silently accepted or retried forever.
  5. This guarantees zero net position on the runner by market close in
     every reachable scenario *the retry loop actually resolves*: entry
     never matched (no exit ever placed); entry+exit both fully matched
     (flat by construction); entry matched, exit under-filled (closer
     loop tops up the shortfall, walking price if needed). It does NOT
     guarantee flat if fill_model=ladder and there's genuinely no
     liquidity to take within the slippage tolerance — that's
     `position.unhedged`, a real outcome, not a bug. See
     tests/test_baseline_flat_invariant.py for the resolvable scenarios
     (synthetic market data, exact ltp control) and
     tests/test_baseline_ladder_flat_invariant.py for the same check
     against the real Aug 2015 Pro fixture.

Closer timing is a state machine, not a sleep: place/cancel execute
synchronously inside the process_market_book callback that calls them, but
simulated MATCHING only happens later, inside SimulatedMiddleware, on a
later tick — and only once market-time has advanced at least
config.place_latency (120ms) past the order's placement. Nothing can
settle inside the same callback that placed the order, so blocking with
time.sleep() there is a no-op by construction (tried it, confirmed it does
nothing useful, removed it). The correct design re-checks each closer
attempt on a LATER call to process_market_book, gated on market time
(market_book.publish_time_epoch), not tick count — Pro data ticks every
~50ms so the first re-check lands ~3 ticks after placement; Advanced data
ticks roughly every second so it's the very next tick either way. See
_progress_closer.

Fill-model-agnostic, and the "best available" assumption under ltp_cross:
_best_back_price / _best_lay_price read runner.ex.available_to_back/lay
(fill_model=ladder / Advanced+Pro data) and fall back to
runner.last_price_traded when that's empty (fill_model=ltp_cross / Basic
Plan data, which carries no order book at all). That fallback is a real
assumption, not a neutral default: on Basic data we have no way to know
what price is actually available to trade at right now, so we approximate
it as "the last price this selection actually traded at" — reasonable in
a liquid, actively-traded market close to the off, optimistic (and
potentially stale) right after a market opens or during a quiet patch
with no recent trades. The strategy itself doesn't know or care which
fill_model produced the price it's looking at — that split is enforced by
the engine (paddock.sim.harness/fill_models), not here.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field

from flumine import config as flumine_config
from flumine.order.order import OrderStatus
from flumine.order.ordertype import LimitOrder
from flumine.order.trade import Trade
from flumine.strategy.strategy import BaseStrategy
from flumine.utils import get_price, price_ticks_away

from paddock.bus.bus import bus as default_bus
from paddock.bus.events import OrderSide, PositionUnhedged, StrategySignal
from paddock.sim.orders import place_order

logger = logging.getLogger(__name__)

MIN_CLOSER_SIZE = 0.01  # below this, floating point noise, not a real shortfall

# Mirrors flumine's own config.place_latency (0.12s) — a closer attempt
# can't possibly have matched before this much MARKET time has passed
# since it was placed, so there's no point re-checking any sooner.
PLACE_LATENCY_MS = flumine_config.place_latency * 1000


@dataclass
class _MarketState:
    favourite_selection_id: int | None = None
    entry_order: object | None = None
    exit_order: object | None = None
    at_off_handled: bool = False
    closer_target: float = 0.0
    closer_orders: list = field(default_factory=list)
    closer_placed_epoch: int | None = None
    unhedged: bool = False


class BaselineFavouriteScalp(BaseStrategy):
    def __init__(
        self,
        *args,
        stake: float = 2.0,
        place_seconds_before_off: float = 300,
        cancel_seconds_before_off: float = 30,
        lay_ticks: int = 2,
        slippage_ticks: int = 3,
        bus=None,
        **kwargs,
    ):
        # Entry and exit (and closer retries) are separate Trade objects on
        # the same runner, and can be concurrently live (e.g. entry's
        # unmatched remainder still resting while exit is live against the
        # matched portion) — flumine's BaseStrategy default
        # (max_live_trade_count=1) rejects the second leg as a
        # STRATEGY_EXPOSURE violation with no exception raised, just a
        # silently voided order (see
        # tests/test_order_rejection.py::test_order_rejected_event_fires_on_
        # max_live_trade_count_violation for what that looks like and how
        # it's now surfaced instead of silently swallowed).
        kwargs.setdefault("max_live_trade_count", 2)
        super().__init__(*args, **kwargs)
        self.stake = stake
        self.place_seconds_before_off = place_seconds_before_off
        self.cancel_seconds_before_off = cancel_seconds_before_off
        self.lay_ticks = lay_ticks
        self.slippage_ticks = slippage_ticks
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

    @staticmethod
    def _best_lay_price(runner) -> float | None:
        # The closer takes liquidity on the LAY side (this strategy's
        # entry is always BACK) — the price actually on offer right now,
        # not a level we hope gets traded through. See module docstring.
        price = get_price(runner.ex.available_to_lay, 0)
        return price if price else runner.last_price_traded

    @staticmethod
    def _find_runner(market_book, selection_id: int | None):
        return next(
            (r for r in market_book.runners if r.selection_id == selection_id), None
        )

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
        elif state.at_off_handled and not state.unhedged and state.closer_target > 0:
            self._progress_closer(market, market_book, state)

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

        state.closer_target = shortfall
        self._place_closer_attempt(market, market_book, state, shortfall)

    def _closer_matched(self, state: _MarketState) -> float:
        return round(sum(o.size_matched for o in state.closer_orders), 2)

    def _place_closer_attempt(self, market, market_book, state: _MarketState, size: float) -> None:
        attempt = len(state.closer_orders)
        favourite = self._find_runner(market_book, state.favourite_selection_id)
        base_price = self._best_lay_price(favourite) if favourite else None
        if base_price is None:
            return  # no price to work with this tick — try again next tick

        # "worse" for a LAY closer means lower (more generous to the
        # counterparty, more likely to actually match) — taking liquidity
        # at attempt 0, walking down the ladder on each retry.
        price = price_ticks_away(base_price, -attempt) if attempt else base_price

        trade = Trade(market.market_id, state.favourite_selection_id, favourite.handicap, self)
        order = trade.create_order(
            side="LAY",
            order_type=LimitOrder(price, size),
            notes=OrderedDict(role="closer", attempt=attempt),
        )
        if not place_order(market, order, self.bus):
            return  # rejected — _progress_closer will try again next tick

        state.closer_orders.append(order)
        state.closer_placed_epoch = market_book.publish_time_epoch

        self.bus.publish(
            StrategySignal(
                strategy=self.name,
                market_id=market.market_id,
                selection_id=state.favourite_selection_id,
                reason=f"closer attempt {attempt}: lay {size} @ {price} (taking liquidity)",
                confidence=None,
            )
        )

    def _progress_closer(self, market, market_book, state: _MarketState) -> None:
        remaining = round(state.closer_target - self._closer_matched(state), 2)
        if remaining <= MIN_CLOSER_SIZE:
            return  # fully closed — nothing more to do

        current = state.closer_orders[-1] if state.closer_orders else None

        if current is None:
            # first attempt was rejected outright — retry at the same
            # (attempt 0) price every tick until it's accepted
            self._place_closer_attempt(market, market_book, state, remaining)
            return

        if current.status != OrderStatus.EXECUTABLE:
            return  # already resolved (matched or cancelled) — handled elsewhere

        # Time-based, not tick-count-based: simulated matching can't
        # possibly have happened before market-time has advanced
        # PLACE_LATENCY_MS past placement (flumine's own simulated
        # latency floor), regardless of how many ticks that takes — ~3
        # ticks on ~50ms Pro data, the very next tick on ~1s Advanced data.
        ready_at = state.closer_placed_epoch + PLACE_LATENCY_MS
        if market_book.publish_time_epoch < ready_at:
            return  # not enough market time has passed to re-check yet

        # enough time has passed and it's still unmatched (or only
        # partially) — recompute remaining first, a fill can land in the
        # same instant as the tick that triggers this check
        remaining = round(state.closer_target - self._closer_matched(state), 2)
        if remaining <= MIN_CLOSER_SIZE:
            return

        attempt = len(state.closer_orders) - 1
        market.cancel_order(current)

        if attempt >= self.slippage_ticks:
            self._give_up_closing(market, state, remaining)
            return

        self._place_closer_attempt(market, market_book, state, remaining)

    def _give_up_closing(self, market, state: _MarketState, remaining: float) -> None:
        state.unhedged = True
        reason = (
            f"closer unmatched after {self.slippage_ticks} slippage attempts — "
            f"{remaining} left naked"
        )
        logger.error(
            "Position unhedged: market=%s selection=%s remaining=%s attempts=%s",
            market.market_id,
            state.favourite_selection_id,
            remaining,
            self.slippage_ticks,
        )
        self.bus.publish(
            PositionUnhedged(
                strategy=self.name,
                market_id=market.market_id,
                selection_id=state.favourite_selection_id,
                side=OrderSide.LAY,
                remaining_size=remaining,
                attempts=self.slippage_ticks,
                reason=reason,
            )
        )
