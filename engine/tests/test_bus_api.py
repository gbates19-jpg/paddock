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
    app = create_app()
    client = TestClient(app)
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
