"""Verifies the fill_model decision end to end:

- ladder against Basic Plan data (1.261851533, ltp-only) REFUSES to run.
- ltp_cross against the same Basic Plan data DOES produce real fills —
  confirmed empirically: flumine's native matching gives size_matched=0
  always against this fixture (no trd field), ltp_cross does not.
- ladder still works normally against rich data (1.170258213) — this
  wiring doesn't regress step 2's commission test.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from flumine import FlumineSimulation
from flumine.order.ordertype import LimitOrder
from flumine.order.trade import Trade
from flumine.strategy.strategy import BaseStrategy
from flumine.streams.betfairhistoricalstream import BetfairHistoricalStream

from paddock.data.manifest import detect_data_plan
from paddock.sim.clients import build_replay_client
from paddock.sim.fill_models import LtpCrossMiddleware
from paddock.sim.harness import FillModelError, run_simulation
from paddock.strategies.passive import PassiveObserver

BASIC_MARKET = Path(__file__).parent / "resources" / "1.261851533"
RICH_MARKET = Path(__file__).parent / "resources" / "1.170258213"


class _BackFirstActiveRunner(BaseStrategy):
    """Test-only: backs the first active runner at its own ltp, once."""

    def check_market_book(self, market, market_book) -> bool:
        return market_book.status == "OPEN" and not self.context.get("placed")

    def process_market_book(self, market, market_book) -> None:
        for runner in market_book.runners:
            if runner.status == "ACTIVE" and runner.last_price_traded:
                trade = Trade(market.market_id, runner.selection_id, runner.handicap, self)
                order = trade.create_order(
                    side="BACK", order_type=LimitOrder(runner.last_price_traded, 2.0)
                )
                market.place_order(order)
                self.context["placed"] = True
                return


def test_detect_data_plan_classifies_bundled_fixtures_correctly():
    assert detect_data_plan(BASIC_MARKET) == "basic"
    assert detect_data_plan(RICH_MARKET) == "pro"


def test_ladder_refuses_to_run_against_basic_plan_data(tmp_path):
    with pytest.raises(FillModelError, match="fill_model=ladder requires"):
        run_simulation(
            PassiveObserver,
            [BASIC_MARKET],
            speed=0,
            commission_rate=0.02,
            fill_model="ladder",
            data_dir=tmp_path,
        )


def test_ltp_cross_runs_against_basic_plan_data(tmp_path):
    run_id = run_simulation(
        PassiveObserver,
        [BASIC_MARKET],
        speed=0,
        commission_rate=0.02,
        fill_model="ltp_cross",
        data_dir=tmp_path,
    )
    assert run_id


def test_ltp_cross_produces_real_fills_where_ladder_gives_zero():
    client = build_replay_client(0.02)
    framework = FlumineSimulation(client=client)
    strategy = _BackFirstActiveRunner(
        streams=[BetfairHistoricalStream(file_path=str(BASIC_MARKET))],
        max_order_exposure=100,
        max_selection_exposure=100,
    )
    framework.add_strategy(strategy)
    framework.add_market_middleware(LtpCrossMiddleware())
    framework.run()

    orders = [o for market in framework.markets for o in market.blotter]
    assert orders, "expected at least one order"
    assert orders[0].size_matched == 2.0
    assert orders[0].average_price_matched == orders[0].order_type.price


def test_ladder_still_works_normally_against_rich_data(tmp_path):
    # regression guard: wiring fill_model through the harness must not
    # change behaviour for data that supports native matching.
    run_id = run_simulation(
        PassiveObserver,
        [RICH_MARKET],
        speed=0,
        commission_rate=0.02,
        fill_model="ladder",
        data_dir=tmp_path,
    )
    assert run_id
