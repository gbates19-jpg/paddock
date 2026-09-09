# Strategy research: does anything here actually have an edge?

Gary's brief, verbatim: *"so how do we make this more profitable it needs
to be a expert not a dummy! Loss of money is ok im not looking for
perfection just not an idiot profit is what we are after."* He signed off
on the research-driven option: build several real candidate strategies,
each grounded in an actual documented reason to expect edge, backtest
them properly, and keep whichever (if any) actually shows a real edge on
the data we have. This is not a search for a guaranteed winner — a
legitimate, honestly-reported negative result is an acceptable outcome of
this exercise, not a failure of it.

## Methodology correction: research leakage (read this before the numbers)

An independent reviewer (Jeff, a colleague of Gary's) checked this work
and found a real methodological flaw, not a style nitpick: `docs/run-plan.md`'s
40-market pilot sample sits *inside* the same 989-market population later
used to score the baseline, and every strategy below had its parameters
— the favourite-longshot lay threshold, the drift z-score window, the
market maker's spread rule — chosen after inspecting samples drawn from
that *same* population. The arithmetic in every t-stat quoted is correct,
but the same data shaped both what got built and how it was scored, which
means the original claim of "no exploitable edge on this data" was stated
with more confidence than the methodology actually supports.

**The fix, applied from this point forward**: `engine/scripts/held_out_split.py`
partitions the 989 markets by calendar date (whole race days, in
Europe/London local time, never split mid-day — meetings on the same day
can share a common regime) into a calibration slice (2015-07-31 ..
2015-08-06, 189 markets, 19.1%) and a held-out slice (2015-08-07 ..
2015-08-31, 800 markets, 80.9%). This split was drawn from date
boundaries alone, before looking at any strategy's performance on either
side. `engine/scripts/run_held_out_eval.py` re-evaluates all four
strategies — baseline included — on the held-out slice only, using each
strategy's already-committed `config/strategies.yaml` parameters
unchanged. **The held-out slice is the actual verdict from here on**; it
will not be inspected again to tune anything.

The original full-989-market figures below (this doc and
`docs/run-plan.md`) are kept, not deleted — they're real numbers, and
they're what actually informed the strategies' designs — but they're
**exploratory / calibration-contaminated, not a valid held-out test**.
Where the two disagree, the held-out numbers in the Results section are
the ones to trust. Jeff's framing, which this doc now uses instead of the
stronger original claim: *these specific strategies/parameters/execution
assumptions have not shown an edge on this data; consistent with a
difficult market, not proof of one.*

## Baseline, for context (exploratory number; see held-out re-evaluation below)

`BaselineFavouriteScalp` was always documented as a deliberately dumb
pipeline-proving stub, not a real strategy — see its module docstring and
`docs/run-plan.md`. Its result stands exactly as already reported and is
not touched here:

- n = 989 markets (full batch, exploratory), mean per-market P&L
  **-£0.0473**, stdev £0.5226, SE £0.0166, **t = -2.85** — a
  statistically real *negative* edge on this exploratory figure.

It's included here purely as the fixed point every new strategy was
designed against — same data, same commission, same `ladder` fill model.
Per the methodology correction above, baseline is *also* re-evaluated on
the held-out slice in the Results section below, on equal footing with
the three candidates — the number above predates that split and isn't
itself contaminated by any calibration choice (baseline's parameters were
never tuned against this data at all, dumb-by-design), but it's still a
full-989-market figure, not held-out, so it's re-run for a fair
side-by-side comparison.

## The three candidates

All three live under `engine/src/paddock/strategies/`, registered in
`paddock.strategies.registry`, independently runnable via `paddock sim
run --strategy <name>` exactly like baseline. None of them are wired into
any live/UI-facing default — that's a separate decision, made after
seeing these numbers, not before.

1. **`drift_following` (`DriftSteamFollower`)** — trades with the
   direction of a runner's own late price movement (shortening = back,
   drifting out = lay), sized as a z-score against that runner's *own*
   recent volatility rather than a fixed tick count.
2. **`favourite_longshot_bias` (`FavouriteLongshotBias`)** — lays runners
   above a price threshold, testing whether the classic fixed-odds
   favourite-longshot bias survives on an exchange's own BSP.
3. **`market_maker` (`LadderMarketMaker`)** — quotes passively inside the
   back/lay spread on the favourite, profiting (or not) from the spread
   and queue priority rather than taking a directional view. Needs real
   order-book depth (`ladder` fill model) to mean anything at all — see
   its feasibility check below.

## Data slice (identical to the baseline run)

