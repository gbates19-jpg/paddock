"""Bridges flumine's order/market lifecycle onto the paddock bus + runs.db.

Hooks confirmed against flumine 3.2.0 source:
- _process_order: fired on every Order update. flumine's OrderStatus enum has
  no distinct CANCELLED/LAPSED terminal states (order/order.py) — a
  cancellation and a lapse both just increase size_cancelled/size_lapsed
  while status moves toward EXECUTION_COMPLETE. So lifecycle is derived by
  diffing size_matched/size_cancelled/size_lapsed against the last seen
  values per order id, not by reading .status directly.
- _process_cleared_markets: fired once per client per market close in
  simulation (baseflumine._process_close_market loops `for client in
  self.clients`). event.event.orders[i].commission is flumine's own
  max(profit * client.commission_base, 0) — see paddock.sim.commission for
  why we recompute it independently from the same commission_rate rather
  than trusting flumine's number outright (drift-detection, not distrust).
- _process_market / _process_closed_market: market.open / market.close.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from flumine.controls.loggingcontrols import LoggingControl
from flumine.order.order import OrderStatus

from paddock.bus.bus import EventBus
from paddock.bus.events import MarketClose, MarketOpen, OrderEvent, OrderSide, PnlUpdate, Runner
from paddock.sim import store
from paddock.sim.commission import compute_commission

logger = logging.getLogger(__name__)

COMPLETE_STATUS = {OrderStatus.EXECUTION_COMPLETE, OrderStatus.EXPIRED, OrderStatus.VIOLATION}


class _OrderProgress:
    __slots__ = ("matched", "cancelled", "lapsed")

    def __init__(self) -> None:
        self.matched = 0.0
        self.cancelled = 0.0
        self.lapsed = 0.0


class PaddockLoggingControl(LoggingControl):
    NAME = "PADDOCK_LOGGING_CONTROL"

    def __init__(self, bus: EventBus, run_id: str, commission_rate: float, data_dir: Path):
        super().__init__()
        self.bus = bus
        self.run_id = run_id
        self.commission_rate = commission_rate
        self.data_dir = Path(data_dir)
        self._progress: dict[str, _OrderProgress] = {}
        self._run_pnl = 0.0
        self._con: sqlite3.Connection | None = None

    def _get_con(self) -> sqlite3.Connection:
        # Opened lazily from inside this control's own thread (run() is
        # started by flumine via Thread.start()) — sqlite3 connections are
        # bound to the thread that created them.
        if self._con is None:
            self._con = store.open_connection(self.data_dir)
        return self._con

    def _process_end_flumine(self, event) -> None:
        super()._process_end_flumine(event)
        if self._con is not None:
            self._con.commit()
            self._con.close()
            self._con = None

    def _process_order(self, event) -> None:
        order = event.event
        side = OrderSide.BACK if order.side == "BACK" else OrderSide.LAY
        price = order.order_type.price
        size = order.order_type.size
        matched = order.size_matched or 0.0
        cancelled = order.size_cancelled or 0.0
        lapsed = order.size_lapsed or 0.0

        progress = self._progress.get(order.id)
        if progress is None:
            progress = _OrderProgress()
            self._progress[order.id] = progress
            self._publish_order_event(
                "order.placed", order, side, price, size, matched
            )

        if matched > progress.matched:
            self._publish_order_event("order.matched", order, side, price, size, matched)
        if cancelled > progress.cancelled:
            self._publish_order_event("order.cancelled", order, side, price, size, matched)
        if lapsed > progress.lapsed:
            self._publish_order_event("order.lapsed", order, side, price, size, matched)

        progress.matched, progress.cancelled, progress.lapsed = matched, cancelled, lapsed

        if order.status in COMPLETE_STATUS:
            con = self._get_con()
            store.record_order(
                con,
                self.run_id,
                order.id,
                order.market_id,
                order.selection_id,
                side.value,
                price,
                size,
                matched,
                order.status.value,
                order.profit,
            )
            con.commit()

    def _publish_order_event(self, event_type: str, order, side, price, size, matched) -> None:
        self.bus.publish(
            OrderEvent(
                type=event_type,
                order_id=order.id,
                market_id=order.market_id,
                selection_id=order.selection_id,
                side=side,
                price=price,
                size=size,
                matched_size=matched,
            )
        )

    def _process_cleared_markets(self, event) -> None:
        for cleared in event.event.orders:
            profit = cleared.profit
            flumine_commission = cleared.commission
            our_commission = compute_commission(profit, self.commission_rate)
            if abs(our_commission - flumine_commission) > 0.005:
                logger.error(
                    "Commission mismatch for %s: flumine=%s ours=%s (commission_rate=%s) "
                    "— client.commission_base is out of sync with engine config.",
                    cleared.market_id,
                    flumine_commission,
                    our_commission,
                    self.commission_rate,
                )
            self._run_pnl += profit - our_commission
            con = self._get_con()
            store.record_market_result(
                con, self.run_id, cleared.market_id, profit, our_commission, cleared.bet_count
            )
            con.commit()
            self.bus.publish(
                PnlUpdate(
                    run_id=self.run_id,
                    market_id=cleared.market_id,
                    market_pnl=profit,
                    run_pnl=self._run_pnl,
                    commission=our_commission,
                )
            )

    def _process_market(self, event) -> None:
        market = event.event
        definition = market.market_book.market_definition if market.market_book else None
        runners = (
            [Runner(selection_id=r.selection_id, name=r.name) for r in definition.runners]
            if definition
            else []
        )
        self.bus.publish(
            MarketOpen(
                market_id=market.market_id,
                venue=market.venue,
                race_name=market.event_name,
                off_time=str(market.market_start_datetime) if market.market_start_datetime else None,
                runners=runners,
            )
        )

    def _process_closed_market(self, event) -> None:
        market_book = event.event
        market_id = market_book.market_id if hasattr(market_book, "market_id") else market_book.get("id")
        self.bus.publish(MarketClose(market_id=market_id))
