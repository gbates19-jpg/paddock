// Bundled recorded event stream for `?demo=1` — lets the UI run with no
// engine attached. Shape matches exactly what /events sends live, just
// replayed against a local clock instead of a websocket.
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

export function buildDemoStream(): Recorded[] {
  const events: Recorded[] = [];

  for (const w of WORKERS) events.push(heartbeat(0, w, "idle"));

  events.push({
    offsetMs: 500,
    event: {
      type: "market.open",
      event_id: eid(),
      ts_ms: 0,
      market_id: "1.999999",
      venue: "Ascot",
      race_name: "14:10 Ascot",
      off_time: new Date(Date.now() + 5 * 60_000).toISOString(),
      runners: [
        { selection_id: 1, name: "Paddock Star" },
        { selection_id: 2, name: "Data Loader" },
        { selection_id: 3, name: "Green Light" },
        { selection_id: 4, name: "Ticker Tape" },
      ],
    },
  });

  let t = 800;
  const prices: Record<number, number> = { 1: 2.5, 2: 4.2, 3: 6.0, 4: 11.0 };
  for (let tick = 0; tick < 24; tick++) {
    for (const sel of Object.keys(prices).map(Number)) {
      const drift = (Math.random() - 0.5) * 0.15;
      prices[sel] = Math.max(1.2, prices[sel] + drift);
      events.push(heartbeat(t, "stream", "busy", 40 + Math.random() * 30));
      events.push({
        offsetMs: t + 20,
        event: {
          type: "runner.price",
          event_id: eid(),
          ts_ms: 0,
          market_id: "1.999999",
          selection_id: sel,
          back: [{ price: Number(prices[sel].toFixed(2)), size: 120 + Math.random() * 400 }],
          lay: [{ price: Number((prices[sel] + 0.02).toFixed(2)), size: 120 + Math.random() * 400 }],
          ltp: Number(prices[sel].toFixed(2)),
          traded_volume: 3000 + tick * 80,
        },
      });
    }
    t += 220;
  }

  events.push(heartbeat(t, "strategy:BaselineFavouriteScalp", "busy", 5));
  events.push({
    offsetMs: t + 40,
    event: {
      type: "strategy.signal",
      event_id: eid(),
      ts_ms: 0,
      strategy: "BaselineFavouriteScalp",
      market_id: "1.999999",
      selection_id: 1,
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
      market_id: "1.999999",
      selection_id: 1,
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
      market_id: "1.999999",
      selection_id: 1,
      side: "back",
      price: 2.5,
      size: 10,
      matched_size: 10,
    },
  });
  events.push(heartbeat(t + 20, "pnl", "busy", 3));
  events.push({
    offsetMs: t + 60,
    event: {
      type: "pnl.update",
      event_id: eid(),
      ts_ms: 0,
      run_id: "demo-run",
      market_id: "1.999999",
      market_pnl: 3.4,
      run_pnl: 3.4,
      commission: 0.07,
    },
  });

  t += 1500;
  events.push({
    offsetMs: t,
    event: { type: "market.close", event_id: eid(), ts_ms: 0, market_id: "1.999999" },
  });

  for (const w of WORKERS) events.push(heartbeat(t + 100, w, "idle"));

  return events;
}
