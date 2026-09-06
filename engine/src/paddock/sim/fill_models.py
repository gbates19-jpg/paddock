"""The `ltp_cross` fill model — an optimistic approximation for Basic Plan
(ltp-only) historic data, where flumine's native traded-volume-ladder
matching (see paddock.data.manifest's docstring) can't produce any fills at
all (verified empirically: a limit order against Basic Plan data always
settles size_matched=0 under flumine's default SimulatedOrder).

Rule: a BACK limit at price P is assumed fully matched at P on the first
tick where ltp >= P after placement (LAY: ltp <= P). No partial fills, no
queue position. Bet delay still applies — that's enforced upstream by
flumine's order-package latency handling (FlumineSimulation._check_pending_
packages / order_package.simulated_latency), which runs before this ever
sees the order, so nothing needed here to preserve it.

Implemented by subclassing flumine's own SimulatedOrder/SimulatedMiddleware
and swapping which instance an order uses — not by patching flumine's
classes/methods. LtpCrossMiddleware IS a SimulatedMiddleware subclass, so
flumine's own "only add a default SimulatedMiddleware if none is present"
check (BaseFlumine, `isinstance(val, SimulatedMiddleware)`) sees ours and
doesn't also add its own — no double registration.

P&L produced under this model is an OPTIMISTIC UPPER BOUND, not a backtest
result — surface that wherever fill_model is shown (runs.db, pnl.update
events, the mode badge, CLI output).
"""
from __future__ import annotations

from flumine.markets.middleware import SimulatedMiddleware
from flumine.order.ordertype import OrderTypes
from flumine.simulation.simulatedorder import SimulatedOrder


class LtpCrossSimulatedOrder(SimulatedOrder):
    def __call__(self, market_book, runner_traded) -> None:
        if self.order.order_type.ORDER_TYPE != OrderTypes.LIMIT or self.size_matched > 0:
            super().__call__(market_book, runner_traded)
            return

        runner = runner_traded[0]
        ltp = runner.last_price_traded
        price = self.order.order_type.price
        if ltp is not None:
            crossed = (self.order.side == "BACK" and ltp >= price) or (
                self.order.side == "LAY" and ltp <= price
            )
            if crossed:
                size = self.order.order_type.size
                self.matched = [[market_book.publish_time_epoch, price, size]]
                self.size_matched = size
                self.average_price_matched = price
                return

        # Not crossed (or no ltp yet) — still honour SUSPENDED/LAPSE
        # persistence handling from the base implementation, since that's a
        # real order-lifecycle behaviour independent of the fill model.
        super().__call__(market_book, runner_traded)


class LtpCrossMiddleware(SimulatedMiddleware):
    def __call__(self, market) -> None:
        for order in market.blotter.live_orders:
            if not isinstance(order.simulated, LtpCrossSimulatedOrder):
                order.simulated = LtpCrossSimulatedOrder(order)
        super().__call__(market)
