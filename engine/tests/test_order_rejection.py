"""Trading-control rejections (flumine OrderStatus.VIOLATION) must be
surfaced, not silently swallowed — this is exactly the bug that made step
3's first draft of BaselineFavouriteScalp look like it placed nothing (see
paddock.strategies.baseline's docstring and git history): the lay leg
violated STRATEGY_EXPOSURE (max_live_trade_count=1, two concurrent legs)
and nothing said so anywhere.

Where this actually gets caught: NOT LoggingControl, and NOT any per-order
status hook. Confirmed against flumine 3.2.0 source — a rejected order
never reaches market.blotter (Transaction.place_order returns False on
ControlError before the order is ever added to it), and
log_control(OrderEvent(...)) is only called on a *successful* placement
response (execution/baseexecution.py). The only observable signal is
Market.place_order's boolean return value at the call site — see
paddock.sim.orders.place_order, which every strategy should call through
rather than market.place_order directly.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from flumine import FlumineSimulation
from flumine.order.ordertype import LimitOrder
from flumine.order.trade import Trade
from flumine.strategy.strategy import BaseStrategy
from flumine.streams.betfairhistoricalstream import BetfairHistoricalStream

from paddock.bus.bus import EventBus
from paddock.sim.clients import build_replay_client
from paddock.sim.orders import place_order

RICH_MARKET = Path(__file__).parent / "resources" / "1.170258213"


class _TwoConcurrentLegsStrategy(BaseStrategy):
    """Deliberately places two simultaneous live orders on the same runner
    with max_live_trade_count left at BaseStrategy's default of 1 (not
    overridden, unlike BaselineFavouriteScalp) — the second one must
    violate STRATEGY_EXPOSURE. Uses paddock.sim.orders.place_order (the
    real code path every strategy should use), not raw market.place_order,
    so this test exercises the actual reporting mechanism.
    """

    def __init__(self, *args, bus, **kwargs):
        super().__init__(*args, **kwargs)
        self.bus = bus

    def check_market_book(self, market, market_book) -> bool:
        return market_book.status == "OPEN" and not self.context.get("placed")

    def process_market_book(self, market, market_book) -> None:
        for runner in market_book.runners:
            if runner.status != "ACTIVE" or not runner.last_price_traded:
                continue
            price = runner.last_price_traded
            for _ in range(2):
                trade = Trade(market.market_id, runner.selection_id, runner.handicap, self)
                order = trade.create_order(
                    side="BACK", order_type=LimitOrder(price, 2.0), notes=OrderedDict()
                )
                place_order(market, order, self.bus)
            self.context["placed"] = True
            return


def test_order_rejected_event_fires_on_max_live_trade_count_violation():
    bus = EventBus()
    queue = bus.subscribe()

    client = build_replay_client(0.02)
    framework = FlumineSimulation(client=client)
    strategy = _TwoConcurrentLegsStrategy(
        streams=[BetfairHistoricalStream(file_path=str(RICH_MARKET))],
        max_order_exposure=100,
        max_selection_exposure=100,
        bus=bus,
        # max_live_trade_count defaults to 1 — not overridden, that's the point
    )
    framework.add_strategy(strategy)
    framework.run()

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    rejected = [e for e in events if e.type == "order.rejected"]
    assert len(rejected) == 1
    assert "live_trade_count" in rejected[0].reason

    error_heartbeats = [
        e for e in events if e.type == "worker.heartbeat" and e.name == "executor" and e.state == "error"
    ]
    assert len(error_heartbeats) == 1
