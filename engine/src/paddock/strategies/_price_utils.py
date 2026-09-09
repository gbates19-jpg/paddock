"""Shared read-only price helpers for the research strategies
(drift_following, favourite_longshot_bias, market_maker) — not used by
BaselineFavouriteScalp, which stays exactly as it was validated.

Betfair's price ladder is non-linear (0.01 steps near 1.01, widening to 10
near 1000) — "one tick" is not a fixed price delta, so tick-distance and
spread-width both need the real ladder (flumine.utils.PRICES_FLOAT), not
arithmetic on the price floats themselves.
"""
from __future__ import annotations

import math

from flumine.utils import PRICES_FLOAT, get_price

# GBP account minimums (betfairlightweight.metadata.currency_parameters,
# also what paddock.sim.clients.build_replay_client's SimulatedClient
# reports) — a LIMIT order is only valid if size >= MIN_BET_SIZE **or**
# price*size >= MIN_BET_PAYOUT (flumine's OrderValidation._validate_
# betfair_min_size). At high odds, 10/price undercuts the flat £1 floor —
# confirmed the hard way: a liability-sized LAY on a 100+ runner
# (£2 liability / 99 ≈ £0.02 stake) gets rejected outright by this rule,
# not filled small. Every strategy that derives size from a target
# liability (rather than using a fixed stake already >= £1) needs this.
MIN_BET_SIZE = 1.0
MIN_BET_PAYOUT = 10.0


def ticks_between(price_a: float, price_b: float) -> int | None:
    """Signed tick distance from price_a to price_b (positive if b is
    further from 1.01 than a). None if either price isn't on the ladder
    (shouldn't happen for exchange-sourced prices, but a bad tick shouldn't
    crash the strategy over it)."""
    try:
        return PRICES_FLOAT.index(price_b) - PRICES_FLOAT.index(price_a)
    except ValueError:
        return None


def log_price(price: float) -> float:
    return math.log(price)


def best_back(runner) -> float | None:
    return get_price(runner.ex.available_to_back, 0)


def best_lay(runner) -> float | None:
    return get_price(runner.ex.available_to_lay, 0)


def min_valid_size(price: float) -> float:
    """Smallest stake that clears flumine's OrderValidation at this price
    (see MIN_BET_SIZE/MIN_BET_PAYOUT above) — round UP (not to-nearest) so
    a boundary case can't land 1 penny under the payout floor."""
    if price <= 0:
        return MIN_BET_SIZE
    payout_floor = math.ceil((MIN_BET_PAYOUT / price) * 100) / 100
    return min(MIN_BET_SIZE, payout_floor)
