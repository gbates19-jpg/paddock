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

**Data plan matters for matching, confirmed against a real Basic Plan
download:** Basic Plan historic files carry `ltp` only — no `atb`/`atl`
(order-book depth) and no `trd` (traded-volume ladder), which flumine's
native simulated matching requires (a limit order backtest against Basic
Plan data otherwise always settles `size_matched == 0`, regardless of
price). `paddock data unpack` auto-detects this per market file (byte-scan
for `atb`/`atl`/`trd`) and records it in `<dest>/manifest.jsonl`. See
**Fill models** below for how `sim run` handles it.

## Fill models (decision, step 2.5)

`config/engine.yaml`'s `fill_model` picks how orders get simulated fills:

- **`ladder`** (default) — flumine's native order-book-depth + traded-volume
  matching. Needs Advanced/Pro plan data or a live stream. `sim run`
  **refuses to run** (clear error naming the files) if any loaded market
  file is Basic Plan data — see `paddock.sim.harness._validate_fill_model`.
- **`ltp_cross`** — optimistic approximation for Basic Plan data: a limit
  order is assumed fully matched at its own price on the first tick `ltp`
  crosses it (BACK: `ltp >= price`; LAY: `ltp <= price`). No partial fills,
  no queue position. Implemented as a `SimulatedOrder`/`SimulatedMiddleware`
  subclass (`paddock.sim.fill_models`) — not a flumine patch. **P&L under
  this model is an optimistic upper bound, not a backtest result** — every
  `runs.db` row, every `pnl.update` bus event, and the UI's mode badge
  carry `fill_model` so this is never silently conflated with a real
  result (the badge reads e.g. `REPLAY · ltp_cross (optimistic)`).

`sim run --fill-model` overrides the config default per run. Using
`ltp_cross` on data that actually supports `ladder` isn't fatal, just
logged as a loud warning (you're leaving a real backtest on the table).

## Sim (step 2)

```
cd engine
uv run paddock sim run --strategy baseline --data ../data/2026/09 --speed 20 --fill-model ltp_cross
```

`--speed` is market-seconds per real-second (0 = as fast as possible).
`passive` is a diagnostic strategy that places no orders — useful for
validating the pipeline before a real strategy exists. `baseline`
(`BaselineFavouriteScalp`, step 3) is deliberately dumb: backs the
favourite ~5 minutes before off, lays 2 ticks lower, cancels whatever's
unmatched 30s before off. Its price-reading is fill-model-agnostic (reads
the order-book ladder when present, falls back to `ltp` when it's empty) —
it's the *engine*, not the strategy, that enforces which fill_model a given
run is allowed to use. Params live in `config/strategies.yaml`. Results
land in `<PADDOCK_DATA_DIR>/runs.db`, readable via the API's `/runs`
endpoints.

## Docker

Not written yet (step 5). When it lands: **UNTESTED** — this Mac doesn't
have Docker installed. Consider OrbStack (lighter-weight Docker Desktop
alternative for macOS) over Docker Desktop when you get to it.