Same batch as `docs/run-plan.md`: all 989 real GB `WIN` markets in the
local Aug/Jul 2015 Pro-tier archive (`data/pro/2015`), the only local data
both large enough and ladder-capable (real order-book depth + traded
volume — see README's Fill models section). Same `commission_rate=0.02`,
same `fill_model=ladder`, same `--speed 0` (no artificial pacing —
nobody's watching a batch backtest tick-by-tick). Full batch every time,
every strategy — no subset was ever picked to flatter a result.

## Calibration — checking against the data before picking numbers

**This whole section is the calibration-contaminated part** — see the
methodology correction above. Per the brief, nothing below is a guessed
magic number; each was checked against a real sample first, which is
exactly the problem: those samples were drawn from the same 989-market
population the strategies are ultimately scored on, not from the
calibration-only slice `held_out_split.py` now defines. This section is
kept as-is because it's an honest record of *why* each strategy is
shaped the way it is, not because it's independent evidence of edge —
that's what the Results section's held-out numbers are for.

### Favourite-longshot bias: does it show up in our own BSP?

Before writing any strategy code, every settled market's final BSP +
result was pulled directly from each file's own closing `marketDefinition`
(989 markets, 8,417 individual runner results with a valid BSP) and
bucketed by price. Overround came out to ~1.004 (BSP is close to a fair,
vig-free auction price on this exchange — not guaranteed the way a
fixed-odds bookmaker's overround is), so any bucket-level departure from
`1/BSP` here is a real candidate mispricing, not just built-in margin.

| BSP bucket | n | implied p | actual p | LAY mean (unit stake) | t |
|---|---|---|---|---|---|
| 1.01-2.0 | 107 | 0.617 | 0.570 | +0.096 | +1.22 |
| 2.0-3.0 | 331 | 0.395 | 0.381 | +0.039 | +0.57 |
| 3.0-4.0 | 491 | 0.286 | 0.289 | -0.010 | -0.14 |
| 4.0-6.0 | 1062 | 0.203 | 0.209 | -0.024 | -0.38 |
| 6.0-10.0 | 1679 | 0.130 | 0.130 | +0.004 | +0.06 |
| 10.0-20.0 | 2140 | 0.073 | 0.071 | +0.031 | +0.40 |
| 20.0-50.0 | 1608 | 0.035 | 0.038 | -0.041 | -0.30 |
| 50.0-1000.0 | 968 | 0.010 | 0.010 | **+0.298** | **+1.31** |

**Honest reading: nothing here clears conventional significance** (every
`|t| < 1.4`) — the classic bias is *not* confirmed outright in this
sample. The one bucket worth building on is the extreme end (BSP >= 50):
largest-magnitude effect, right direction, and — importantly — short
favourites (< 2.0) showed the *opposite* sign from the textbook
prediction (backing them lost money here, weakly), which is exactly the
kind of departure from the assumption the brief warned against baking in
without checking. This is why `FavouriteLongshotBias` only lays above a
threshold (default 50, matching where the signal actually concentrated)
and does **not** add a "back the favourite" leg — our own data didn't
support one.

This BSP-level check is necessarily a different measurement from the
actual strategy's backtest below: BSP is the market's *final* clearing
price, not a price this strategy (or any strategy trading before the off)
could actually transact at. It's a rationale for *what to test*, not a
preview of the backtest's answer.

### Drift/steam: what does "meaningful" mean here?

A 250-market sample (flumine's own historical-stream parsing, not a
hand-rolled diff merger) recorded each runner's best-available-back price
near T-10min and T-2min before the off. Median absolute log-price move
over that 8-minute window was **~0.11** (a ~12% relative change) —
confirms an 8-minute lookback captures real movement, not noise. Decile
analysis on this sample found the single strongest raw t-stat (-2.31) on
the "biggest drift-out" decile, backing at the post-drift price — but
that decile also carried, on average, by far the highest prices in the
sample, which is the same effect the favourite-longshot check above is
already measuring, not necessarily an independent "drift" signal.
Given that confound, `DriftSteamFollower`'s z-score is deliberately
scaled by each runner's *own* recent volatility (not a fixed threshold)
specifically so it isn't just re-detecting the price-level effect above,
and the strategy trades both directions symmetrically rather than
hard-coding "only drift-outs matter" from a small, confounded sample. See
`drift_following.py`'s module docstring for the exact z-score formula.

### Market maker: is this even feasible on this data?

Checked against flumine 3.2.0 source before building anything: a passive
limit order only gets simulated fills via `SimulatedOrder._process_traded`,
which implements a real price-time-priority queue ("traded volume / 2"
clears whatever was resting ahead of you) — and that needs the
traded-volume ladder (`trd`), which only Advanced/Pro plan data carries.
Basic Plan data (`ltp` only) genuinely cannot support this strategy at
all — a version of it built against `ltp_cross` would just be a fake
market maker wearing the name, which is exactly what the brief said not
to build. Our Aug 2015 Pro batch has full depth, so this is real.

Separately (and this is a design-shaping finding, not a feasibility
one): a quick check against the two bundled real Pro fixtures showed the
favourite's spread sits at exactly **1 tick ~99% of the time**. A
"quote strictly inside the spread, otherwise sit out" rule — the first
version written — would therefore have almost nothing to do on the one
runner it trades. The strategy instead joins the touch when the spread is
only 1 tick (the realistic thing to do given how tight this specific
market actually is) and improves inside it when there's genuinely room.
See the market's spread being what it is drove this: was checked before
picking the rule, not adjusted afterward to produce a better number.

### Market maker: bug investigation (a real bug was found and fixed)

The first full-989-market exploratory run of `market_maker` produced
`run_pnl=-£3,131.80`, t=-12.28 — an order of magnitude worse than any
other strategy, and bad enough (a colleague spotted it mid-run,
worsening steadily) to warrant stopping and actually diagnosing it rather
than just reporting it. Three questions, checked in order:

**Is it re-quoting too aggressively (a throttle bug)?** No — traced real
quote-placement timestamps for the single worst market
(`1.119888719`, -£45.20) and confirmed ~5.0-5.2 second gaps between
requotes throughout, exactly matching `requote_interval_seconds=5`. The
throttle works as designed.

**Is it failing to manage inventory/exposure (a real bug)?** **Yes** —
found and fixed. `LadderMarketMaker` quoted both BACK and LAY at the same
fixed `quote_size` (a stake), but LAY *exposure* is `size * (price - 1)`
— liability, not stake — so the same fixed size means larger exposure at
higher prices. `max_order_exposure: 50` was sized for a normal
`quote_size=2` quote (safe up to price 26), but the *flatten* leg's size
is the whole accumulated imbalance, not one quote — confirmed in the
logs as real `STRATEGY_EXPOSURE` rejections on flatten attempts, and
because a rejected flatten attempt doesn't reduce the imbalance, this is
a vicious cycle: each retry stays rejected, the position stays one-sided,
and the closer eventually gives up with a bigger naked residual than a
working market maker should ever carry. **Fix**: raised
`max_order_exposure` to 200 in `config/strategies.yaml` — not the sizing
formula itself, which would have broken the flatten logic's "flat means
BACK-matched-stake == LAY-matched-stake" invariant. 200 is not arbitrary:
confirmed favourite prices never exceed 10 anywhere in the whole
989-market batch (checked against `BaselineFavouriteScalp`'s own entry
prices), so 200 comfortably covers even a badly-imbalanced ~22-unit
flatten at that ceiling — well beyond what healthy two-sided quoting
should ever build up. Verified the fix on an 80-market spot-check:
`STRATEGY_EXPOSURE`-on-exposure rejections were gone.

**Is the simulated fill/queue model just not representing the intended
economics?** Also yes, and this is the *dominant* driver, not the bug
above — the 80-market spot-check with the bug fixed still showed
t=-5.17, confirming the fix removed a confound, not the actual finding.
Traced the worst market's actual matched prices: back fills
volume-weighted-averaged 1.131, lay fills 1.141 — a **consistent 1-tick
giveaway on every round-trip pair**, repeated ~113 times in that one
market (a 10-minute window ÷ the 5s throttle allows at most ~120 quote
cycles — this market used almost all of them). This is arithmetically
unavoidable: two *passive* quotes placed inside the *same* snapshot's
spread necessarily have BACK price < LAY price, and — per the profit
identity `S*(Pback - Play)` if the runner wins, `0` if it loses — that
ordering nets to a loss-or-flat outcome for that pair, never a gain,
*unless* the market moves enough between when each side actually fills
to reverse which one filled at the better price. flumine's queue
simulation (confirmed correct against its own source, not a bug) gives a
brand-new best-in-book quote a starting queue position of ~0, so in this
actively-ticking pre-off data, both sides fill almost immediately, almost
every cycle — meaning the strategy rarely gets the "market moved between
fills" chance that would let it come out ahead, and instead pays the
1-tick giveaway over and over. This is a real, substantive finding about
naive symmetric inside-spread quoting under a realistic queue model, not
an execution-plumbing shortfall — see `market_maker.py`'s module
docstring for the same explanation kept alongside the code.

One separate, smaller, *known and not fixed* limitation: `_ensure_quote`
creates a fresh `Trade` object every time it replaces a quote, and a
handful of `STRATEGY_EXPOSURE: live_trade_count >= max_live_trade_count`
rejections show up from flumine still counting a just-cancelled trade as
live for a short window. This causes occasional missed requote cycles,
not incorrect P&L — left as-is rather than risking a structural rewrite
of the quoting loop this close to the held-out run below.

## Results

_(filled in once the three full-batch runs complete — see the table and
per-strategy verdicts below)_
