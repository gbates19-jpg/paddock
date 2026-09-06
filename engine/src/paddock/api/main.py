"""FastAPI layer: exposes the bus over HTTP + a websocket for the UI.

/sim/speed is real: it reaches whichever run(s) are currently in progress
via paddock.sim.harness.ACTIVE_RUN_SPEEDS (a run_id -> SpeedControl
registry populated by run_simulation) and mutates the SpeedControl that
run's WallClockPacingMiddleware reads on every tick — no restart needed.

/sim/start is real: it validates strategy/data/fill_model synchronously
(same checks `paddock sim run` does) so a bad request 400s immediately
rather than dying invisibly on a background thread, then drives
run_simulation() from one — FlumineSimulation.run() blocks for the whole
replay, and this endpoint has to return the run_id immediately. See
paddock.bus.bus's module docstring for why publishing from that thread
needed its own fix (bus.bind_loop / call_soon_threadsafe), not just a
`Thread(...).start()`.

/sim/stop is deliberately NOT implemented — not a gap we forgot, one we
looked at and declined to fake. FlumineSimulation.run() (flumine 3.2.0,
simulation/simulation.py) has no cooperative-cancellation check anywhere
in its per-tick loop; the only way to interrupt it from the outside is to
raise out of a strategy/middleware callback, which flumine's own
call_middleware_error_handling only lets propagate at all when the
*global* `flumine.config.raise_errors` flag is set — and that flag also
disables flumine's normal per-tick error containment for every strategy
and middleware for the duration, not just the one we'd be using it to
stop. Faking "stop" that way trades a clean abort for a real, silent
change to how every other error in the run is handled — worse than just
not having the button. A real fix needs flumine to expose an actual
cancellation point (patch upstream, or fork the loop), which is out of
scope here.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from paddock.bus.bus import bus
from paddock.bus.events import LogEvent, LogLevel
from paddock.config.settings import get_settings

logger = logging.getLogger(__name__)


def _runs_db_path() -> Path:
    return Path(get_settings().data_dir) / "runs.db"


class SetSpeedRequest(BaseModel):
    speed: float
    run_id: str | None = None  # omit when exactly one run is in progress


class StartSimRequest(BaseModel):
    strategy: str
    data_path: str
    speed: float = 20.0
    fill_model: str | None = None  # None => config/engine.yaml's default


# Guards POST /sim/start: only one background run at a time in this
# process. Set synchronously, inside _run_lock, before the thread starts —
# not derived from paddock.sim.harness.ACTIVE_RUN_SPEEDS, which is only
# populated once the thread is already inside run_simulation. Checking
# that instead would leave a real race between two concurrent POST
# /sim/start requests both passing the "is one running?" check before
# either had actually registered itself.
_run_lock = threading.Lock()
_run_thread: threading.Thread | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PADDOCK API starting (mode=%s)", get_settings().mode.value)
    bus.bind_loop(asyncio.get_running_loop())
    try:
        yield
    finally:
        bus.bind_loop(None)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="PADDOCK API", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.api_cors_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/runs")
    def list_runs() -> list[dict]:
        db_path = _runs_db_path()
        if not db_path.exists():
            return []
        with sqlite3.connect(db_path) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT run_id, strategy, params, commission_rate, fill_model, created_at "
                "FROM runs ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        db_path = _runs_db_path()
        if not db_path.exists():
            return {}
        with sqlite3.connect(db_path) as con:
            con.row_factory = sqlite3.Row
            run = con.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                return {}
            markets = con.execute(
                "SELECT * FROM run_markets WHERE run_id = ?", (run_id,)
            ).fetchall()
            orders = con.execute(
                "SELECT * FROM run_orders WHERE run_id = ?", (run_id,)
            ).fetchall()
            return {
                "run": dict(run),
                "markets": [dict(m) for m in markets],
                "orders": [dict(o) for o in orders],
            }

    @app.post("/sim/speed")
    def set_sim_speed(body: SetSpeedRequest) -> dict:
        from paddock.sim.harness import ACTIVE_RUN_SPEEDS

        if body.run_id is not None:
            control = ACTIVE_RUN_SPEEDS.get(body.run_id)
            if control is None:
                raise HTTPException(404, f"No active run {body.run_id!r}")
        elif len(ACTIVE_RUN_SPEEDS) == 1:
            control = next(iter(ACTIVE_RUN_SPEEDS.values()))
        elif not ACTIVE_RUN_SPEEDS:
            raise HTTPException(409, "No run in progress")
        else:
            raise HTTPException(409, "Multiple runs in progress — pass run_id")

        control.value = body.speed
        return {"speed": control.value}

    @app.post("/sim/start", status_code=202)
    def start_sim(body: StartSimRequest) -> dict:
        global _run_thread

        from paddock.config.engine_config import load_engine_config
        from paddock.config.strategies_config import load_strategy_params
        from paddock.sim.harness import (
            FillModelError,
            discover_market_files,
            run_simulation,
            validate_fill_model,
        )
        from paddock.strategies.registry import get_strategy_class

        with _run_lock:
            if _run_thread is not None and _run_thread.is_alive():
                raise HTTPException(409, "A run is already in progress in this process")

            request_settings = get_settings()

            try:
                strategy_cls = get_strategy_class(body.strategy)
            except ValueError as e:
                raise HTTPException(400, str(e)) from e

            data_path = Path(body.data_path)
            if not data_path.is_absolute():
                data_path = Path(request_settings.data_dir) / data_path
            market_files = discover_market_files(data_path)
            if not market_files:
                raise HTTPException(400, f"No market files found under {data_path}")

            engine_config = load_engine_config()
            resolved_fill_model = body.fill_model or engine_config.fill_model
            try:
                validate_fill_model(resolved_fill_model, market_files, Path(request_settings.data_dir))
            except FillModelError as e:
                raise HTTPException(400, str(e)) from e

            run_id = uuid4().hex
            strategy_kwargs = load_strategy_params(body.strategy)

            def _execute() -> None:
                try:
                    run_simulation(
                        strategy_cls,
                        market_files,
                        speed=body.speed,
                        commission_rate=engine_config.commission_rate,
                        fill_model=resolved_fill_model,
                        data_dir=Path(request_settings.data_dir),
                        mode=request_settings.mode.value,
                        strategy_kwargs=strategy_kwargs,
                        run_id=run_id,
                    )
                except Exception:
                    logger.exception("Sim run %s failed", run_id)
                    bus.publish(
                        LogEvent(level=LogLevel.ERROR, msg=f"Run {run_id} failed — see server logs")
                    )

            _run_thread = threading.Thread(
                target=_execute, name=f"paddock-sim-{run_id}", daemon=True
            )
            _run_thread.start()

        return {"run_id": run_id, "market_count": len(market_files), "fill_model": resolved_fill_model}

    @app.websocket("/events")
    async def events_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({"type": "snapshot", "data": bus.snapshot()})
        queue = bus.subscribe()
        try:
            while True:
                event = await queue.get()
                await websocket.send_json(event.model_dump(mode="json"))
        except WebSocketDisconnect:
            pass
        except asyncio.CancelledError:
            raise
        finally:
            bus.unsubscribe(queue)

    return app


app = create_app()
