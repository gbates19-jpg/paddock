from fastapi.testclient import TestClient

from paddock.api.main import create_app
from paddock.bus.bus import bus
from paddock.bus.events import WorkerHeartbeat, WorkerState


def test_worker_heartbeat_roundtrip_serialization():
    event = WorkerHeartbeat(name="stream", state=WorkerState.BUSY, last_latency_ms=12.5)
    dumped = event.model_dump(mode="json")
    assert dumped["type"] == "worker.heartbeat"
    assert dumped["name"] == "stream"
    assert dumped["state"] == "busy"


def test_events_ws_sends_snapshot_then_broadcasts():
    # `with TestClient(app) as client:` (not a bare TestClient(app)) is
    # load-bearing here: only entering the client itself as a context
    # manager runs the ASGI lifespan, which is what calls
    # bus.bind_loop(...). Without it this test would still pass, but by
    # accident — publish() would take its pre-bind synchronous fallback
    # path instead of the real call_soon_threadsafe one, so a regression
    # in the thread-safe marshalling (see paddock.bus.bus's module
    # docstring, and tests/test_bus_thread_safety.py) wouldn't show up
    # here at all.
    with TestClient(create_app()) as client:
        with client.websocket_connect("/events") as ws:
            first = ws.receive_json()
            assert first["type"] == "snapshot"

            bus.publish(WorkerHeartbeat(name="executor", state=WorkerState.IDLE))
            second = ws.receive_json()
            assert second["type"] == "worker.heartbeat"
            assert second["name"] == "executor"


def test_runs_endpoint_empty_when_no_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PADDOCK_DATA_DIR", str(tmp_path))
    app = create_app()
    client = TestClient(app)
    resp = client.get("/runs")
    assert resp.status_code == 200
    assert resp.json() == []
