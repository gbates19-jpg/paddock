"""POST /sim/start: validates synchronously (so a bad request 400s
immediately rather than dying invisibly on a background thread), starts
the real run without blocking the request, guards against a second run
overlapping the first, and — the thing that actually matters for Gary
watching from a phone — a websocket client connected before the run
starts keeps receiving real events for the duration of the run.

Every test here uses `with TestClient(create_app()) as client:` (not a
bare `TestClient(create_app())`) — that's load-bearing, not stylistic.
FastAPI/Starlette's TestClient only runs the ASGI lifespan (startup +
shutdown) when the client itself is entered as a context manager; without
it, `paddock.api.main`'s lifespan never calls `bus.bind_loop(...)`, so
`EventBus.publish()` silently takes its pre-bind synchronous fallback
path instead of the real `call_soon_threadsafe` one — which is exactly
the unsafe direct-`put_nowait`-from-a-foreign-thread path this feature
exists to avoid. That was found the hard way while writing this file:
the streaming test below genuinely hung against a bare `TestClient(app)`,
which is a live demonstration of why the marshalling in
paddock.bus.bus.EventBus matters, not a hypothetical.

POST /sim/stop is intentionally not covered here: it's not implemented,
see paddock.api.main's module docstring for why that's a deliberate
omission rather than a gap.
"""
from __future__ import annotations

import queue as queue_module
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

import paddock.api.main as api_main
import paddock.sim.harness as harness
from paddock.api.main import create_app

SAMPLE_MARKET = Path(__file__).parent / "resources" / "1.261851533"


def _receive_json_with_timeout(ws, timeout: float = 5.0):
    """TestClient's receive_json() blocks with no timeout of its own — if
    an expected event never shows up (a real bug, not just slow CI), a
    bare call here would hang the whole test run rather than fail it. The
    receiving thread is a daemon: if it never returns we still fail fast
    with a clear TimeoutError instead of it holding the process open."""
    result: queue_module.Queue = queue_module.Queue(maxsize=1)

    def _recv() -> None:
        try:
            result.put(("ok", ws.receive_json()))
        except Exception as e:  # noqa: BLE001 - relayed to the caller, not swallowed
            result.put(("err", e))

    threading.Thread(target=_recv, daemon=True).start()
    try:
        kind, value = result.get(timeout=timeout)
    except queue_module.Empty:
        raise TimeoutError(f"no websocket message within {timeout}s") from None
    if kind == "err":
        raise value
    return value


def _join_active_run(timeout: float = 5.0) -> None:
    thread = api_main._run_thread
    if thread is not None:
        thread.join(timeout=timeout)


