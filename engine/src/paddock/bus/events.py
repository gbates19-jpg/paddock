"""Pydantic event models for the PADDOCK bus.

Every significant thing the engine does emits one of these onto the bus
(see paddock.bus.bus.EventBus). The FastAPI layer serializes them 1:1 as
JSON over the /events websocket, so the field names here are the wire
contract the UI renders against — treat renames as breaking changes.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def _now_ms() -> int:
    return int(time.time() * 1000)


class WorkerState(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"


class OrderSide(str, Enum):
    BACK = "back"
    LAY = "lay"


class OrderLifecycle(str, Enum):
    PLACED = "placed"
    MATCHED = "matched"
    CANCELLED = "cancelled"
    LAPSED = "lapsed"


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class BaseEvent(BaseModel):
    """Common envelope. `type` is a discriminator the UI switches on."""

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    ts_ms: int = Field(default_factory=_now_ms)


class WorkerHeartbeat(BaseEvent):
    type: Literal["worker.heartbeat"] = "worker.heartbeat"
    name: str
    state: WorkerState
    last_latency_ms: float | None = None


class Runner(BaseModel):
    selection_id: int
    name: str | None = None


class MarketOpen(BaseEvent):
    type: Literal["market.open"] = "market.open"
    market_id: str
    venue: str | None = None
    race_name: str | None = None
    off_time: str | None = None
    runners: list[Runner] = Field(default_factory=list)


class MarketClose(BaseEvent):
    type: Literal["market.close"] = "market.close"
    market_id: str


class PriceLevel(BaseModel):
    price: float
    size: float


class RunnerPrice(BaseEvent):
    type: Literal["runner.price"] = "runner.price"
    market_id: str
    selection_id: int
    back: list[PriceLevel] = Field(default_factory=list)
    lay: list[PriceLevel] = Field(default_factory=list)
    ltp: float | None = None
    traded_volume: float | None = None


class StrategySignal(BaseEvent):
    type: Literal["strategy.signal"] = "strategy.signal"
    strategy: str
    market_id: str
    selection_id: int
    reason: str
    confidence: float | None = None


class OrderEvent(BaseEvent):
    type: Literal[
        "order.placed", "order.matched", "order.cancelled", "order.lapsed"
    ]
    order_id: str
    market_id: str
    selection_id: int
    side: OrderSide
    price: float
    size: float
    matched_size: float = 0.0


class OrderRejected(BaseEvent):
    """A trading-control rejection (flumine OrderStatus.VIOLATION) — the
    order was never live at all, so this is deliberately a separate event
    from OrderEvent's placed/matched/cancelled/lapsed lifecycle rather than
    a fifth literal on it. See paddock.sim.logging_control."""

    type: Literal["order.rejected"] = "order.rejected"
    order_id: str
    market_id: str
    selection_id: int
    side: OrderSide
    price: float
    size: float
    reason: str


class PositionUnhedged(BaseEvent):
    """A strategy gave up trying to flatten a position — walked the
    slippage tolerance (paddock.strategies.baseline's closer retry loop)
    and still couldn't get matched. A real, naked position is left open at
    settlement. See paddock.strategies.baseline._give_up_closing."""

    type: Literal["position.unhedged"] = "position.unhedged"
    strategy: str
    market_id: str
    selection_id: int
    side: OrderSide
    remaining_size: float
    attempts: int
    reason: str


class PnlUpdate(BaseEvent):
    type: Literal["pnl.update"] = "pnl.update"
    run_id: str
    market_id: str | None = None
    market_pnl: float | None = None
    run_pnl: float = 0.0
    commission: float = 0.0
    # Required, no default: P&L is only meaningful alongside how it was
    # produced — "ltp_cross" numbers are an optimistic upper bound, not a
    # backtest result. See paddock.sim.fill_models.
    fill_model: str


class RunConfig(BaseEvent):
    """Announced once when a sim run starts (and carried in the bus
    snapshot) so a UI that connects mid-run — or a phone joining late over
    Tailscale — knows the mode badge state without waiting for a
    pnl.update. See paddock.sim.harness.run_simulation."""

    type: Literal["run.config"] = "run.config"
    run_id: str
    mode: str
    fill_model: str
    commission_rate: float
    # The value at run start — POST /sim/speed can change it live
    # afterwards (paddock.sim.pacing.SpeedControl); the Book HUD's slider
    # tracks its own optimistic local state rather than re-reading this.
    speed: float


class LogEvent(BaseEvent):
    type: Literal["log"] = "log"
    level: LogLevel
    msg: str


Event = (
    WorkerHeartbeat
    | MarketOpen
    | MarketClose
    | RunnerPrice
    | StrategySignal
    | OrderEvent
    | OrderRejected
    | PositionUnhedged
    | PnlUpdate
    | RunConfig
    | LogEvent
)

EVENT_TYPES: dict[str, type[BaseEvent]] = {
    "worker.heartbeat": WorkerHeartbeat,
    "market.open": MarketOpen,
    "market.close": MarketClose,
    "runner.price": RunnerPrice,
    "strategy.signal": StrategySignal,
    "order.placed": OrderEvent,
    "order.matched": OrderEvent,
    "order.cancelled": OrderEvent,
    "order.lapsed": OrderEvent,
    "order.rejected": OrderRejected,
    "position.unhedged": PositionUnhedged,
    "pnl.update": PnlUpdate,
    "run.config": RunConfig,
    "log": LogEvent,
}

# Worker names the UI's Floor scene expects heartbeats from.
WORKER_NAMES = (
    "stream",
    "keep_alive",
    "executor",
    "data_loader",
    "pnl",
)
