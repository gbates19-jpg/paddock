"""POST /sim/speed is real — it mutates the SpeedControl a running
WallClockPacingMiddleware reads on every tick, not a stub."""
from __future__ import annotations

from fastapi.testclient import TestClient

from paddock.api.main import create_app
from paddock.sim.harness import ACTIVE_RUN_SPEEDS
from paddock.sim.pacing import SpeedControl


def test_set_speed_updates_the_registered_control():
    ACTIVE_RUN_SPEEDS.clear()
    control = SpeedControl(20.0)
    ACTIVE_RUN_SPEEDS["run-1"] = control
    try:
        client = TestClient(create_app())
        resp = client.post("/sim/speed", json={"speed": 500.0, "run_id": "run-1"})
        assert resp.status_code == 200
        assert resp.json() == {"speed": 500.0}
        assert control.value == 500.0
    finally:
        ACTIVE_RUN_SPEEDS.clear()


def test_set_speed_without_run_id_uses_the_sole_active_run():
    ACTIVE_RUN_SPEEDS.clear()
    control = SpeedControl(20.0)
    ACTIVE_RUN_SPEEDS["only-run"] = control
    try:
        client = TestClient(create_app())
        resp = client.post("/sim/speed", json={"speed": 1.0})
        assert resp.status_code == 200
        assert control.value == 1.0
    finally:
        ACTIVE_RUN_SPEEDS.clear()


def test_set_speed_with_no_active_runs_returns_409():
    ACTIVE_RUN_SPEEDS.clear()
    client = TestClient(create_app())
    resp = client.post("/sim/speed", json={"speed": 20.0})
    assert resp.status_code == 409


def test_set_speed_unknown_run_id_returns_404():
    ACTIVE_RUN_SPEEDS.clear()
    client = TestClient(create_app())
    resp = client.post("/sim/speed", json={"speed": 20.0, "run_id": "nope"})
    assert resp.status_code == 404