def test_start_rejects_unknown_strategy(tmp_path, monkeypatch):
    monkeypatch.setenv("PADDOCK_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as client:
        resp = client.post(
            "/sim/start",
            json={"strategy": "not-a-real-strategy", "data_path": str(SAMPLE_MARKET)},
        )
        assert resp.status_code == 400
        assert "Unknown strategy" in resp.json()["detail"]


def test_start_rejects_a_data_path_with_no_market_files(tmp_path, monkeypatch):
    monkeypatch.setenv("PADDOCK_DATA_DIR", str(tmp_path))
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with TestClient(create_app()) as client:
        resp = client.post("/sim/start", json={"strategy": "passive", "data_path": str(empty_dir)})
        assert resp.status_code == 400
        assert "No market files found" in resp.json()["detail"]


def test_start_rejects_ladder_fill_model_on_basic_plan_data(tmp_path, monkeypatch):
    # A real, pre-existing gotcha this test tripped over and had to route
    # around, not something introduced here: paddock.data.manifest.data_plan_for's
    # manifest-lookup fast path keys purely on filename, with no content
    # check — if PADDOCK_DATA_DIR pointed at the real repo data/ dir (which
    # has its own manifest.jsonl), and that manifest happened to already
    # contain an unrelated real market that coincidentally shares this
    # bundled fixture's market_id, the lookup would silently return the
    # WRONG plan for the fixture. Isolating PADDOCK_DATA_DIR to an empty
    # tmp_path (no manifest.jsonl at all) forces the real byte-scan
    # fallback instead, which is what every test in this file needs
    # regardless of this specific bug.
    monkeypatch.setenv("PADDOCK_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as client:
        try:
            resp = client.post(
                "/sim/start",
                json={"strategy": "passive", "data_path": str(SAMPLE_MARKET), "fill_model": "ladder"},
            )
            assert resp.status_code == 400
            assert "fill_model=ladder requires" in resp.json()["detail"]
        finally:
            _join_active_run()


def test_start_returns_run_id_immediately_without_blocking(monkeypatch, tmp_path):
    """run_simulation is swapped for a fake that blocks until released —
    proves the endpoint itself doesn't wait for the (real, much longer)
    FlumineSimulation.run() loop before responding."""
    monkeypatch.setenv("PADDOCK_DATA_DIR", str(tmp_path))
    release = threading.Event()
    started = threading.Event()

    def fake_run_simulation(*args, **kwargs):
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(harness, "run_simulation", fake_run_simulation)

    with TestClient(create_app()) as client:
        try:
            start = time.monotonic()
            resp = client.post(
                "/sim/start",
                json={"strategy": "passive", "data_path": str(SAMPLE_MARKET), "fill_model": "ltp_cross"},
            )
            elapsed = time.monotonic() - start

            assert resp.status_code == 202
            assert elapsed < 2.0, f"POST /sim/start blocked for {elapsed:.2f}s — should return immediately"
            assert resp.json()["run_id"]
            assert started.wait(timeout=2), "background thread never called run_simulation"
        finally:
            release.set()
            _join_active_run()


def test_start_rejects_a_second_run_while_one_is_in_progress(monkeypatch, tmp_path):
    monkeypatch.setenv("PADDOCK_DATA_DIR", str(tmp_path))
    release = threading.Event()
    started = threading.Event()

    def fake_run_simulation(*args, **kwargs):
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(harness, "run_simulation", fake_run_simulation)

    with TestClient(create_app()) as client:
        body = {"strategy": "passive", "data_path": str(SAMPLE_MARKET), "fill_model": "ltp_cross"}
        try:
            first = client.post("/sim/start", json=body)
            assert first.status_code == 202
            assert started.wait(timeout=2)

            second = client.post("/sim/start", json=body)
            assert second.status_code == 409
        finally:
            release.set()
            _join_active_run()


def test_sim_start_streams_real_events_to_a_connected_websocket_client(monkeypatch, tmp_path):
    """The actual point of this whole feature: a client connected before
    the run starts must see run.config (mode badge / speed control) and
    the real market lifecycle events as they happen — not just the
    catch-up snapshot. Runs the real bundled fixture through the real
    run_simulation, no mocks."""
    monkeypatch.setenv("PADDOCK_DATA_DIR", str(tmp_path))

    with TestClient(create_app()) as client:
        try:
            with client.websocket_connect("/events") as ws:
                snapshot = _receive_json_with_timeout(ws)
                assert snapshot["type"] == "snapshot"

                resp = client.post(
                    "/sim/start",
                    json={
                        "strategy": "passive",
                        "data_path": str(SAMPLE_MARKET),
                        "fill_model": "ltp_cross",
                        "speed": 0,
                    },
                )
                assert resp.status_code == 202
                run_id = resp.json()["run_id"]

                seen_types: set[str] = set()
                run_config_run_id = None
                for _ in range(200):  # bounded: never spin forever on a stalled stream
                    if run_config_run_id == run_id and "market.close" in seen_types:
                        break
                    event = _receive_json_with_timeout(ws, timeout=10.0)
                    seen_types.add(event["type"])
                    if event["type"] == "run.config":
                        run_config_run_id = event["run_id"]

                assert run_config_run_id == run_id, f"never saw run.config for {run_id}; saw {seen_types}"
                assert "market.open" in seen_types
                assert "market.close" in seen_types
        finally:
            _join_active_run()
