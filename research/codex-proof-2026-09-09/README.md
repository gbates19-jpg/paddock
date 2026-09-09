# Paddock research proof

This isolated Python-standard-library diagnostic reads Paddock historical data without importing its runtime or writing to its repository. It is a correction demonstration, not a strategy or a trading system.

Run tests:

```sh
python3 -B -m unittest discover -s research/codex-proof-2026-09-09 -v
```

Replay (choose a new destination; existing output directories are refused):

```sh
python3 -B research/codex-proof-2026-09-09/proof.py . /tmp/paddock-proof-new-run
```

The bundled input-markets.json freezes the 989-file population used by the existing full in-play report. Supply the repository containing those raw files as the first argument. Initial schedule changes quarantine a market rather than retrospectively choosing a schedule. Snapshots use the last complete timestamp at or before their target, including every update sharing that timestamp. No observations are fabricated after EOF. Malformed JSON, out-of-order records, unexpected market IDs and unsupported indexed ladders quarantine the entire file. Complete streams are read and SHA-256 fingerprinted.

The diagnostic retains OPEN, pre-in-play markets and ACTIVE runners, uncrossed two-sided quotes up to odds 100, a stream observation at most five seconds old, no intervening recorded runner removal, and displayed capacity for a unit entry and equal-profit exit hedge. Stream age measures market update age, not guaranteed runner quote freshness. Removal intervals and missing exits are exclusions, not simulated failed trades: this can introduce selection bias and means these averages must not be interpreted as attainable strategy returns.

BACK consumes available-to-back at entry and available-to-lay at exit; LAY does the reverse. BACK profit per initial stake is entry/exit − 1. LAY profit per initial lay stake is 1 − entry/exit, with a separate initial-liability-normalized column. Commission is 2% on each positive hypothetical isolated round trip. Actual market-level netting across trades is not simulated. Unit stake is a normalization and not proof of order eligibility under exchange minimums.

There is no reaction latency, queue model, bet delay, order matching, slippage, partial-fill handling, cancellation, withdrawal adjustment settlement, portfolio or capital path. This is deliberately a quote-markout diagnostic. In-play code in Paddock remains unmodified and its latency defect remains unresolved.

All offsets and horizons are fixed from the existing study, with no strategy selection or threshold search. August 2015 is reused solely for correction diagnostics, not untouched evaluation. Confidence intervals resample equal-weight day means (2,000 draws; fixed seed); they are descriptive marginal intervals, not adjusted evidence from an out-of-sample strategy test or a model of multi-day dependence.

`algebra-only.json` isolates price-side/payoff corrections on the original CSV while retaining its timestamp defects. `report.json` contains the fresh raw replay summary. The full row-level CSV remains local. Different eligibility rules mean the latter is not an identical-row comparison. `baseline-provenance.json` fingerprints the old scripts, CSV/report, manifest and live guard; the full report fingerprints every successfully read raw source and the new code.

## Publication notes

This package shares code, tests, aggregate results and source fingerprints. Raw market streams and row-level quotes are not included. Local uncommitted research and runtime files were not included. The published script only changes input-manifest lookup for portability; report.json retains the hash of the exact original script used for the full replay. Tests were rerun on the packaged script. The underlying replay functions are unchanged.
