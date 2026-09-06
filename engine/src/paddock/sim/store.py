"""runs.db — one SQLite file, schema matches paddock.api.main's read queries.

Path is always a pathlib.Path; callers pass the directory (Settings.data_dir),
never a hand-built string, so this works regardless of spaces in the repo
path.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    strategy TEXT NOT NULL,
    params TEXT,
    commission_rate REAL NOT NULL,
    fill_model TEXT NOT NULL,
    run_pnl REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_markets (
    run_id TEXT NOT NULL,
    market_id TEXT NOT NULL,
    market_pnl REAL NOT NULL,
    commission REAL NOT NULL,
    bet_count INTEGER NOT NULL,
    PRIMARY KEY (run_id, market_id)
);

CREATE TABLE IF NOT EXISTS run_orders (
    run_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    market_id TEXT NOT NULL,
    selection_id INTEGER,
    side TEXT,
    price REAL,
    size REAL,
    matched_size REAL,
    status TEXT,
    profit REAL,
    role TEXT,
    attempt INTEGER,
    PRIMARY KEY (run_id, order_id)
);
"""


def runs_db_path(data_dir: Path) -> Path:
    return Path(data_dir) / "runs.db"


def open_connection(data_dir: Path) -> sqlite3.Connection:
    """Long-lived connection for a single writer (e.g. one sim run's
    LoggingControl thread). Caller owns commit()/close()."""
    db_path = runs_db_path(data_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


@contextmanager
def connect(data_dir: Path):
    """Short-lived connection for a single read/write, e.g. run setup."""
    con = open_connection(data_dir)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def create_run(
    con: sqlite3.Connection,
    run_id: str,
    strategy: str,
    params: dict,
    commission_rate: float,
    fill_model: str,
    created_at: str,
) -> None:
    con.execute(
        "INSERT INTO runs (run_id, strategy, params, commission_rate, fill_model, run_pnl, created_at) "
        "VALUES (?, ?, ?, ?, ?, 0, ?)",
        (run_id, strategy, json.dumps(params), commission_rate, fill_model, created_at),
    )


def record_market_result(
    con: sqlite3.Connection, run_id: str, market_id: str, market_pnl: float, commission: float, bet_count: int
) -> None:
    con.execute(
        "INSERT OR REPLACE INTO run_markets (run_id, market_id, market_pnl, commission, bet_count) "
        "VALUES (?, ?, ?, ?, ?)",
        (run_id, market_id, market_pnl, commission, bet_count),
    )
    con.execute(
        "UPDATE runs SET run_pnl = run_pnl + ? WHERE run_id = ?",
        (market_pnl - commission, run_id),
    )


def record_order(
    con: sqlite3.Connection,
    run_id: str,
    order_id: str,
    market_id: str,
    selection_id: int,
    side: str,
    price: float,
    size: float,
    matched_size: float,
    status: str,
    profit: float,
    role: str | None = None,
    attempt: int | None = None,
) -> None:
    con.execute(
        "INSERT OR REPLACE INTO run_orders "
        "(run_id, order_id, market_id, selection_id, side, price, size, matched_size, status, profit, role, attempt) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, order_id, market_id, selection_id, side, price, size, matched_size, status, profit, role, attempt),
    )


def get_run_pnl(con: sqlite3.Connection, run_id: str) -> float:
    row = con.execute("SELECT run_pnl FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return row["run_pnl"] if row else 0.0
