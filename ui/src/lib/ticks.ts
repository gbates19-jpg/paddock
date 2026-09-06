// Mirrors flumine.utils.price_ticks_away's ladder — Betfair's tick
// increment is non-uniform (0.01 below 2, widening in bands up to 5 at
// 100+). Used only to draw a realistic set of ladder rows around
// whatever price levels the data actually reports, not to validate them.
const BANDS: [number, number, number][] = [
  [1, 2, 0.01],
  [2, 3, 0.02],
  [3, 4, 0.05],
  [4, 6, 0.1],
  [6, 10, 0.2],
  [10, 20, 0.5],
  [20, 30, 1],
  [30, 50, 2],
  [50, 100, 5],
  [100, 1000, 10],
];

function tickSizeAt(price: number): number {
  const band = BANDS.find(([lo, hi]) => price >= lo && price < hi);
  return band ? band[2] : 10;
}

export function tickUp(price: number): number {
  const size = tickSizeAt(price);
  return Number((price + size).toFixed(2));
}

export function tickDown(price: number): number {
  const size = tickSizeAt(Math.max(1.01, price - 0.001));
  return Number(Math.max(1.01, price - size).toFixed(2));
}

// Rows from `high` down to `low` inclusive, stepping by the real ladder —
// used to fill in a proper-looking ladder even where the feed only gave a
// handful of discrete levels.
export function ticksBetween(low: number, high: number, maxRows = 12): number[] {
  const rows: number[] = [];
  let p = high;
  while (p >= low - 1e-9 && rows.length < maxRows) {
    rows.push(Number(p.toFixed(2)));
    p = tickDown(p);
  }
  return rows;
}
