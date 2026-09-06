"""Orchestrates a single FlumineSimulation run: discovers market files,
wires client/middleware/logging control, writes runs.db, returns run_id.

All paths are pathlib.Path throughout — the repo lives under a path with a
space in it (`/Volumes/Mac Mini 2TB/...`), so nothing here does string
concatenation or shells out to build a path; see
tests/test_paths_with_spaces.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from flumine import FlumineSimulation
from flumine.strategy.strategy import BaseStrategy
from flumine.streams.betfairhistoricalstream import BetfairHistoricalStream

from paddock.bus.bus import EventBus
from paddock.bus.bus import bus as default_bus
from paddock.bus.events import WorkerHeartbeat, WorkerState
from paddock.sim import store
from paddock.sim.clients import build_replay_client
from paddock.sim.logging_control import PaddockLoggingControl
from paddock.sim.pacing import WallClockPacingMiddleware

logger = logging.getLogger(__name__)


def _looks_like_market_file(path: Path) -> bool:
    # Betfair market ids are always "1.<digits>" regardless of sport; this
    # is also the filename paddock.data.historic.unpack() writes.
    name = path.name
    return name.startswith("1.") and name[2:].isdigit()


def discover_market_files(data_path: Path) -> list[Path]:
    data_path = Path(data_path)
    if data_path.is_file():
        return [data_path]
    if not data_path.exists():
        return []
    return sorted(p for p in data_path.rglob("*") if p.is_file() and _looks_like_market_file(p))


def run_simulation(
    strategy_cls: type[BaseStrategy],
    market_files: list[Path],
    speed: float,
    commission_rate: float,
    data_dir: Path,
    strategy_kwargs: dict[str, Any] | None = None,
    run_id: str | None = None,
    bus: EventBus = default_bus,
) -> str:
    if not market_files:
        raise FileNotFoundError("No market files provided to run_simulation")

    data_dir = Path(data_dir)
    run_id = run_id or uuid4().hex
    strategy_kwargs = dict(strategy_kwargs or {})

    streams = [BetfairHistoricalStream(file_path=str(f)) for f in market_files]
    strategy = strategy_cls(streams=streams, **strategy_kwargs)

    with store.connect(data_dir) as con:
        store.create_run(
            con,
            run_id,
            strategy.name,
            strategy.context,
            commission_rate,
            datetime.now(timezone.utc).isoformat(),
        )

    bus.publish(WorkerHeartbeat(name="data_loader", state=WorkerState.BUSY, last_latency_ms=None))
    client = build_replay_client(commission_rate)
    framework = FlumineSimulation(client=client)
    framework.add_strategy(strategy)
    framework.add_market_middleware(WallClockPacingMiddleware(speed=speed))
    framework.add_logging_control(PaddockLoggingControl(bus, run_id, commission_rate, data_dir))
    bus.publish(WorkerHeartbeat(name="data_loader", state=WorkerState.IDLE, last_latency_ms=None))

    bus.publish(WorkerHeartbeat(name="stream", state=WorkerState.BUSY, last_latency_ms=None))
    bus.publish(WorkerHeartbeat(name="executor", state=WorkerState.BUSY, last_latency_ms=None))
    try:
        framework.run()
    finally:
        bus.publish(WorkerHeartbeat(name="stream", state=WorkerState.IDLE, last_latency_ms=None))
        bus.publish(WorkerHeartbeat(name="executor", state=WorkerState.IDLE, last_latency_ms=None))
        bus.publish(WorkerHeartbeat(name="pnl", state=WorkerState.IDLE, last_latency_ms=None))

    logger.info("Simulation run %s complete over %d market file(s)", run_id, len(market_files))
    return run_id
