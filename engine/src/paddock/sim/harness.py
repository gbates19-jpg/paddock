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
from paddock.data.manifest import LADDER_CAPABLE_PLANS, data_plan_for
from paddock.sim import store
from paddock.sim.clients import build_replay_client
from paddock.sim.fill_models import LtpCrossMiddleware
from paddock.sim.logging_control import PaddockLoggingControl
from paddock.sim.pacing import WallClockPacingMiddleware
from paddock.sim.runner_price import DEFAULT_MAX_PER_SECOND, RunnerPriceMiddleware

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
    ladder_capable_files = []
    for f in market_files:
        plan = data_plan_for(f, data_dir)
        (ladder_capable_files if plan in LADDER_CAPABLE_PLANS else basic_files).append(f)

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

    if fill_model == "ltp_cross" and ladder_capable_files:
        logger.warning(
            "fill_model=ltp_cross is being used on %d/%d market file(s) that have "
            "real order-book depth and could support fill_model=ladder instead — "
            "ltp_cross's P&L is an optimistic upper bound, ladder's is a real "
            "simulated backtest. Consider switching for these files.",
            len(ladder_capable_files),
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
    runner_price_rate: float = DEFAULT_MAX_PER_SECOND,
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
    framework.add_market_middleware(RunnerPriceMiddleware(bus=bus, max_per_second=runner_price_rate))
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

    _record_final_orders(framework, run_id, data_dir)

    logger.info("Simulation run %s complete over %d market file(s)", run_id, len(market_files))
    return run_id


def _record_final_orders(framework: FlumineSimulation, run_id: str, data_dir: Path) -> None:
    """Reads every order's FINAL state directly from framework.markets[*]
    .blotter, on the main thread, after framework.run() has already
    returned — the same pattern flumine's own examples/simulate.py uses.

    This is deliberately NOT done via PaddockLoggingControl: confirmed
    against flumine 3.2.0 source that log_control(OrderEvent(order)) fires
    exactly once per order, at successful placement, never again on
    cancel or match — so whether that single background-thread-processed
    snapshot catches an order's final status is a genuine race against the
    main thread's ongoing simulation. Reading the blotter here instead,
    after the simulation has fully finished, has no such race — every
    order object's state is final and nothing else is mutating it.
    See paddock.sim.logging_control's module docstring for the full story.
    """
    with store.connect(data_dir) as con:
        for market in framework.markets:
            for order in market.blotter:
                side = "back" if order.side == "BACK" else "lay"
                store.record_order(
                    con,
                    run_id,
                    order.id,
                    order.market_id,
                    order.selection_id,
                    side,
                    order.order_type.price,
                    order.order_type.size,
                    order.size_matched or 0.0,
                    order.status.value if order.status else "unknown",
                    order.profit,
                    role=order.notes.get("role") if order.notes else None,
                    attempt=order.notes.get("attempt") if order.notes else None,
                )
