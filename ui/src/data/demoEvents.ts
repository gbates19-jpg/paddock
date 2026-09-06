// Bundled recorded event stream for `?demo=1` — lets the UI run with no
// engine attached. Shape matches exactly what /events sends live, just
// replayed against a local clock instead of a websocket.
//
// Runner/venue/race names below are REAL, pulled from a real Basic Plan
// download (data/basic/2026/09/1.261733284 and .../1.261733290, Brighton
// 1st Sep) — not placeholders. Basic Plan data has no order-book depth
// for ANY runner (that's the whole point of the plan), so to still be
// able to demo the Ladder's depth-having state we deliberately give most
// of market A's runners synthetic depth here, as if they were Advanced/
// Pro tier, and leave exactly one (the last) with none — a demo
// simplification, not a claim about what that real file actually
// contains. See NO_DEPTH_SELECTION.
import type { PaddockEvent } from "../lib/events";

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

const WORKERS = ["stream", "keep_alive", "executor", "data_loader", "pnl", "strategy:BaselineFavouriteScalp"];

const MARKET_A = {
  id: "1.261733284",
  venue: "Brighton",
  race: "Brighton 1st Sep",
  offMinutesFromNow: 4,
  runners: [
    { selection_id: 5240218, name: "Shining Guest", start: 2.5 },
    { selection_id: 91405503, name: "My Mate Mackley", start: 4.2 },
    { selection_id: 84239473, name: "Beach Partee", start: 6.0 },
    { selection_id: 84080026, name: "London Is Blue", start: 8.5 },
    { selection_id: 89943966, name: "Havana Jag", start: 9.0 },
    { selection_id: 84836613, name: "Loleeta", start: 11.0 }, // no depth — see header comment
  ],
};
const NO_DEPTH_SELECTION = 84836613; // Loleeta

const MARKET_B = {
  id: "1.261733290",
  venue: "Brighton",
  race: "Brighton 1st Sep",
  offMinutesFromNow: 34,
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
      off_time: new Date(Date.now() + m.offMinutesFromNow * 60_000).toISOString(),
      runners: m.runners.map((r) => ({ selection_id: r.selection_id, name: r.name })),
    },
  };
}

// Dense burst standing in for a real Pro replay's ~50ms tick rate, to
// stress-test rendering — see scripts/snap.mjs's FPS measurement.
const DENSE_BURST_TICKS = 60;
const DENSE_BURST_INTERVAL_MS = 50;

export function buildDemoStream(): Recorded[] {
  const events: Recorded[] = [];

  for (const w of WORKERS) events.push(heartbeat(0, w, "idle"));

  events.push({
    offsetMs: 0,
    event: {
      type: "run.config",
      event_id: eid(),
      ts_ms: 0,
      run_id: "demo-run",
      mode: "replay",
      fill_model: "ltp_cross",
      commission_rate: 0.02,
      speed: 20,
    },
  });

  events.push(marketOpen(300, MARKET_A));
  events.push(marketOpen(400, MARKET_B));

  const prices: Record<number, number> = {};
  for (const r of [...MARKET_A.runners, ...MARKET_B.runners]) prices[r.selection_id] = r.start;

  function priceTick(t: number, marketId: string, sel: number, tick: number) {
    const drift = (Math.random() - 0.5) * 0.15;
    prices[sel] = Math.max(1.2, prices[sel] + drift);
    const hasDepth = sel !== NO_DEPTH_SELECTION;
    events.push(heartbeat(t, "stream", "busy", 20 + Math.random() * 40));
    events.push({
      offsetMs: t,
      event: {
        type: "runner.price",
        event_id: eid(),
        ts_ms: 0,
        market_id: marketId,
        selection_id: sel,
        back: hasDepth ? [{ price: Number(prices[sel].toFixed(2)), size: 120 + Math.random() * 400 }] : [],
        lay: hasDepth ? [{ price: Number((prices[sel] + 0.02).toFixed(2)), size: 120 + Math.random() * 400 }] : [],
        ltp: Number(prices[sel].toFixed(2)),
        traded_volume: hasDepth ? 3000 + tick * 80 : null,
      },
    });
  }

  // Normal-paced ticking, both markets, ~220ms apart (Advanced-ish density)
  let t = 800;
  for (let tick = 0; tick < 18; tick++) {
    for (const r of MARKET_A.runners) priceTick(t, MARKET_A.id, r.selection_id, tick);
    if (tick % 2 === 0) for (const r of MARKET_B.runners) priceTick(t + 30, MARKET_B.id, r.selection_id, tick);
    t += 220;
  }

  // Dense burst on market A's favourite — stand-in for Pro's ~50ms ticks
  const favourite = MARKET_A.runners[0].selection_id;
  for (let i = 0; i < DENSE_BURST_TICKS; i++) {
    priceTick(t, MARKET_A.id, favourite, 100 + i);
    t += DENSE_BURST_INTERVAL_MS;
  }

  events.push(heartbeat(t, "strategy:BaselineFavouriteScalp", "busy", 5));
  events.push({
    offsetMs: t + 40,
    event: {
      type: "strategy.signal",
      event_id: eid(),
      ts_ms: 0,
      strategy: "BaselineFavouriteScalp",
      market_id: MARKET_A.id,
      selection_id: favourite,
      reason: "5 minutes to off — backing favourite",
      confidence: 0.7,
    },
  });
  t += 300;
  events.push(heartbeat(t, "executor", "busy", 12));
  events.push({
    offsetMs: t + 40,
    event: {
      type: "order.placed",
      event_id: eid(),
      ts_ms: 0,
      order_id: "demo-order-1",
      market_id: MARKET_A.id,
      selection_id: favourite,
      side: "back",
      price: 2.5,
      size: 10,
      matched_size: 0,
    },
  });
  t += 600;
  events.push({
    offsetMs: t,
    event: {
      type: "order.matched",
      event_id: eid(),
      ts_ms: 0,
      order_id: "demo-order-1",
      market_id: MARKET_A.id,
      selection_id: favourite,
      side: "back",
      price: 2.5,
      size: 10,
      matched_size: 10,
    },
  });

  // A short run of pnl.update ticks so the Book's sparkline has a shape,
  // not a single point.
  const pnlSeries = [0, 0.4, 0.9, 0.6, 1.3, 2.1, 1.8, 2.6, 3.4];
  pnlSeries.forEach((value, i) => {
    events.push(heartbeat(t + i * 200, "pnl", "busy", 3));
    events.push({
      offsetMs: t + i * 200 + 20,
      event: {
        type: "pnl.update",
        event_id: eid(),
        ts_ms: 0,
        run_id: "demo-run",
        market_id: MARKET_A.id,
        market_pnl: value,
        run_pnl: value,
        commission: Number((value * 0.02).toFixed(2)),
        fill_model: "ltp_cross",
      },
    });
  });
  t += pnlSeries.length * 200 + 800;

  events.push({
    offsetMs: t,
    event: { type: "market.close", event_id: eid(), ts_ms: 0, market_id: MARKET_A.id },
  });

  for (const w of WORKERS) events.push(heartbeat(t + 100, w, "idle"));

  return events;
}
