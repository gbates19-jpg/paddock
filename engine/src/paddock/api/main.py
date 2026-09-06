"""FastAPI layer: exposes the bus over HTTP + a websocket for the UI.

Step 1 scope: /events websocket (with snapshot-on-connect) and the /runs
read endpoints against runs.db. /sim/* control endpoints are wired up in
step 2 once paddock.sim exists — for now they 404 by omission rather than
faking a response.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from paddock.bus.bus import bus
from paddock.config.settings import get_settings

logger = logging.getLogger(__name__)


def _runs_db_path() -> Path:
    return Path(get_settings().data_dir) / "runs.db"


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
