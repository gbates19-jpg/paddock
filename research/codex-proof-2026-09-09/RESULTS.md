# What the correction actually changed

Read 989 requested market files; 985 markets produced 363,983 eligible direction/horizon observations. Quarantined files: 0.

14 deterministic tests passed. Every output row passed timestamp, payoff and unique-identity checks. All eight full-replay means were independently recomputed from the written CSV.

| Direction / horizon | Original report | Same CSV, corrected sides/payoffs | Fresh raw replay | Eligible observations |
|---|---:|---:|---:|---:|
| BACK 5s | -3.37% | -3.34% | -3.39% | 46,627 |
| BACK 15s | -3.31% | -3.31% | -3.38% | 46,613 |
| BACK 30s | -3.17% | -3.36% | -3.42% | 46,211 |
| BACK 60s | -2.72% | -3.56% | -3.47% | 42,559 |
| LAY 5s | -3.71% | -3.74% | -3.64% | 46,610 |
| LAY 15s | -3.77% | -3.77% | -3.67% | 46,582 |
| LAY 30s | -3.98% | -3.78% | -3.65% | 46,242 |
| LAY 60s | -5.01% | -4.08% | -3.64% | 42,539 |

These are returns per initial stake. LAY initial-liability-normalized values are separately recorded in the full report. The fresh replay uses stricter eligibility and therefore a different row population. This table diagnoses implementation changes; it does not compare tradable strategy P&L.

The correction does not establish an edge. It establishes testable payoff and timestamp behavior. The historical month is already explored, and none of these all-runner averages is an untouched strategy evaluation.

## Observable improvements

- Independent settlement tests prove equal profit whether the horse wins or loses, instead of merely testing a formula against itself.
- Feature timestamps cannot precede the state used; sparse files cannot borrow their final future state.
- Suspensions, in-play states, runner removals and changed schedules have explicit exclusion rules.
- Every raw file is fingerprinted; malformed files are quarantined rather than silently skipped.
- Saved outputs expose quote ages, both stake and liability normalization, exclusion counts, code fingerprint and fixed parameters.

## Exclusion and parsing counts

```json
{
  "lines": 31953238,
  "images": 23312,
  "missing_or_stale_snapshot": 135,
  "targets_beyond_eof": 0,
  "schedule_revision_market": 1,
  "insufficient_displayed_depth": 5087,
  "invalid_exit": 4788,
  "invalid_entry": 8400,
  "withdrawal_interval": 69
}
```

## Scope and next decision

Paddock and its raw inputs remain unchanged, with live trading disabled. The isolated source, tests and aggregate report are available in this folder; the replay CSV remains local. This records the local run before publication. The existing in-play implementation is not repaired by this pre-off demonstration.

The next research gate remains a timestamped fundamentals sample. No fresh strategy should be promoted from these quote markouts. This deliverable provides a working, tested diagnostic foundation; it is not an execution simulator. See README.md for exact assumptions and reproduction commands.
