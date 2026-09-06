"""Diagnostic strategy: places no orders, ever.

Exists so the sim harness, data pipeline, and bus can be validated end to
end before step 3's real BaselineFavouriteScalp strategy exists. Never
promote this to a "does something small" strategy — its entire value is
that check_market_book always returns False, so it structurally cannot
place a bet.
"""
from __future__ import annotations

from flumine.strategy.strategy import BaseStrategy


class PassiveObserver(BaseStrategy):
    def check_market_book(self, market, market_book) -> bool:
        return False
