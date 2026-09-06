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
npm run dev                # :5173, binds 0.0.0.0 (reachable over Tailscale)
npm run dev -- --open '/?demo=1'   # runs with no engine, bundled recorded stream
```

## Data (step 2)

Historic data is free on the Basic Plan but requires a one-time manual
"purchase" (£0) at https://historicdata.betfair.com before it can be listed
or downloaded — `paddock data fetch` can't do that step for you.

```
cd engine
uv run paddock data unpack /path/to/downloaded.tar --dest ../data
```

Unpacks into `<dest>/<year>/<month>/<market_id>` and prints a summary
(market count, date range, venues, total size). `paddock data fetch`
(the `get_file_list`/`download_file` API path) exists but is **not verified
against a real account** — see the docstring in
`engine/src/paddock/data/historic.py`.

**Known limitation, confirmed against a real Basic Plan download:** Basic
Plan historic files carry `ltp` (last traded price) only — no `atb`/`atl`
(order-book depth) and no `trd` (traded-volume ladder). flumine's simulated
order matching is driven entirely by the traded-volume ladder, so a limit
order backtest against Basic Plan data always settles with
`size_matched == 0`, regardless of price. This doesn't break the pipeline
(the smoke test uses a real Basic Plan file and never places an order), but
it means **step 3's BaselineFavouriteScalp cannot get a meaningful
simulated fill against free data as currently planned** — needs a decision
before that strategy is designed: either backtest against a paid plan with
order-book depth, or adopt an explicit fill-assumption for Basic Plan data
(e.g. "a limit order at or through `ltp` is assumed filled") documented as
a Phase 0 simplification.

## Sim (step 2)

```
cd engine
uv run paddock sim run --strategy passive --data ../data/2026/09 --speed 20
```

`--speed` is market-seconds per real-second (0 = as fast as possible).
`passive` is a diagnostic strategy that places no orders — useful for
validating the pipeline before step 3's real strategy exists. Results land
in `<PADDOCK_DATA_DIR>/runs.db`, readable via the API's `/runs` endpoints.

## Docker

Not written yet (step 5). When it lands: **UNTESTED** — this Mac doesn't
have Docker installed. Consider OrbStack (lighter-weight Docker Desktop
alternative for macOS) over Docker Desktop when you get to it.
