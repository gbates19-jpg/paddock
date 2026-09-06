// Bundled recorded event stream for `?demo=1` — lets the UI run with no
// engine attached. Shape matches exactly what /events sends live, just
// replayed against a local clock instead of a websocket.
//
// v2: the demo is a STORY, not a burst of noise. One full trade lifecycle
// on the next-off market, told at a pace a person can follow:
//   prices tick -> strategy signals -> back placed -> back matched ->
//   lay placed 2 ticks under -> lay matched (hedged, locked green) ->
//   second attempt whose lay never fills, cancelled 30s before the off,
//   closed at market for a small loss -> market closes -> loop.
// Prices move on Betfair's real tick grid (lib/ticks) so the ladder,
// the arrows and the sentences all agree.
//
// Runner/venue/race names are REAL, pulled from a real Basic Plan
// download (data/basic/2026/09/1.261733284 and .../1.261733290, Brighton
// 1st Sep). Basic Plan data has no order-book depth, so to demo the
// Ladder's depth-having state most of market A's runners get synthetic
// best-3 depth here, and exactly one (Loleeta) is left with none.
import type { PaddockEvent, PriceLevel } from "../lib/events";
import { tickDown, tickUp } from "../lib/ticks";

let id = 0;
const eid = () => `demo-${id++}`;

interface Recorded {
  offsetMs: number;
  event: PaddockEvent;
}

function heartbeat(offsetMs: number, name: string, state: "idle" | "busy" | "error", latency = 8): Recorded {
  return {
    offsetMs,
    event: { type: "worker.heartbeat", event_id: eid(), ts_ms: 0, name, state, last_latency_ms: latency },
  };
}

const STRATEGY = "BaselineFavouriteScalp";
const WORKERS = ["stream", "keep_alive", "executor", "data_loader", "pnl", `strategy:${STRATEGY}`];

export const DEMO_MARKET_ID = "1.261733284";
export const DEMO_FAVOURITE = 5240218; // Shining Guest
export const DEMO_NO_DEPTH = 84836613; // Loleeta

const MARKET_A = {
  id: DEMO_MARKET_ID,
  venue: "Brighton",
  race: "14:10 Brighton 1m Hcap",
  offSecondsFromNow: 5 * 60 + 20,
  runners: [
    { selection_id: DEMO_FAVOURITE, name: "Shining Guest", start: 2.5 },
    { selection_id: 91405503, name: "My Mate Mackley", start: 4.2 },
    { selection_id: 84239473, name: "Beach Partee", start: 6.0 },
    { selection_id: 84080026, name: "London Is Blue", start: 8.6 },
    { selection_id: 89943966, name: "Havana Jag", start: 9.2 },
    { selection_id: DEMO_NO_DEPTH, name: "Loleeta", start: 11.0 },
  ],
};

const MARKET_B = {
  id: "1.261733290",
  venue: "Brighton",
  race: "14:40 Brighton 6f Hcap",
  offSecondsFromNow: 35 * 60,
  runners: [
    { selection_id: 100001, name: "Norfolk Blue", start: 3.4 },
    { selection_id: 100002, name: "Inspectre", start: 5.5 },
    { selection_id: 100003, name: "Muchacho", start: 7.0 },
    { selection_id: 100004, name: "Twilight Baby", start: 12.0 },
  ],
};

function marketOpen(offsetMs: number, m: typeof MARKET_A | typeof MARKET_B): Recorded {
  return {
    offsetMs,
    event: {
      type: "market.open",
      event_id: eid(),
      ts_ms: 0,
      market_id: m.id,
      venue: m.venue,
      race_name: m.race,
      off_time: new Date(Date.now() + m.offSecondsFromNow * 1000).toISOString(),
      runners: m.runners.map((r) => ({ selection_id: r.selection_id, name: r.name })),
    },
  };
}

// Deterministic-ish pseudo random so two loops look alike enough to
// compare, but not identical.
let seed = 7;
function rnd(): number {
  seed = (seed * 9301 + 49297) % 233280;
  return seed / 233280;
}

