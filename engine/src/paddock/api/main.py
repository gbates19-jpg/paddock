"""FastAPI layer: exposes the bus over HTTP + a websocket for the UI.

/sim/speed is real: it reaches whichever run(s) are currently in progress
via paddock.sim.harness.ACTIVE_RUN_SPEEDS (a run_id -> SpeedControl
registry populated by run_simulation) and mutates the SpeedControl that
run's WallClockPacingMiddleware reads on every tick — no restart needed.
/sim/start and /sim/stop are NOT implemented (still step-1-era gaps, not
newly introduced) — starting a run means driving a blocking
FlumineSimulation.run() loop from a background thread/task, and stopping
one mid-replay has no clean hook in flumine without patching it; both are
real, scoped-out follow-ups, not silently faked here.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from paddock.bus.bus import bus
from paddock.config.settings import get_settings

logger = logging.getLogger(__name__)


def _runs_db_path() -> Path:
    return Path(get_settings().data_dir) / "runs.db"


class SetSpeedRequest(BaseModel):
    speed: float
    run_id: str | None = None  # omit when exactly one run is in progress


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PADDOCK API starting (mode=%s)", get_settings().mode.value)
    yield


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
