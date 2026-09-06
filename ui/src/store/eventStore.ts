import { create } from "zustand";
import type {
  MarketOpen,
  OrderEvent,
  PaddockEvent,
  PnlUpdate,
  RunConfig,
  RunnerPrice,
  Snapshot,
  WorkerHeartbeat,
} from "../lib/events";

export type ConnectionStatus = "connecting" | "connected" | "disconnected" | "demo";
export type Scene = "floor" | "paddock" | "ladder";

interface Particle {
  id: string;
  from: string;
  to: string;
  kind: string;
  size: number;
  bornAt: number;
}

export interface SelectedRunner {
  marketId: string;
  selectionId: number;
}

export function runnerKey(marketId: string, selectionId: number): string {
  return `${marketId}:${selectionId}`;
}

interface EventStoreState {
  connection: ConnectionStatus;
  workers: Record<string, WorkerHeartbeat>;
  markets: Record<string, MarketOpen>;
  runnerPrices: Record<string, RunnerPrice>;
  ordersByRunner: Record<string, Record<string, OrderEvent>>;
  pnl: PnlUpdate | null;
  runConfig: RunConfig | null;
  particles: Particle[];
  log: PaddockEvent[];
  scene: Scene;
  selectedRunner: SelectedRunner | null;

  setConnection: (s: ConnectionStatus) => void;
  applySnapshot: (snapshot: Snapshot) => void;
  applyEvent: (event: PaddockEvent) => void;
  pruneParticle: (id: string) => void;
  setScene: (scene: Scene) => void;
  selectRunner: (marketId: string, selectionId: number) => void;
  clearSelectedRunner: () => void;
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
  runnerPrices: {},
  ordersByRunner: {},
  pnl: null,
  runConfig: null,
  particles: [],
  log: [],
  scene: "floor",
  selectedRunner: null,

  setConnection: (connection) => set({ connection }),
  setScene: (scene) => set({ scene }),
  selectRunner: (marketId, selectionId) =>
    set({ scene: "ladder", selectedRunner: { marketId, selectionId } }),
  clearSelectedRunner: () => set({ selectedRunner: null }),

  applySnapshot: (snapshot) =>
    set(() => {
      const workers: Record<string, WorkerHeartbeat> = {};
      for (const w of snapshot.data.workers) workers[w.name] = w;
      const markets: Record<string, MarketOpen> = {};
      for (const m of snapshot.data.markets) markets[m.market_id] = m;
      const runnerPrices: Record<string, RunnerPrice> = {};
      for (const p of snapshot.data.runner_prices ?? []) {
        runnerPrices[runnerKey(p.market_id, p.selection_id)] = p;
      }
      return {
        workers,
        markets,
        runnerPrices,
        pnl: snapshot.data.pnl,
        runConfig: snapshot.data.run_config,
      };
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
      } else if (event.type === "runner.price") {
        next.runnerPrices = {
          ...state.runnerPrices,
          [runnerKey(event.market_id, event.selection_id)]: event,
        };
      } else if (
        event.type === "order.placed" ||
        event.type === "order.matched" ||
        event.type === "order.cancelled" ||
        event.type === "order.lapsed"
      ) {
        const key = runnerKey(event.market_id, event.selection_id);
        const existing = state.ordersByRunner[key] ?? {};
        next.ordersByRunner = {
          ...state.ordersByRunner,
          [key]: { ...existing, [event.order_id]: event },
        };
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