export function buildDemoStream(): Recorded[] {
  const events: Recorded[] = [];
  const prices: Record<number, number> = {};
  const volumes: Record<number, number> = {};
  for (const r of [...MARKET_A.runners, ...MARKET_B.runners]) {
    prices[r.selection_id] = r.start;
    volumes[r.selection_id] = 800 + Math.round(rnd() * 4000);
  }

  function depth(best: number, dir: 1 | -1): PriceLevel[] {
    const out: PriceLevel[] = [];
    let p = best;
    for (let i = 0; i < 3; i++) {
      out.push({ price: p, size: Math.round(40 + rnd() * 380) });
      p = dir === 1 ? tickUp(p) : tickDown(p);
    }
    return out;
  }

  function priceTick(t: number, marketId: string, sel: number, force?: 1 | -1 | 0) {
    const move = force ?? (rnd() < 0.55 ? 0 : rnd() < 0.5 ? 1 : -1);
    if (move === 1) prices[sel] = tickUp(prices[sel]);
    if (move === -1) prices[sel] = tickDown(prices[sel]);
    const hasDepth = sel !== DEMO_NO_DEPTH;
    volumes[sel] += Math.round(rnd() * 60);
    events.push(heartbeat(t, "stream", "busy", 18 + rnd() * 30));
    events.push({
      offsetMs: t,
      event: {
        type: "runner.price",
        event_id: eid(),
        ts_ms: 0,
        market_id: marketId,
        selection_id: sel,
        back: hasDepth ? depth(prices[sel], -1) : [],
        lay: hasDepth ? depth(tickUp(prices[sel]), 1) : [],
        ltp: prices[sel],
        traded_volume: hasDepth ? volumes[sel] : null,
      },
    });
  }

  function tickAll(t: number, marketId: string, runners: { selection_id: number }[]) {
    for (const r of runners) priceTick(t, marketId, r.selection_id);
  }

  function order(
    t: number,
    type: "order.placed" | "order.matched" | "order.cancelled" | "order.lapsed",
    orderId: string,
    side: "back" | "lay",
    price: number,
    size: number,
    matched: number
  ) {
    events.push(heartbeat(t, "executor", "busy", 9 + rnd() * 6));
    events.push({
      offsetMs: t,
      event: {
        type,
        event_id: eid(),
        ts_ms: 0,
        order_id: orderId,
        market_id: MARKET_A.id,
        selection_id: DEMO_FAVOURITE,
        side,
        price,
        size,
        matched_size: matched,
      },
    });
  }

  function pnl(t: number, marketPnl: number, runPnl: number) {
    events.push(heartbeat(t, "pnl", "busy", 3));
    events.push({
      offsetMs: t,
      event: {
        type: "pnl.update",
        event_id: eid(),
        ts_ms: 0,
        run_id: "demo-run",
        market_id: MARKET_A.id,
        market_pnl: marketPnl,
        run_pnl: runPnl,
        commission: Number((Math.max(0, marketPnl) * 0.02).toFixed(2)),
        fill_model: "ladder",
      },
    });
  }

  for (const w of WORKERS) events.push(heartbeat(0, w, "idle"));
  events.push({
    offsetMs: 0,
    event: {
      type: "run.config",
      event_id: eid(),
      ts_ms: 0,
      run_id: "demo-run",
      mode: "replay",
      fill_model: "ladder",
      commission_rate: 0.02,
      speed: 20,
    },
  });
  events.push({
    offsetMs: 50,
    event: { type: "log", event_id: eid(), ts_ms: 0, level: "info", msg: "replay started: data/advanced/2026/09, 2 markets" },
  });

  events.push(marketOpen(300, MARKET_A));
  events.push(marketOpen(400, MARKET_B));

  // --- 1. Market ticking, strategy watching (0-6s) ---
  let t = 800;
  for (let i = 0; i < 14; i++) {
    tickAll(t, MARKET_A.id, MARKET_A.runners);
    if (i % 3 === 0) tickAll(t + 60, MARKET_B.id, MARKET_B.runners);
    t += 380;
  }

  // --- 2. Signal: 5 min to off, back the favourite (6s) ---
  const fav = DEMO_FAVOURITE;
  events.push(heartbeat(t, `strategy:${STRATEGY}`, "busy", 4));
  events.push({
    offsetMs: t + 40,
    event: {
      type: "strategy.signal",
      event_id: eid(),
      ts_ms: 0,
      strategy: STRATEGY,
      market_id: MARKET_A.id,
      selection_id: fav,
      reason: "5:00 to off — favourite at best back, entering",
      confidence: 0.7,
    },
  });
  t += 700;

  // --- 3. Back placed at best available, then matched (7-9s) ---
  const backPrice = prices[fav];
  order(t, "order.placed", "demo-back-1", "back", backPrice, 10, 0);
  t += 500;
  priceTick(t, MARKET_A.id, fav, 0);
  t += 900;
  order(t, "order.matched", "demo-back-1", "back", backPrice, 10, 10);
  t += 500;

  // --- 4. Lay 2 ticks under, resting (9-13s) ---
  const layPrice = tickDown(tickDown(backPrice));
  order(t, "order.placed", "demo-lay-1", "lay", layPrice, 10, 0);
  t += 400;
  for (let i = 0; i < 6; i++) {
    tickAll(t, MARKET_A.id, MARKET_A.runners.filter((r) => r.selection_id !== fav));
    // favourite drifts down toward our lay
    priceTick(t, MARKET_A.id, fav, i === 2 || i === 4 ? -1 : 0);
    t += 420;
  }

  // --- 5. Lay matched -> hedged, green locked (13s) ---
  order(t, "order.matched", "demo-lay-1", "lay", layPrice, 10, 10);
  const locked = Number((10 * (backPrice / layPrice - 1)).toFixed(2)); // green-up profit whatever wins
  pnl(t + 100, locked, locked);
  t += 1400;

  // --- 6. Second scalp: back matched, lay never fills, cancelled 30s before off (14-22s) ---
  events.push({
    offsetMs: t,
    event: {
      type: "strategy.signal",
      event_id: eid(),
      ts_ms: 0,
      strategy: STRATEGY,
      market_id: MARKET_A.id,
      selection_id: fav,
      reason: "re-entering — spread 1 tick, volume rising",
      confidence: 0.55,
    },
  });
  t += 600;
  const back2 = prices[fav];
  order(t, "order.placed", "demo-back-2", "back", back2, 10, 0);
  t += 800;
  order(t, "order.matched", "demo-back-2", "back", back2, 10, 10);
  t += 500;
  const lay2 = tickDown(tickDown(back2));
  order(t, "order.placed", "demo-lay-2", "lay", lay2, 10, 0);
  t += 400;
  for (let i = 0; i < 7; i++) {
    tickAll(t, MARKET_A.id, MARKET_A.runners.filter((r) => r.selection_id !== fav));
    // this time the price goes AGAINST us
    priceTick(t, MARKET_A.id, fav, i === 1 || i === 3 || i === 5 ? 1 : 0);
    t += 420;
  }
  events.push({
    offsetMs: t,
    event: {
      type: "strategy.signal",
      event_id: eid(),
      ts_ms: 0,
      strategy: STRATEGY,
      market_id: MARKET_A.id,
      selection_id: fav,
      reason: "0:30 to off — cancelling unmatched, closing at market",
      confidence: null,
    },
  });
  t += 300;
  order(t, "order.cancelled", "demo-lay-2", "lay", lay2, 10, 0);
  t += 500;
  // closer takes liquidity at the current lay price
  const closeLay = tickUp(prices[fav]);
  order(t, "order.placed", "demo-lay-3", "lay", closeLay, 10, 0);
  t += 600;
  order(t, "order.matched", "demo-lay-3", "lay", closeLay, 10, 10);
  const loss = Number((10 * (back2 / closeLay - 1)).toFixed(2)); // negative when closeLay > back2
  const runTotal = Number((locked + loss).toFixed(2));
  pnl(t + 100, runTotal, runTotal);
  t += 1200;

  // --- 7. A few more ticks, then the off / close (24-28s) ---
  for (let i = 0; i < 5; i++) {
    tickAll(t, MARKET_A.id, MARKET_A.runners);
    t += 400;
  }
  events.push({
    offsetMs: t,
    event: { type: "log", event_id: eid(), ts_ms: 0, level: "info", msg: `market ${MARKET_A.id} turned in-play; strategy flat` },
  });
  t += 2500;
  events.push({ offsetMs: t, event: { type: "market.close", event_id: eid(), ts_ms: 0, market_id: MARKET_A.id } });
  t += 200;
  for (const w of WORKERS) events.push(heartbeat(t, w, "idle"));
  // keep market B ticking a while so the screen is never dead
  for (let i = 0; i < 8; i++) {
    tickAll(t, MARKET_B.id, MARKET_B.runners);
    t += 500;
  }

  return events;
}
