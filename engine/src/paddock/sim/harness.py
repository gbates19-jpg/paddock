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
from paddock.bus.events import RunConfig, WorkerHeartbeat, WorkerState
from paddock.data.manifest import data_plan_for
from paddock.sim import store
from paddock.sim.clients import build_replay_client
from paddock.sim.fill_models import LtpCrossMiddleware
from paddock.sim.logging_control import PaddockLoggingControl
from paddock.sim.pacing import WallClockPacingMiddleware

logger = logging.getLogger(__name__)


class FillModelError(ValueError):
    """Raised when fill_model and the data plan of the loaded market files
    are incompatible — see the module docstring on paddock.sim.fill_models
    and paddock.data.manifest for why this distinction matters."""


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


def _validate_fill_model(
    fill_model: str, market_files: list[Path], data_dir: Path | None
) -> None:
    """ladder needs ex/trd data — REFUSE (raise) if any file lacks it.
    ltp_cross doesn't need it — WARN (log only) if a file has it anyway,
    since running the optimistic approximation on data that could give a
    real fill is a (recoverable) quality-of-backtest mistake, not a
    fatal one."""
    basic_files = []
    rich_files = []
    for f in market_files:
        plan = data_plan_for(f, data_dir)
        (basic_files if plan == "basic" else rich_files).append(f)

    if fill_model == "ladder" and basic_files:
        names = ", ".join(f.name for f in basic_files[:5])
        more = f" (+{len(basic_files) - 5} more)" if len(basic_files) > 5 else ""
        raise FillModelError(
            f"fill_model=ladder requires order-book depth + traded-volume data "
            f"(Advanced/Pro historic plan, or a live stream), but {len(basic_files)} "
            f"of {len(market_files)} market file(s) are Basic Plan (ltp only): "
            f"{names}{more}. Use fill_model=ltp_cross for Basic Plan data — see "
            f"config/engine.yaml."
        )

    if fill_model == "ltp_cross" and rich_files:
        logger.warning(
            "fill_model=ltp_cross is being used on %d/%d market file(s) that have "
            "real order-book depth and could support fill_model=ladder instead — "
            "ltp_cross's P&L is an optimistic upper bound, ladder's is a real "
            "simulated backtest. Consider switching for these files.",
            len(rich_files),
            len(market_files),
        )


def run_simulation(
    strategy_cls: type[BaseStrategy],
    market_files: list[Path],
    speed: float,
    commission_rate: float,
    fill_model: str,
    data_dir: Path,
    mode: str = "replay",
    strategy_kwargs: dict[str, Any] | None = None,
    run_id: str | None = None,
    bus: EventBus = default_bus,
) -> str:
    if not market_files:
        raise FileNotFoundError("No market files provided to run_simulation")

    data_dir = Path(data_dir)
    _validate_fill_model(fill_model, market_files, data_dir)

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
            fill_model,
            datetime.now(timezone.utc).isoformat(),
        )

    bus.publish(
        RunConfig(run_id=run_id, mode=mode, fill_model=fill_model, commission_rate=commission_rate)
    )

    bus.publish(WorkerHeartbeat(name="data_loader", state=WorkerState.BUSY, last_latency_ms=None))
    client = build_replay_client(commission_rate)
    framework = FlumineSimulation(client=client)
    framework.add_strategy(strategy)
    framework.add_market_middleware(WallClockPacingMiddleware(speed=speed))
    if fill_model == "ltp_cross":
        framework.add_market_middleware(LtpCrossMiddleware())
    framework.add_logging_control(
        PaddockLoggingControl(bus, run_id, commission_rate, fill_model, data_dir)
    )
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
