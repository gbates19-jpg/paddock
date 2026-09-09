"""DriftSteamFollower — trades with the direction of meaningful late price
movement ("steam"/"drift"), one of the most-replicated documented effects
in horse racing markets: late money is disproportionately informed, so a
runner that shortens hard in the last few minutes tends to still be
under-priced relative to that new information, and one that drifts out
hard tends to still be over-priced.

Candidate strategy #1 of 3 built to test whether a real, documented edge
survives contact with our actual data — see docs/strategy-research.md for
the full comparison and verdict. Unlike BaselineFavouriteScalp (a
deliberate pipeline-proving stub, not a real strategy), this one embodies
an actual economic hypothesis and is meant to be judged on its backtest.

"Meaningful" is defined relative to each runner's OWN recent price
volatility, not a fixed tick count — the brief was explicit that a magic
number here would be indefensible, and it's also the right call
statistically: a favourite trading in the 1.01-3.0 range and a 50+
outsider have wildly different typical price ranges, so the same absolute
move means very different things for each (confirmed empirically — see
the calibration note below).

Design:

1. From `lookback_seconds` + `decision_seconds_before_off` before the off,
   record each ACTIVE runner's best-available-to-back price (falling back
   to last_price_traded when the book's empty — same fallback
   BaselineFavouriteScalp uses, for the same reason: this strategy doesn't
   know or care which fill_model produced the price). Resampled at most
   once per `resample_seconds` per runner (real Pro data ticks every
   ~50ms near the off; recording every tick would make the rolling-vol
   window mostly noise from bid/ask bounce rather than real price
   movement, and there's no reason to hold thousands of samples per
   runner in memory for an 8-minute window).

2. At `decision_seconds_before_off` (a single one-shot check per market,
   `_MarketState.decided`): for every runner with at least `min_samples`
   resampled prices spanning back close to `lookback_seconds`, compute

       cumulative_move = log(price_now) - log(price_oldest_in_window)
       step_stdev      = stdev(consecutive log-price differences)
       z = cumulative_move / (step_stdev * sqrt(n_steps))

   — a random-walk-scaled z-score: dividing the whole-window move by
   `step_stdev * sqrt(n_steps)` (rather than just `step_stdev`) accounts
   for the fact that a random walk's cumulative displacement grows with
   sqrt(steps) even with zero drift, so a longer or choppier window
   doesn't mechanically inflate the score. This makes the score
   comparable in principle across runners with very different price
   levels and volatility — a runner needs a move that's genuinely large
   *for it*, not just a large number of ticks.

3. Trade the single runner with the largest |z| that clears
   `z_threshold`, if any — one signal per market, direction from the
   sign: shortened (z < 0) => BACK; drifted out (z > 0) => LAY. Sized to
   `target_exposure` either way (BACK: stake = target_exposure; LAY: size
   = target_exposure / (price - 1), so liability is the same
   target_exposure regardless of which side fires — otherwise a handful
   of LAY signals on long-priced drifters would dominate the whole
   book's risk). Placed as an aggressive (liquidity-taking) order at the
   current best price — this is a one-shot directional bet, not a
   resting quote hoping to get a better fill; if it's still unmatched by
   `cancel_seconds_before_off`, the remainder is cancelled rather than
   left to lapse into an undefined in-play state.

4. No exit, no hedge — deliberately different from
   BaselineFavouriteScalp. This strategy is a directional bet held to
   settlement, not a scalp; there is nothing to flatten, and doing so
   would just be re-implementing BaselineFavouriteScalp's exit on top of
   a different entry signal.

Calibration note (see docs/strategy-research.md for the full writeup):
checked against a 250-market sample before picking the numbers above —
median |log-price move| over an 8-minute pre-off window was ~0.11 (a
~12% relative price change), confirming an 8-minute lookback captures
real, not negligible, movement. That same sample also showed the
strongest single decile-level t-stat (-2.31) on the "big drift-out"
side, not the "big shorten" side — but decile-level price averages in
that sample were heavily confounded with the *favourite-longshot bias*
strategy's own effect (the biggest-drift-out decile was also, on average,
the highest-priced decile), so this file does NOT hard-code "only trade
drift-outs" — that would be baking a small, confounded sample's noise
into the strategy rather than testing the symmetric hypothesis the
literature actually makes. The full 989-market backtest (same data, same
harness, ladder fill model) is the real test of both directions; see the
results table for which one (if either) actually held up.
"""
from __future__ import annotations

import math
import statistics
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from flumine.order.order import OrderStatus
from flumine.order.ordertype import LimitOrder
from flumine.order.trade import Trade
from flumine.strategy.strategy import BaseStrategy

from paddock.bus.bus import bus as default_bus
from paddock.bus.events import StrategySignal
from paddock.sim.orders import place_order
from paddock.strategies._price_utils import best_back, best_lay, min_valid_size

MIN_STEP_STDEV = 1e-9  # guards against a division by ~zero on a dead-flat window


