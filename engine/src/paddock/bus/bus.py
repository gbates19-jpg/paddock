"""Asyncio event bus: engine code publishes events, the API broadcasts them.

Single process, single asyncio loop (per Phase 0 stack decision — no Redis).
The bus also keeps a rolling snapshot of "current state" so a websocket
client that connects mid-run can be caught up without replaying history.

Thread-safety: `publish()` is called from more than one thread once a sim
run is driven from a background thread (paddock.api.main's POST
/sim/start) — both the thread running `FlumineSimulation.run()` itself
(paddock.sim.harness) and flumine's own internal LoggingControl thread
(paddock.sim.logging_control) call it, neither of which is the asyncio
loop's thread. `asyncio.Queue.put_nowait` is documented as NOT
thread-safe — calling it off-loop can silently corrupt the queue's
internal waiter bookkeeping rather than raising, which would look like
"the UI randomly misses fills" under load, not a crash. `bind_loop()`
records the loop that owns this bus's subscriber queues; once bound,
every `publish()` — regardless of which thread calls it — is marshalled
onto that loop via `call_soon_threadsafe` before touching any queue.
Before `bind_loop()` is called (plain CLI usage, no API/websocket layer
involved at all) `publish()` runs synchronously in the calling thread, so
`paddock sim run` on its own pays no extra cost and needs no running loop.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Callable

from paddock.bus.events import (
    BaseEvent,
    MarketClose,
    MarketOpen,
    PnlUpdate,
    RunConfig,
    RunnerPrice,
    WorkerHeartbeat,
)

logger = logging.getLogger(__name__)

Subscriber = Callable[[BaseEvent], None]


class EventBus:
    def __init__(self, history_size: int = 500) -> None:
        self._subscribers: set[asyncio.Queue[BaseEvent]] = set()
        self._history: deque[BaseEvent] = deque(maxlen=history_size)
        # snapshot state for new-connection catch-up
        self._workers: dict[str, WorkerHeartbeat] = {}
        self._markets: dict[str, MarketOpen] = {}
        self._runner_prices: dict[tuple[str, int], RunnerPrice] = {}
        self._pnl: PnlUpdate | None = None
        self._run_config: RunConfig | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        """Called once from paddock.api.main's lifespan, with the loop
        FastAPI/uvicorn is actually running on. Until this is called,
        publish() assumes there's no loop to protect (plain CLI usage)."""
        self._loop = loop

    def publish(self, event: BaseEvent) -> None:
        # call_soon_threadsafe is safe to use even when we happen to already
        # be on the loop's own thread (it's just a slower call_soon in that
        # case) — so we don't need to detect which thread we're on, only
        # whether a loop has been bound at all.
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._publish_now, event)
        else:
            self._publish_now(event)

    def _publish_now(self, event: BaseEvent) -> None:
        self._history.append(event)
        self._update_snapshot(event)
        dead = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(queue)
        for queue in dead:
            self._subscribers.discard(queue)

    def _update_snapshot(self, event: BaseEvent) -> None:
        if isinstance(event, WorkerHeartbeat):
            self._workers[event.name] = event
        elif isinstance(event, MarketOpen):
            self._markets[event.market_id] = event
        elif isinstance(event, MarketClose):
            self._markets.pop(event.market_id, None)
            stale = [k for k in self._runner_prices if k[0] == event.market_id]
            for k in stale:
                del self._runner_prices[k]
        elif isinstance(event, RunnerPrice):
            self._runner_prices[(event.market_id, event.selection_id)] = event
        elif isinstance(event, PnlUpdate):
            self._pnl = event
        elif isinstance(event, RunConfig):
            self._run_config = event

    def subscribe(self, maxsize: int = 1000) -> asyncio.Queue[BaseEvent]:
        queue: asyncio.Queue[BaseEvent] = asyncio.Queue(maxsize=maxsize)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[BaseEvent]) -> None:
        self._subscribers.discard(queue)

    def snapshot(self) -> dict:
        return {
            "workers": [w.model_dump(mode="json") for w in self._workers.values()],
            "markets": [m.model_dump(mode="json") for m in self._markets.values()],
            "runner_prices": [p.model_dump(mode="json") for p in self._runner_prices.values()],
            "pnl": self._pnl.model_dump(mode="json") if self._pnl else None,
            "run_config": self._run_config.model_dump(mode="json") if self._run_config else None,
        }


# Process-wide singleton — one bus per engine process (single asyncio loop).
bus = EventBus()
