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

Historic data is free on the Basic Plan; Advanced/Pro are paid (or free
once old enough — Betfair ages plans out over time, confirmed: our real
Aug 2015 Pro-tier purchase was £0). All require a one-time manual
"purchase" at https://historicdata.betfair.com before they can be listed
or downloaded — `paddock data fetch` can't do that step for you.

```
cd engine
uv run paddock data unpack /path/to/downloaded.tar --dest ../data --country GB --market-type WIN
```

Lays out as `<dest>/<plan>/<year>/<month>/<market_id>` — plan
(`basic`/`advanced`/`pro`) comes from a byte-scan of each market's own
content, never the tar's folder labels or filename (see below for why
that matters in practice). `--country`/`--market-type` filter per market
before anything is written to disk; a whole (plan, year, month) group with
nothing matching the country filter is reported, not silently dropped.
Never overwrites: a market_id landing again under the same plan is
hash-compared against what's on disk — identical is skipped quietly,
different is reported as a conflict and left untouched either way. Prints
a per-plan/month summary (market count, date range, venues, size) plus any
skipped-groups/duplicates/conflicts. `paddock data fetch` (the
`get_file_list`/`download_file` API path) exists but is **not verified
against a real account** — see the docstring in
`engine/src/paddock/data/historic.py`.

**Plan detection, confirmed against real downloads of all three tiers:**
- `pro`: full order-book depth — literal `atb`/`atl` keys.
- `advanced`: *compact* best-price-only depth (`batb`/`batl`) plus the
  traded-volume ladder (`trd`) — no full `atb`/`atl`. Easy to mis-detect if
  you only check for `atb`/`atl` literally (their substrings don't appear
  inside `batb`/`batl`).
- `basic`: `ltp` only, none of the above.

Both `advanced` and `pro` carry `trd`, which is what flumine's native
matching actually needs (see **Fill models**) — so both support
`fill_model=ladder`. Only `basic` requires `fill_model=ltp_cross`.

**Pro data is dense**: confirmed on a real Aug 2015 file — ~50ms between
updates, spanning the full pre-off history (one market file: 16k+ updates
across 28 hours, several MB). The manifest records each market's
`update_count` so this is visible without re-scanning; `sim run --speed`
needs to be set much higher for Pro data to replay in a watchable amount
of wall-clock time (confirmed: speed=5000 replays that 28-hour file in
~20s real time, at ~8% CPU — the pacing middleware's per-tick sleep math
is unaffected by density, it's just a lot more ticks to sleep between). A
future Ladder-scene event feed reading this data needs to throttle its own
UI-bound events (e.g. ~10/s per runner) independently of the sim's own
pacing, which runs at native tick density — not yet built (step 4).

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

**Validated against real data, both directions:**
- `ladder` against 6 real Aug 2015 Pro markets: real matched orders at real
  prices, flumine's own `cleared()` P&L, run_pnl=+0.08 across the sample.
  One market needed the flat-invariant's "closer" fallback (exit never
  crossed) and it matched cleanly.
- `ladder` vs `ltp_cross` head-to-head on the *same* 6 real Sept 2026
  Advanced markets: run_pnl was **+0.04 (ltp_cross) vs -1.96 (ladder)** on
  this sample. The entire gap is one market (`1.261733309`) where the
  closer order crossed under `ltp_cross`'s ltp-based rule but never
  actually matched under `ladder` — there was no real traded volume at
  that price before the market closed, so the "naked" back leg lost its
  full stake. **This is a real, load-bearing limitation, not a bug**:
  "close at market" via a resting limit order is only a guarantee under
  `ltp_cross` (crossing is defined by ltp alone). Under `ladder`,
  flat-at-off is only as good as the market's actual liquidity right then
  — a real backtest can still end up with a naked position if nothing
  trades at the closing price in time. `ltp_cross` being the *optimistic*
  model, not `ladder` being broken, is exactly why every P&L number now
  carries which one produced it.

## Sim (step 2-3)

```
cd engine
uv run paddock sim run --strategy baseline --data ../data/advanced/2026/09 --speed 20 --fill-model ltp_cross --show-orders
```

`--speed` is market-seconds per real-second (0 = as fast as possible).
`--show-orders` prints every matched order and each market's `cleared()`
P&L at the end (used for the validation above). `passive` is a diagnostic
strategy that places no orders — useful for validating the pipeline before
a real strategy exists.

`baseline` (`BaselineFavouriteScalp`) is deliberately dumb, sequential
legs with a flat-at-off invariant: place ENTRY (back the favourite) ~5
minutes before off; once entry has any matched size, place EXIT (lay,
sized to exactly what matched, a couple of ticks lower) — never before
entry has actually matched something. At 30s before off: cancel any
unmatched entry remainder; if entry matched but exit doesn't fully cover
it, cancel exit's remainder and place a CLOSER order for the shortfall at
the current crossing price ("accept the red"). Guarantees zero net
position by market close in every reachable scenario *up to the ladder
caveat above* — proven against synthetic market data with exact ltp
control (`tests/test_baseline_flat_invariant.py`), not just real data
where you can't force every scenario to occur.

Price-reading is fill-model-agnostic (reads the order-book ladder when
present, falls back to `ltp` when it's empty) — it's the *engine*, not the
strategy, that enforces which fill_model a given run is allowed to use.
`max_live_trade_count`/`max_order_exposure` are set explicitly in
`config/strategies.yaml` rather than left at flumine's defaults, since this
strategy always runs two concurrent legs by design.

**Trading-control rejections are surfaced, not silently swallowed** —
this is exactly the bug that made the first draft of this strategy look
like it placed nothing (the lay leg violated `max_live_trade_count=1` with
no exception, just a silently-voided order). Confirmed the only place this
is observable: `Market.place_order()`'s own boolean return value at the
call site — neither `LoggingControl` nor any per-order status hook ever
sees a rejected order, since it never reaches `market.blotter` or
`log_control` at all. `paddock.sim.orders.place_order` wraps this: on
rejection it emits an `order.rejected` bus event with the reason, flashes
the `executor` worker heartbeat to `error`, and logs at ERROR. Every
strategy should call through it rather than `market.place_order` directly.

Results land in `<PADDOCK_DATA_DIR>/runs.db`, readable via the API's
`/runs` endpoints.

## Docker

Not written yet (step 5). When it lands: **UNTESTED** — this Mac doesn't
have Docker installed. Consider OrbStack (lighter-weight Docker Desktop
alternative for macOS) over Docker Desktop when you get to it.
