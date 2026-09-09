# Run plan: does BaselineFavouriteScalp have an edge?

> **Methodology correction (added later, see `docs/strategy-research.md`):**
> the 40-market pilot sample below is drawn from *inside* the same
> 989-market population the final batch result is computed on — not a
> separate, untouched sample. An independent reviewer correctly flagged
> this as research leakage. It doesn't make the t-stat below arithmetically
> wrong, but this document's numbers should be read as **exploratory, not
> a leakage-safe held-out test**. `docs/strategy-research.md`'s
> "Methodology correction" section and its Results table re-evaluate
> `BaselineFavouriteScalp` (unchanged, no re-tuning) on a proper held-out
> slice (`engine/scripts/held_out_split.py`) alongside the three candidate
> strategies — that comparison, not this document alone, is the one to
> trust for a verdict.

Every number in this document below "Pilot pass" is either read off disk
before running anything, or comes from a small real pilot run used only to
ground the statistics — nothing here is guessed. The full batch's results
are appended to the end of this file once it completes.

## The question

One run's P&L is a single draw from a distribution dominated by individual
race variance, not strategy edge — it says nothing. `docs/phase1.md`
already sets the bar this build needs before real stake: agreement over
`>=300 markets`. This is that batch, run in `replay` mode against real
historic data, aimed at the same sample size for the same reason: with
enough markets, the *mean* per-market P&L's standard error becomes small
enough that a real edge (or the lack of one) is distinguishable from
noise.

## Data slice chosen, and why

**All 989 GB `WIN` markets in the Pro-tier Aug/Jul 2015 batch already
unpacked locally** (`data/pro/2015/07` + `data/pro/2015/08`, confirmed via
`data/manifest.jsonl`: 989 rows with `data_plan=pro`, `market_type=WIN`,
`country_code=GB`, spanning `2015-07-31T16:35Z` .. `2015-08-31T17:05Z`).

Why this slice and not the Sep 2026 data also on disk:

- `fill_model=ladder` (flumine's real order-book-depth + traded-volume
  matching — the only fill model that produces an actual backtest rather
  than an optimistic approximation, see README.md "Fill models") needs
  Advanced or Pro plan data. The 2026 Advanced batch (`data/advanced`)
  exists but is small — nowhere near 300 markets — and 2026 Basic
  (`data/basic`) doesn't carry order-book depth at all (`ltp` only),
  so it can't run `ladder` regardless of size.
- The Aug 2015 Pro batch is the only thing on disk that's both
  ladder-capable *and* large enough on its own: 989 markets, comfortably
  over the 300-market gate with margin to spare, and it's free/already
  purchased (see README.md's Data section on Betfair's plan-aging), so
  running all of it costs nothing extra to acquire.
- Using the *entire* local Pro batch rather than a hand-picked subset
  avoids introducing a selection bias of our own on top of whatever bias
  already exists in which races got captured in this archive.

989 markets, all `GB` `WIN`, all real 2015 historic races — not
synthetic, not cherry-picked.

## Runtime estimate (measured, not guessed)

Benchmarked the real CLI (`paddock sim run --strategy baseline
--fill-model ladder`) against random samples of the same files, at
`--speed 0` ("as fast as possible" — no artificial pacing sleep; realism
of playback speed only matters for the live control room UI, not for a
batch backtest nobody is watching tick-by-tick):

| sample  | market-book updates | wall time | rate |
|---|---|---|---|
| 3 files  | 137,699    | 3.76s  | ~36,600/s |
| 20 files | 628,654    | 13.44s | ~46,760/s |
| 40 files | ~893,000   | 28.58s | ~31,200/s |

(Throughput varies with per-file density, not just file count — Pro
market files range from ~9.8k to ~63.7k updates each, mean 32,310, so
sample-to-sample rate wobbles; ~35,000-45,000 updates/sec is the
reasonable range to plan around.)

Full batch: 989 files, 31,954,227 total updates (sum of
`update_count` across all 989 manifest rows). At ~40,000 updates/sec,
**expected wall time is roughly 13-16 minutes**. This is why the answer
to "more if it's cheap to run" (from the brief) is: run the entire local
batch, not a 300-market subset of it — the marginal cost of the extra
~2.3x markets over the 300 floor is a few extra minutes, not a few extra
hours.

## What "enough to be meaningful" means numerically

For `n` independent market outcomes with per-market P&L standard
deviation `σ`, the standard error of the *mean* per-market P&L is
`σ/√n`. A single run (`n=1`) has `SE = σ` — the entire spread of outcomes
*is* the uncertainty, which is exactly why one run says nothing about
edge vs. variance.

To ground `σ` in something real rather than a guess, a 40-market
subsample of this exact population (not held out — it's included in the
full 989, used here only to pre-register the expected precision before
committing to the full run) was run through the identical strategy/fill
model:

- n = 40, mean per-market P&L (after commission) = **-0.134**,
  sample stdev = **0.577**, SE = 0.577/√40 = **0.091**
- Outcome split: 11 markets net positive, 6 net negative, 23 net
  ~exactly flat (all 40 placed exactly 2 orders — entry + exit; "flat"
  means the exit price barely differed from the entry price, a real
  scratch trade, not a missing one — see e.g. market `1.119786510`:
  back @2.5 matched profit -2.0, lay @2.46 matched profit +2.0, nets to
  0.0. Not a bug, just a scalp that captured ~no spread that day.)

