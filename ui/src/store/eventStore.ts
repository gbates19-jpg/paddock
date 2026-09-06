import { create } from "zustand";
import type {
  MarketOpen,
  PaddockEvent,
  PnlUpdate,
  RunConfig,
  Snapshot,
  WorkerHeartbeat,
} from "../lib/events";

export type ConnectionStatus = "connecting" | "connected" | "disconnected" | "demo";

interface Particle {
  id: string;
  from: string;
  to: string;
  kind: string;
  size: number;
  bornAt: number;
}

interface EventStoreState {
  connection: ConnectionStatus;
  workers: Record<string, WorkerHeartbeat>;
  markets: Record<string, MarketOpen>;
  pnl: PnlUpdate | null;
  runConfig: RunConfig | null;
  particles: Particle[];
  log: PaddockEvent[];

  setConnection: (s: ConnectionStatus) => void;
  applySnapshot: (snapshot: Snapshot) => void;
  applyEvent: (event: PaddockEvent) => void;
  pruneParticle: (id: string) => void;
}

let particleCounter = 0;

function particleFor(event: PaddockEvent): Particle | null {
  const map: Record<string, [string, string]> = {
    "runner.price": ["stream", "executor"],
    "strategy.signal": ["executor", "executor"],
    "order.placed": ["executor", "executor"],
    "order.matched": ["executor", "pnl"],
    "order.cancelled": ["executor", "executor"],
    "order.lapsed": ["executor", "executor"],
  };
  const edge = map[event.type];
  if (!edge) return null;
  let size = 4;
  if ("size" in event && typeof event.size === "number") size = Math.max(3, Math.min(14, event.size));
  if ("matched_size" in event && event.matched_size) size = Math.max(size, Math.min(18, event.matched_size));
  return {
    id: `p${particleCounter++}`,
    from: edge[0],
    to: edge[1],
    kind: event.type,
    size,
    bornAt: performance.now(),
  };
}

export const useEventStore = create<EventStoreState>((set) => ({
  connection: "connecting",
  workers: {},
  markets: {},
  pnl: null,
  runConfig: null,
  particles: [],
  log: [],

  setConnection: (connection) => set({ connection }),

  applySnapshot: (snapshot) =>
    set(() => {
      const workers: Record<string, WorkerHeartbeat> = {};
      for (const w of snapshot.data.workers) workers[w.name] = w;
      const markets: Record<string, MarketOpen> = {};
      for (const m of snapshot.data.markets) markets[m.market_id] = m;
      return { workers, markets, pnl: snapshot.data.pnl, runConfig: snapshot.data.run_config };
    }),

  applyEvent: (event) =>
    set((state) => {
      const next: Partial<EventStoreState> = {};

      if (event.type === "worker.heartbeat") {
        next.workers = { ...state.workers, [event.name]: event };
      } else if (event.type === "market.open") {
        next.markets = { ...state.markets, [event.market_id]: event };
      } else if (event.type === "market.close") {
        const markets = { ...state.markets };
        delete markets[event.market_id];
        next.markets = markets;
      } else if (event.type === "pnl.update") {
        next.pnl = event;
      } else if (event.type === "run.config") {
        next.runConfig = event;
      }

      const particle = particleFor(event);
      if (particle) {
        next.particles = [...state.particles, particle].slice(-200);
      }

      const log = [event, ...state.log].slice(0, 300);
      next.log = log;

      return next;
    }),

  pruneParticle: (id) =>
    set((state) => ({ particles: state.particles.filter((p) => p.id !== id) })),
}));
