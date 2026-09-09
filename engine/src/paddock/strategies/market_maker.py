"""LadderMarketMaker — quotes passively inside the back/lay spread and
profits from the spread + queue priority rather than taking a directional
view. This is closer to how professional Betfair traders actually
operate than either of the other two candidates, and specifically needs
the `ladder` fill model's real order-book-depth + traded-volume matching
(flumine's native SimulatedMiddleware) to mean anything — a "market
maker" backtested against `ltp_cross` (which only ever fills at-or-better
than a price that ltp has already crossed, with no queue position at all)
would just be a fake version of this strategy wearing its name. Confirmed
feasible against our data before building it: flumine's own
SimulatedOrder._process_traded implements real price-time-priority queue
simulation (a resting order only matches once *subsequently traded
volume* clears however much size was already resting ahead of it — the
standard "traded volume/2" queue-position heuristic), which needs the
Pro/Advanced-only traded-volume ladder (`trd`) this repo's Aug 2015 Pro
batch actually has. See docs/strategy-research.md for the full
feasibility note.

Candidate strategy #3 of 3 — see drift_following.py's module docstring
for the shared context this file doesn't repeat.

Design (deliberately a *simple* market maker — no inventory skewing, no
dynamic sizing; scoped this way so the backtest answers "does the basic
spread-capture idea work at all here" before anyone builds something more
elaborate on top of a negative answer):

1. Locks onto the pre-off favourite once, at the first tick inside the
   quoting window (`start_seconds_before_off`) — same "pick one runner"
   scope as the other two strategies, for comparability, not a
   fundamental limit of the approach.

2. Every `requote_interval_seconds` (real Pro data ticks every ~50ms near
   the off — requoting on every tick would be both unrealistic for any
   real venue's rate limits and prohibitively slow to backtest), checks
   the current spread in ticks (`paddock.strategies._price_utils.
   ticks_between` — Betfair's ladder is non-linear, so "spread in ticks"
   is not `lay_price - back_price`). If the spread is at least
   `min_spread_ticks`, places (or replaces, if the touch has moved) a
   passive BACK/LAY one tick inside the current touch when the spread is
   at least `min_spread_ticks` wide — a strictly passive quote, confirmed
   against flumine's SimulatedOrder.place: a BACK priced higher than the
   current available_to_back doesn't match immediately, it queues (see
   the module's feasibility note above). When the spread is only 1 tick
   — confirmed empirically to be the case ~99% of the time on the
   favourite specifically, checked against these exact 2 bundled fixtures
   before this was written this way — there's no room to improve without
   crossing, so both sides instead JOIN the touch (same price as
   whoever's already there, back of that price's queue) rather than sit
   out almost the entire market. "Only improve, never join" sounds more
   conservative but would make this strategy a near no-op on the
   runner it actually trades.

The real risk this strategy is actually testing, spelled out because it's
not obvious from the design alone: two passive quotes placed inside the
SAME snapshot's spread are, by construction, never a free lunch — your
back quote sits below your lay quote (that's what "inside the spread"
means), so a back-fill and a lay-fill priced at that same instant nets to
a small loss if the runner wins and exactly flat if it loses (confirmed
against a real run: matched-size-weighted average fill prices of 1.131
BACK vs 1.141 LAY on one bundled fixture — a consistent 1-tick giveaway,
not noise). The only way this strategy makes money is if the runner's
price moves enough, in the time between a back-side fill and a lay-side
fill, that the *actual* fill prices land the other way up (back fill
higher than lay fill) more often than not — i.e. it's a real bet that
this market has enough short-term back-and-forth movement to overcome
the spread it's giving up by quoting symmetrically, not a guaranteed
edge. That's exactly the empirical question the full 989-market backtest
answers; see docs/strategy-research.md's verdict for whether it does.

3. Whenever a quote fully matches, it's immediately replaced (checked on
   the very next un-throttled cycle) — a real market maker keeps both
   sides live continuously, it doesn't quote once and stop. Each retired
   order's `size_matched` is folded into a running per-side total before
   the reference is dropped, since a replaced order is a different
   `Order` object with its own zeroed queue position.

4. At `stop_seconds_before_off`, both sides are cancelled (whatever's
   still resting is done) and the running BACK/LAY matched totals are
   compared. If they don't net to flat — expected: nothing here
   guarantees symmetric fills, that's the actual risk a market maker
   carries — the shortfall is flattened with the same aggressive
   take-liquidity retry loop BaselineFavouriteScalp validated (walk price
   up to `slippage_ticks` times, then give up and report
   `position.unhedged`). This is a fresh, self-contained implementation
   of that pattern rather than an import from baseline.py — deliberately
   not touching that file's already-validated behaviour to add a shared
   dependency on it.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from flumine import config as flumine_config
from flumine.order.order import OrderStatus
from flumine.order.ordertype import LimitOrder
from flumine.order.trade import Trade
from flumine.strategy.strategy import BaseStrategy
from flumine.utils import price_ticks_away

from paddock.bus.bus import bus as default_bus
from paddock.bus.events import OrderSide, PositionUnhedged, StrategySignal
from paddock.sim.orders import place_order
from paddock.strategies._price_utils import best_back, best_lay, min_valid_size, ticks_between

MIN_CLOSER_SIZE = 0.01
PLACE_LATENCY_MS = flumine_config.place_latency * 1000


@dataclass
class _MarketState:
    favourite_selection_id: int | None = None
    back_order: object | None = None
    lay_order: object | None = None
    back_matched_total: float = 0.0
    lay_matched_total: float = 0.0
    last_requote_epoch: int | None = None
    flatten_started: bool = False
    flatten_target: float = 0.0
    flatten_side: str | None = None
    flatten_orders: list = field(default_factory=list)
    flatten_placed_epoch: int | None = None
    unhedged: bool = False


class LadderMarketMaker(BaseStrategy):
    def __init__(
        self,
        *args,
        start_seconds_before_off: float = 600,
        stop_seconds_before_off: float = 30,
        requote_interval_seconds: float = 5,
        min_spread_ticks: int = 2,
        quote_size: float = 2.0,
        slippage_ticks: int = 3,
        bus=None,
        **kwargs,
    ):
        # Two concurrent live orders on the same runner by design (a back
        # quote and a lay quote resting at once) — see
        # BaselineFavouriteScalp.__init__ for why this needs raising from
        # flumine's max_live_trade_count=1 default.
        kwargs.setdefault("max_live_trade_count", 2)
        super().__init__(*args, **kwargs)
        self.start_seconds_before_off = start_seconds_before_off
        self.stop_seconds_before_off = stop_seconds_before_off
        self.requote_interval_seconds = requote_interval_seconds
        self.min_spread_ticks = min_spread_ticks
        self.quote_size = quote_size
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
    def _find_runner(market_book, selection_id: int | None):
        return next((r for r in market_book.runners if r.selection_id == selection_id), None)

    def check_market_book(self, market, market_book) -> bool:
        if market_book.status != "OPEN":
            return False
        seconds_to_off = self._seconds_to_off(market, market_book)
        return seconds_to_off is not None and seconds_to_off <= self.start_seconds_before_off

    def process_market_book(self, market, market_book) -> None:
        state = self._market_state(market.market_id)
        seconds_to_off = self._seconds_to_off(market, market_book)
        if seconds_to_off is None:
            return

        if state.favourite_selection_id is None:
            self._lock_favourite(market_book, state)
            if state.favourite_selection_id is None:
                return  # no priced runner yet this tick — try again next tick

        if not state.flatten_started and seconds_to_off <= self.stop_seconds_before_off:
            self._start_flatten(market, market_book, state)
            return

        if state.flatten_started:
            if not state.unhedged:
                self._progress_flatten(market, market_book, state)
            return

        self._quote(market, market_book, state)

    def _lock_favourite(self, market_book, state: _MarketState) -> None:
        candidates = [
            (best_back(r) or r.last_price_traded, r)
            for r in market_book.runners
            if r.status == "ACTIVE"
        ]
        candidates = [(p, r) for p, r in candidates if p]
        if not candidates:
            return
        candidates.sort(key=lambda t: t[0])
        state.favourite_selection_id = candidates[0][1].selection_id

    def _retire(self, order, state: _MarketState, side: str) -> None:
        if order is None:
            return
        if side == "BACK":
            state.back_matched_total = round(state.back_matched_total + order.size_matched, 2)
        else:
            state.lay_matched_total = round(state.lay_matched_total + order.size_matched, 2)

    def _quote(self, market, market_book, state: _MarketState) -> None:
        epoch = market_book.publish_time_epoch
        if (
            state.last_requote_epoch is not None
            and epoch - state.last_requote_epoch < self.requote_interval_seconds * 1000
        ):
            return

        runner = self._find_runner(market_book, state.favourite_selection_id)
        if runner is None:
            return
        touch_back = best_back(runner)
        touch_lay = best_lay(runner)
        if not touch_back or not touch_lay:
            return
        spread_ticks = ticks_between(touch_back, touch_lay)
        if spread_ticks is None or spread_ticks < 1:
            return  # crossed/equal book — a data oddity, not a quotable state

        # Confirmed empirically (docs/strategy-research.md): on the
        # favourite specifically, the spread sits at exactly 1 tick ~99%
        # of the time — `min_spread_ticks` only gates whether we IMPROVE
        # the touch (spread wide enough to move inside without crossing
        # it); at the 1-tick floor there's no room to improve at all, so
        # the realistic move is to join the touch (same price, back of
        # that price's queue) rather than sit out almost the entire
        # market, which is what an "only improve" rule would do here.
        if spread_ticks >= self.min_spread_ticks:
            desired_back = price_ticks_away(touch_back, 1)
            desired_lay = price_ticks_away(touch_lay, -1)
        else:
            desired_back = touch_back
            desired_lay = touch_lay
        if desired_back >= desired_lay:
            return  # ladder edge case — no room left to quote safely

        requoted = False
        requoted |= self._ensure_quote(market, state, "BACK", runner, desired_back)
        requoted |= self._ensure_quote(market, state, "LAY", runner, desired_lay)
        if requoted:
            state.last_requote_epoch = epoch

    def _ensure_quote(self, market, state: _MarketState, side: str, runner, desired_price: float) -> bool:
        current = state.back_order if side == "BACK" else state.lay_order

        if current is not None:
            if current.status == OrderStatus.EXECUTION_COMPLETE:
                self._retire(current, state, side)
                current = None
            elif current.status == OrderStatus.EXECUTABLE:
                if current.order_type.price == desired_price:
                    return False  # already quoting at the right level
                market.cancel_order(current)
                self._retire(current, state, side)
                current = None
            else:
                return False  # cancelling/expired/violation — wait for it to resolve

        # BACK and LAY quotes are deliberately the SAME stake
        # (quote_size), not risk-matched by liability — the flatten logic
        # below needs back_matched_total == lay_matched_total (equal
        # STAKE, not equal liability) to mean "flat", since that's the
        # actual condition for a guaranteed-neutral settlement (see the
        # module docstring's profit derivation). Risk-matching the LAY
        # leg by liability instead would break that invariant by design,
        # not fix anything.
        trade = Trade(market.market_id, runner.selection_id, runner.handicap, self)
        order = trade.create_order(
            side=side,
            order_type=LimitOrder(desired_price, self.quote_size),
            notes=OrderedDict(role="mm_back" if side == "BACK" else "mm_lay"),
        )
        if not place_order(market, order, self.bus):
            if side == "BACK":
                state.back_order = None
            else:
                state.lay_order = None
            return False

        if side == "BACK":
            state.back_order = order
        else:
            state.lay_order = order

        self.bus.publish(
            StrategySignal(
                strategy=self.name,
                market_id=market.market_id,
                selection_id=runner.selection_id,
                reason=f"quote {side} {self.quote_size} @ {desired_price}",
                confidence=None,
            )
        )
        return True

    def _start_flatten(self, market, market_book, state: _MarketState) -> None:
        state.flatten_started = True
        for side, order in (("BACK", state.back_order), ("LAY", state.lay_order)):
            if order is not None and order.status == OrderStatus.EXECUTABLE:
                market.cancel_order(order)
            self._retire(order, state, side)
        state.back_order = None
        state.lay_order = None

        net = round(state.back_matched_total - state.lay_matched_total, 2)
        if abs(net) <= MIN_CLOSER_SIZE:
            self.bus.publish(
                StrategySignal(
                    strategy=self.name,
                    market_id=market.market_id,
                    selection_id=state.favourite_selection_id,
                    reason=f"flat at stop: back={state.back_matched_total} lay={state.lay_matched_total}",
                    confidence=None,
                )
            )
            return

        # net > 0: matched more BACK than LAY -> excess long -> LAY to flatten.
        # net < 0: matched more LAY than BACK -> excess short -> BACK to flatten.
        state.flatten_side = "LAY" if net > 0 else "BACK"
        state.flatten_target = abs(net)
        self._place_flatten_attempt(market, market_book, state, state.flatten_target)

    def _flatten_matched(self, state: _MarketState) -> float:
        return round(sum(o.size_matched for o in state.flatten_orders), 2)

    def _place_flatten_attempt(self, market, market_book, state: _MarketState, size: float) -> None:
        attempt = len(state.flatten_orders)
        runner = self._find_runner(market_book, state.favourite_selection_id)
        if runner is None:
            return
        if state.flatten_side == "LAY":
            base_price = best_lay(runner)
            price = price_ticks_away(base_price, -attempt) if attempt and base_price else base_price
        else:
            base_price = best_back(runner)
            price = price_ticks_away(base_price, attempt) if attempt and base_price else base_price
        if base_price is None:
            return  # no price to work with this tick — try again next tick

        # A small leftover imbalance (e.g. one side's quote partially
        # filled a fraction of a pound more than the other) can be below
        # the exchange's own minimum bet size/payout at this price — see
        # paddock.strategies._price_utils.min_valid_size. Rounding the
        # flatten size UP to clear that floor means occasionally
        # over-correcting the residual by a few pence, which is the
        # actually-available real-world choice here, not a shortcut.
        size = max(size, min_valid_size(price))

        trade = Trade(market.market_id, runner.selection_id, runner.handicap, self)
        order = trade.create_order(
            side=state.flatten_side,
            order_type=LimitOrder(price, size),
            notes=OrderedDict(role="mm_flatten", attempt=attempt),
        )
        if not place_order(market, order, self.bus):
            return

        state.flatten_orders.append(order)
        state.flatten_placed_epoch = market_book.publish_time_epoch
        self.bus.publish(
            StrategySignal(
                strategy=self.name,
                market_id=market.market_id,
                selection_id=runner.selection_id,
                reason=f"flatten attempt {attempt}: {state.flatten_side} {size} @ {price}",
                confidence=None,
            )
        )

    def _progress_flatten(self, market, market_book, state: _MarketState) -> None:
        remaining = round(state.flatten_target - self._flatten_matched(state), 2)
        if remaining <= MIN_CLOSER_SIZE:
            return

        current = state.flatten_orders[-1] if state.flatten_orders else None
        if current is None:
            self._place_flatten_attempt(market, market_book, state, remaining)
            return
        if current.status != OrderStatus.EXECUTABLE:
            return

        ready_at = state.flatten_placed_epoch + PLACE_LATENCY_MS
        if market_book.publish_time_epoch < ready_at:
            return

        remaining = round(state.flatten_target - self._flatten_matched(state), 2)
        if remaining <= MIN_CLOSER_SIZE:
            return

        attempt = len(state.flatten_orders) - 1
        market.cancel_order(current)

        if attempt >= self.slippage_ticks:
            self._give_up_flatten(market, state, remaining)
            return

        self._place_flatten_attempt(market, market_book, state, remaining)

    def _give_up_flatten(self, market, state: _MarketState, remaining: float) -> None:
        state.unhedged = True
        reason = (
            f"flatten unmatched after {self.slippage_ticks} slippage attempts — "
            f"{remaining} left naked"
        )
        self.bus.publish(
            PositionUnhedged(
                strategy=self.name,
                market_id=market.market_id,
                selection_id=state.favourite_selection_id,
                side=OrderSide.LAY if state.flatten_side == "LAY" else OrderSide.BACK,
                remaining_size=remaining,
                attempts=self.slippage_ticks,
                reason=reason,
            )
        )
