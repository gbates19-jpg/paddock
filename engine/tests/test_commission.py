"""Confirms flumine's own commission math and paddock.sim.commission agree.

flumine 3.2.0's Market.cleared(client) computes:
    round(max(profit * client.commission_base, 0), 2)
paddock.sim.commission.compute_commission must produce the exact same
number for the exact same (profit, commission_rate) — that's the whole
point of the function existing, rather than us inventing our own formula.

Why this test uses tests/resources/1.170258213 (flumine's own bundled
fixture) rather than the real Basic Plan file bundled for the smoke test:
verified empirically that Basic Plan historic data carries `ltp` only, no
`atb`/`atl`/`trd` (order-book depth / traded-volume ladder). flumine's
SimulatedMiddleware derives simulated fills from the traded-volume ladder
(flumine/markets/middleware.py RunnerAnalytics.traded, sourced from
runner.ex.traded_volume i.e. the `trd` field) — with no `trd` in the stream,
a placed order reaches EXECUTION_COMPLETE with size_matched=0.0 always, no
matter the price. That's not a bug in this code, it's a real gap in what
Basic Plan data can back-test: a limit order backtest can only "just work"
against the free tier if profit ends up 0 for every order, which would
make this test pass for a trivial and uninteresting reason. This needs a
decision from Gary before step 3's BaselineFavouriteScalp is designed
around real fills — flagged, not resolved, here.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import pytest
from flumine import FlumineSimulation
from flumine.order.order import OrderStatus
from flumine.order.ordertype import LimitOrder
from flumine.order.trade import Trade
from flumine.streams.betfairhistoricalstream import BetfairHistoricalStream
from flumine.strategy.strategy import BaseStrategy
from flumine.utils import get_price

from paddock.sim.clients import build_replay_client
from paddock.sim.commission import compute_commission

SAMPLE_MARKET = Path(__file__).parent / "resources" / "1.170258213"
COMMISSION_RATE = 0.02


class _BackFavouriteOnce(BaseStrategy):
    """Test-only: places exactly one back bet, as soon as the market is open
    and at least one runner has a back price, so a settled market produces a
    real (non-zero) profit/loss to check commission math against."""

    def check_market_book(self, market, market_book) -> bool:
        return market_book.status == "OPEN" and not self.context.get("placed")

    def process_market_book(self, market, market_book) -> None:
        for runner in market_book.runners:
            if runner.status != "ACTIVE":
                continue
            price = get_price(runner.ex.available_to_back, 0)
            if not price:
                continue
            trade = Trade(market.market_id, runner.selection_id, runner.handicap, self)
            order = trade.create_order(
                side="BACK",
                order_type=LimitOrder(price, 2.0),
                notes=OrderedDict(test="commission_parity"),
            )
            market.place_order(order)
            self.context["placed"] = True
            return

    def process_orders(self, market, orders) -> None:
        for order in orders:
            if order.status == OrderStatus.EXECUTABLE and order.elapsed_seconds and order.elapsed_seconds > 5:
                market.cancel_order(order)


@pytest.mark.parametrize("profit,rate", [(10.0, 0.02), (-5.0, 0.02), (0.0, 0.05), (123.456, 0.1)])
def test_compute_commission_matches_flumine_formula(profit, rate):
    assert compute_commission(profit, rate) == round(max(profit * rate, 0.0), 2)


def test_commission_matches_flumine_cleared_for_real_settled_market():
    client = build_replay_client(COMMISSION_RATE)
    framework = FlumineSimulation(client=client)
    strategy = _BackFavouriteOnce(
        streams=[BetfairHistoricalStream(file_path=str(SAMPLE_MARKET))],
        max_order_exposure=100,
        max_selection_exposure=100,
    )
    framework.add_strategy(strategy)
    framework.run()

    markets = list(framework.markets)
    assert markets, "expected at least one market to have been processed"
    market = markets[0]

    cleared = market.cleared(client)
    ours = compute_commission(cleared["profit"], COMMISSION_RATE)

    assert cleared["commission"] == ours