Projecting that same σ (0.577) to the full n=989: **SE ≈ 0.577/√989 ≈
0.018** per market. That's roughly 5x tighter than the 40-market pilot's
SE, and means a true mean edge as small as ~£0.04-0.05/market (on a £2
stake — a 2-2.5% edge per trade) would already sit ~2-3 standard errors
from zero at this sample size, i.e. distinguishable from "no edge" rather
than buried in noise. This is the concrete sense in which 989 markets
(vs. the 300-market floor) is "enough to say something," not just a
round number — though see the caveats in the final verdict below for
what this statistical significance does and doesn't establish.

## Command run

```
cd engine
uv run paddock sim run --strategy baseline --data ../data/pro/2015 \
  --speed 0 --fill-model ladder
```

`commission_rate` is `config/engine.yaml`'s default (0.02, Gary's real
account rate — see README's Fill models section), not overridden.
`--speed 0` per the runtime section above. Writes into the real
`data/runs.db` (no `PADDOCK_DATA_DIR` override) via the CLI's normal path,
one run_id covering all 989 markets (`--show-orders` was omitted — it
only affects CLI printing at exit, not persistence, and dumping ~2,000
order rows to a terminal buys nothing here; every order was still written
to `run_orders` and is queried directly below).

---

## Result

Ran clean: `run_id=39ce5ac9ba3043358dfcb63a8812fd34`, 989/989 markets,
no crashes. All numbers below are computed directly from `run_markets`/
`run_orders` for that run_id, not estimated.

| | |
|---|---|
| Markets | 989 |
| Gross P&L (before commission) | -£46.24 |
| Commission | £0.56 |
| **Net P&L** (`runs.run_pnl`) | **-£46.80** |
| Mean per-market P&L | **-£0.0473** |
| Sample stdev (per-market P&L) | £0.5226 |
| Standard error of the mean | £0.0166 |
| **t-stat** (mean / SE) | **-2.85** |
| Net positive markets | 235 (23.8%) |
| Net negative markets | 99 (10.0%) |
| Net ~flat markets | 655 (66.2%) |
| Best / worst single market | +£5.59 / -£10.40 |

### Verdict

**This is a real, statistically significant negative result, not noise.**
At n=989 the mean per-market P&L sits **~2.85 standard errors below
zero** — comfortably past the ~2 that the pre-registered SE math above
called "distinguishable from no edge." The honest reading is not "no
edge detected" but **"a systematic negative edge over this batch"**: this
deliberately-dumb baseline loses money on average, net of commission,
consistently enough across 989 independent markets that it isn't
explained by the variance of individual race outcomes.

What this does and doesn't prove:

- It's specific to **this exact batch**: 2015 Pro-tier historic GB WIN
  markets, replayed through the `ladder` fill model, one particular
  version of `BaselineFavouriteScalp` with `config/strategies.yaml`'s
  current parameters (£2 stake, 5-min entry, 2-tick exit target, 3-tick
  closer slippage budget). It is **not** a finding about Betfair's
  exchange in general, about the `ladder` fill model's realism, or about
  scalp strategies as a category — just about this strategy, on this
  data, as currently tuned.
- It's historic replay against **delayed, aged data** (2015), not live
  market conditions a decade later — liquidity, bet volume, and
  favourite-backing behaviour on the exchange today aren't guaranteed to
  resemble 2015's.
- 989 markets is enough to say the *mean* is reliably negative on *this*
  batch; it is not enough, on its own, to rule out that some sub-segment
  (particular odds ranges, going, field size, time of day) is actually
  profitable while others drag the average down — that's a follow-up
  analysis, not something this run answers.

### The 66% flat-trade rate, looked into

Worth understanding, as flagged — it's mostly benign, but not entirely:

- **977 of 989 markets** placed the expected clean 2-leg trade (entry +
  exit). Most of the 655 "flat" markets are inside this group: entry and
  exit matched at prices only ~1 tick apart (the same pattern seen in the
  40-market pilot, e.g. back @2.5 / lay @2.46 netting to exactly £0.00
  before commission) — real completed round-trips that simply didn't
  capture enough spread to clear a profit or loss, not missing trades.
  This is basic baseline economics, not a bug: a 1-tick-wide scalp nets
  to ~zero whenever the price doesn't move by more than that tick in the
  5-minute entry-to-exit window, which this data says happens often.
- **7 markets** never got the entry matched at all (correctly recorded as
  flat, zero exposure ever taken — the back price it wanted just never
  traded).
- **4 markets had a real, non-flat problem**: entry matched, but neither
  the exit nor the closer's retry loop ever managed to hedge it before
  the market closed, leaving a fully naked position that landed wherever
  the runner happened to finish (2 of these are among the 99 losses at
  exactly -£2.00 = the raw stake, 1 is among the 235 wins at +£5.59 —
  pure luck of an unhedged bet, not scalp edge). 3 of the 4 exhausted all
  3 closer retries and correctly logged `Position unhedged` (working as
  designed — see README's Sim section). The 4th
  (`1.120272311`) stopped after only 1 retry with no `Position unhedged`
  log at all: its second closer attempt was rejected outright
  (`STRATEGY_EXPOSURE: live_trade_count (2) >= max_live_trade_count (2)`)
  because the prior unmatched attempt hadn't been confirmed-cancelled
  before the next one was placed — a real gap in the closer's retry loop
  (it can lose a retry silently to its own exposure cap rather than
  logging the give-up), worth fixing before relying on the closer near
  illiquid closes, though with only 4 markets affected out of 989 it
  changes nothing about the headline numbers or verdict above.