@dataclass
class _RunnerHistory:
    samples: deque = field(default_factory=lambda: deque())  # [(epoch_ms, log_price)]
    last_sample_epoch: int | None = None


@dataclass
class _MarketState:
    histories: dict[int, _RunnerHistory] = field(default_factory=dict)
    decided: bool = False
    order: object | None = None


class DriftSteamFollower(BaseStrategy):
    def __init__(
        self,
        *args,
        lookback_seconds: float = 480,
        resample_seconds: float = 20,
        min_samples: int = 4,
        decision_seconds_before_off: float = 120,
        cancel_seconds_before_off: float = 15,
        z_threshold: float = 1.0,
        target_exposure: float = 2.0,
        bus=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.lookback_seconds = lookback_seconds
        self.resample_seconds = resample_seconds
        self.min_samples = min_samples
        self.decision_seconds_before_off = decision_seconds_before_off
        self.cancel_seconds_before_off = cancel_seconds_before_off
        self.z_threshold = z_threshold
        self.target_exposure = target_exposure
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
        if seconds_to_off is None:
            return False
        return seconds_to_off <= (self.lookback_seconds + self.decision_seconds_before_off)

    def process_market_book(self, market, market_book) -> None:
        state = self._market_state(market.market_id)
        seconds_to_off = self._seconds_to_off(market, market_book)
        if seconds_to_off is None:
            return

        if not state.decided:
            self._record_samples(market_book, state, market_book.publish_time_epoch)

        if not state.decided and seconds_to_off <= self.decision_seconds_before_off:
            state.decided = True
            self._make_decision(market, market_book, state)
            return

        if (
            state.decided
            and state.order is not None
            and state.order.status == OrderStatus.EXECUTABLE
            and seconds_to_off <= self.cancel_seconds_before_off
        ):
            market.cancel_order(state.order)

    def _record_samples(self, market_book, state: _MarketState, epoch_ms: int) -> None:
        for runner in market_book.runners:
            if runner.status != "ACTIVE":
                continue
            price = best_back(runner) or runner.last_price_traded
            if not price:
                continue
            history = state.histories.setdefault(runner.selection_id, _RunnerHistory())
            if (
                history.last_sample_epoch is not None
                and epoch_ms - history.last_sample_epoch < self.resample_seconds * 1000
            ):
                continue
            history.samples.append((epoch_ms, math.log(price)))
            history.last_sample_epoch = epoch_ms
            cutoff = epoch_ms - self.lookback_seconds * 1000
            while history.samples and history.samples[0][0] < cutoff:
                history.samples.popleft()

    def _score(self, history: _RunnerHistory) -> float | None:
        samples = list(history.samples)
        if len(samples) < self.min_samples:
            return None
        log_prices = [p for _, p in samples]
        diffs = [b - a for a, b in zip(log_prices, log_prices[1:])]
        if len(diffs) < 2:
            return None
        step_stdev = statistics.stdev(diffs)
        if step_stdev < MIN_STEP_STDEV:
            return None
        cumulative_move = log_prices[-1] - log_prices[0]
        expected_scale = step_stdev * math.sqrt(len(diffs))
        if expected_scale < MIN_STEP_STDEV:
            return None
        return cumulative_move / expected_scale

    def _make_decision(self, market, market_book, state: _MarketState) -> None:
        best_selection_id = None
        best_z = 0.0
        for selection_id, history in state.histories.items():
            z = self._score(history)
            if z is None:
                continue
            if abs(z) > abs(best_z):
                best_z = z
                best_selection_id = selection_id

        if best_selection_id is None or abs(best_z) < self.z_threshold:
            self.bus.publish(
                StrategySignal(
                    strategy=self.name,
                    market_id=market.market_id,
                    selection_id=best_selection_id or 0,
                    reason=f"no runner cleared z_threshold={self.z_threshold} (best |z|={abs(best_z):.2f})",
                    confidence=None,
                )
            )
            return

        runner = next(
            (r for r in market_book.runners if r.selection_id == best_selection_id), None
        )
        if runner is None:
            return

        if best_z < 0:
            side = "BACK"
            price = best_back(runner) or runner.last_price_traded
            size = self.target_exposure
        else:
            side = "LAY"
            price = best_lay(runner) or runner.last_price_traded
            if price is None or price <= 1.0:
                size = None
            else:
                size = max(round(self.target_exposure / (price - 1.0), 2), min_valid_size(price))

        if not price or not size:
            return

        trade = Trade(market.market_id, runner.selection_id, runner.handicap, self)
        order = trade.create_order(
            side=side,
            order_type=LimitOrder(price, size),
            notes=OrderedDict(role="drift_entry"),
        )
        if not place_order(market, order, self.bus):
            return

        state.order = order
        self.bus.publish(
            StrategySignal(
                strategy=self.name,
                market_id=market.market_id,
                selection_id=runner.selection_id,
                reason=f"{side} {size} @ {price} (z={best_z:.2f}, "
                f"{'shortened' if best_z < 0 else 'drifted'})",
                confidence=min(abs(best_z) / (self.z_threshold * 3), 1.0),
            )
        )
