# PADDOCK

Betfair exchange trading pipeline (Phase 0) — free delayed data, full simulation,
and a live visual control room. Real-money order placement is physically disabled
in this build; see `engine/src/paddock/config/settings.py` and `docs/phase1.md`.

Status: build in progress. This README will be filled in properly once the full
stack (engine, UI, data pipeline, docker) is in place.

## Engine (step 1 done)

```
cd engine
uv sync
uv run pytest
uv run paddock api        # serves REST + /events websocket on :8000
```

## UI (step 1 done)

```
cd ui
npm install
npm run dev                # :5173, connects to ws://localhost:8000/events
npm run dev -- --open '/?demo=1'   # runs with no engine, bundled recorded stream
```
