"""Wraps flumine's Market.place_order to surface trading-control rejections.

Confirmed against flumine 3.2.0 source that this can't be done any other
way: a rejected order (OrderStatus.VIOLATION, raised inside
BaseControl._on_error via ControlError) never reaches
market.blotter — Transaction.place_order returns False on ControlError
*before* `market.blotter[order.id] = order` runs — and
log_control(OrderEvent(...)) is only ever called from
execution/baseexecution.py on a successful placement response. So neither
LoggingControl nor any per-order "status hook" ever sees a rejection; the
only observable signal is Market.place_order's own boolean return value at
the call site. This wraps that call so strategies don't have to duplicate
the rejection-reporting logic themselves.
"""
from __future__ import annotations

import logging

from paddock.bus.bus import EventBus
from paddock.bus.bus import bus as default_bus
from paddock.bus.events import OrderRejected, OrderSide, WorkerHeartbeat, WorkerState

logger = logging.getLogger(__name__)


def place_order(market, order, bus: EventBus | None = None) -> bool:
    """Same contract as market.place_order(order): True if placed, False
    if a trading control rejected it — but also reports the rejection."""
    bus = bus or default_bus
    if market.place_order(order):
        return True

    side = OrderSide.BACK if order.side == "BACK" else OrderSide.LAY
    reason = order.violation_msg or "unknown violation"
    logger.error(
        "Order rejected market=%s selection=%s side=%s: %s",
        order.market_id,
        order.selection_id,
        side.value,
        reason,
    )
    bus.publish(
        OrderRejected(
            order_id=order.id,
            market_id=order.market_id,
            selection_id=order.selection_id,
            side=side,
            price=order.order_type.price,
            size=order.order_type.size,
            reason=reason,
        )
    )
    # Momentary flash, not a stuck state — the executor isn't broken, one
    # order attempt was refused. See FloorScene's error shake/flash.
    bus.publish(WorkerHeartbeat(name="executor", state=WorkerState.ERROR, last_latency_ms=None))
    bus.publish(WorkerHeartbeat(name="executor", state=WorkerState.IDLE, last_latency_ms=None))
    return False
