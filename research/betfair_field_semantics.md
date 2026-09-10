# Betfair `atb`/`atl` semantics used by Paddock

## Official reference

Betfair Exchange Stream API, **Key fields** and **Building a price cache**:

<https://betfair-developer-docs.atlassian.net/wiki/spaces/1smk3cen4v3lu3yomq5qye0ni/pages/2687396/Exchange+Stream+API>

The official documentation defines the full-depth price-point ladders as:

- `atb`: **Available To Back**
- `atl`: **Available To Lay**

It also states that `atb`/`atl` are raw full-depth non-virtual prices, that `img=true` replaces the cached item, and that price-point updates are `(price, size)` deltas with size zero removing a price.

Paddock therefore preserves the action semantics rather than translating them into conventional bid/ask names:

| Incoming action | Consumes | Entry field | Exit field |
|---|---|---|---|
| BACK | Available To Back | `atb` | `atl` |
| LAY | Available To Lay | `atl` | `atb` |

The best executable prices are `max(atb)` for a BACK and `min(atl)` for a LAY, consistent with the action available at each ladder.

## Independent matching sanity check

Use an unchanged book with `atb=2.00` and `atl=2.02`:

- BACK then LAY: `2.00 / 2.02 - 1 = -0.00990099` before commission.
- LAY then BACK: `1 - 2.02 / 2.00 = -0.01000000` before commission.

The same result follows from equalised matching:

- BACK £10 at 2.00, then LAY `£10 × 2.00 / 2.02 = £9.9009901` at 2.02. Both outcome P&Ls are approximately `-£0.0990099`.
- LAY £10 at 2.02, then BACK `£10 × 2.02 / 2.00 = £10.10` at 2.00. Both outcome P&Ls are `-£0.10`.

Any implementation that maps BACK entry to `atl` and LAY exit to `atb` on this unchanged book can manufacture a positive return. That is the specific side error corrected here; this change is not a bid/ask convention change.
