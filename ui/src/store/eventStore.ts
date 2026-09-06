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
import { type StoryEntry, storyFor } from "../lib/story";
import { loadPersisted, savePersisted, snapshotForPersist } from "./persist";

export type ConnectionStatus = "connecting" | "connected" | "disconnected" | "demo";
export type Screen = "pipeline" | "race" | "ladder";

export interface SelectedRunner {
  marketId: string;
  selectionId: number;
}

export function runnerKey(marketId: string, selectionId: number): string {
  return `${marketId}:${selectionId}`;
}

// A short-lived flow mark for the Pipeline's connecting channels — born
// when an event crosses a stage boundary, pruned a moment later by the
// component that draws it. Kept separate from the story feed: this is
// motion, the story is the record.
export interface FlowMark {
  id: string;
  from: string;
  to: string;
  kind: string;
  bornAt: number;
}

const RATE_WINDOW_MS = 15_000;
const STORY_LIMIT = 400;

interface EventStoreState {
  connection: ConnectionStatus;
  workers: Record<string, WorkerHeartbeat>;
  markets: Record<string, MarketOpen>;
  closedMarkets: Record<string, number>; // market_id -> ts_ms closed
  runnerPrices: Record<string, RunnerPrice>;
  prevLtp: Record<string, number>; // runnerKey -> ltp before the latest tick, for direction arrows
  tickDir: Record<string, 1 | -1 | 0>;
  ordersByRunner: Record<string, Record<string, OrderEvent>>;
  pnl: PnlUpdate | null;
  runConfig: RunConfig | null;
  story: StoryEntry[];
  flowMarks: FlowMark[];
  recentTickTs: number[]; // runner.price event timestamps, for a rate display
  recentSignalTs: number[];
  pnlHistory: number[]; // run_pnl at each pnl.update, for the Book's sparkline
  screen: Screen;
  selectedRunner: SelectedRunner | null;

  setConnection: (s: ConnectionStatus) => void;
  applySnapshot: (snapshot: Snapshot) => void;
  applyEvent: (event: PaddockEvent) => void;
  pruneFlowMark: (id: string) => void;
  setScreen: (screen: Screen) => void;
  selectRunner: (marketId: string, selectionId: number) => void;
  clearSelectedRunner: () => void;
}

let flowCounter = 0;

// Which pipeline stage boundary an event's flow mark crosses.
const FLOW_EDGE: Record<string, [string, string] | undefined> = {
  "runner.price": ["stream", "strategy"],
  "strategy.signal": ["strategy", "executor"],
  "order.placed": ["executor", "executor"],
  "order.matched": ["executor", "book"],
  "order.cancelled": ["executor", "executor"],
  "order.lapsed": ["executor", "executor"],
  "pnl.update": ["executor", "book"],
};

function flowMarkFor(event: PaddockEvent): FlowMark | null {
  const edge = FLOW_EDGE[event.type];
  if (!edge) return null;
  return { id: `f${flowCounter++}`, from: edge[0], to: edge[1], kind: event.type, bornAt: performance.now() };
}

// Restored from sessionStorage when a backgrounded tab gets reloaded (see
// store/persist.ts). Null on a genuinely fresh start, which is the normal
// case — everything below falls back to its empty default.
const restored = loadPersisted();

export const useEventStore = create<EventStoreState>((set) => ({
  connection: "connecting",
  // Deliberately NOT restored: a heartbeat we saved before being
  // backgrounded says nothing about whether that worker is alive now.
  workers: {},
  markets: restored?.markets ?? {},
  closedMarkets: restored?.closedMarkets ?? {},
  runnerPrices: restored?.runnerPrices ?? {},
  prevLtp: {},
  tickDir: restored?.tickDir ?? {},
  ordersByRunner: restored?.ordersByRunner ?? {},
  pnl: restored?.pnl ?? null,
  runConfig: restored?.runConfig ?? null,
  story: restored?.story ?? [],
  flowMarks: [],
  // Rolling rate windows: restoring these would paint throughput that
  // isn't happening. They refill within a second of reconnecting.
  recentTickTs: [],
  recentSignalTs: [],
  pnlHistory: restored?.pnlHistory ?? [],
  screen: restored?.screen ?? "pipeline",
  selectedRunner: restored?.selectedRunner ?? null,

  setConnection: (connection) => set({ connection }),
  setScreen: (screen) => set({ screen }),
  selectRunner: (marketId, selectionId) => set({ screen: "ladder", selectedRunner: { marketId, selectionId } }),
  // Back to the race card, keeping the runner selected so the Ladder tab
  // returns you to it rather than to an empty placeholder.
  clearSelectedRunner: () => set({ screen: "race" }),

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

      // storyFor needs the state as it was BEFORE this event is applied
      // (e.g. "matched" phrasing needs the order's previous matched_size,
      // and market.close needs the market that's about to be marked
      // closed while it's still keyed in `markets`).
      let previousOrder: OrderEvent | undefined;
      if (
        event.type === "order.placed" ||
        event.type === "order.matched" ||
        event.type === "order.cancelled" ||
        event.type === "order.lapsed"
      ) {
        previousOrder = state.ordersByRunner[runnerKey(event.market_id, event.selection_id)]?.[event.order_id];
      }
      const entry = storyFor(event, { markets: state.markets, previousOrder, runPnlBefore: state.pnl?.run_pnl ?? 0 });

      if (event.type === "worker.heartbeat") {
        next.workers = { ...state.workers, [event.name]: event };
      } else if (event.type === "market.open") {
        next.markets = { ...state.markets, [event.market_id]: event };
        if (state.closedMarkets[event.market_id]) {
          const closedMarkets = { ...state.closedMarkets };
          delete closedMarkets[event.market_id];
          next.closedMarkets = closedMarkets;
        }
      } else if (event.type === "market.close") {
        // Kept in `markets` (not deleted) so the Race card can show a
        // CLOSED pill instead of the market just vanishing — the old v1
        // behaviour deleted it here, which is also why v1 had nothing to
        // say about a market that had just gone off.
        next.closedMarkets = { ...state.closedMarkets, [event.market_id]: event.ts_ms };
      } else if (event.type === "runner.price") {
        const key = runnerKey(event.market_id, event.selection_id);
        const prior = state.runnerPrices[key];
        if (prior?.ltp != null) next.prevLtp = { ...state.prevLtp, [key]: prior.ltp };
        if (prior?.ltp != null && event.ltp != null) {
          const dir = event.ltp > prior.ltp ? 1 : event.ltp < prior.ltp ? -1 : 0;
          next.tickDir = { ...state.tickDir, [key]: dir };
        }
        next.runnerPrices = { ...state.runnerPrices, [key]: event };
        next.recentTickTs = [...state.recentTickTs, event.ts_ms].filter((t) => t > event.ts_ms - RATE_WINDOW_MS).slice(-500);
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
        next.pnlHistory = [...state.pnlHistory, event.run_pnl].slice(-60);
      } else if (event.type === "run.config") {
        next.runConfig = event;
      } else if (event.type === "strategy.signal") {
        next.recentSignalTs = [...state.recentSignalTs, event.ts_ms].filter((t) => t > event.ts_ms - 60_000).slice(-200);
      }

      const flowMark = flowMarkFor(event);
      if (flowMark) next.flowMarks = [...state.flowMarks, flowMark].slice(-150);

      if (entry) next.story = [entry, ...state.story].slice(0, STORY_LIMIT);

      return next;
    }),

  pruneFlowMark: (id) => set((state) => ({ flowMarks: state.flowMarks.filter((p) => p.id !== id) })),
}));

// --- session persistence -------------------------------------------------
// Two writers, for two different failure modes:
//   1. A throttled periodic write, so a hard crash or an eviction that
//      skips the lifecycle events still loses at most a few seconds.
//   2. A synchronous flush the moment the page is hidden — this is the one
//      that matters on iOS, since backgrounding is exactly when Safari
//      decides to evict the tab, and it may never run another line of our
//      JS before reloading it.
const PERSIST_THROTTLE_MS = 2000;
let lastWrite = 0;
let pending: ReturnType<typeof setTimeout> | null = null;

function flush(): void {
  lastWrite = Date.now();
  if (pending) {
    clearTimeout(pending);
    pending = null;
  }
  savePersisted(snapshotForPersist(useEventStore.getState()));
}

export function attachPersistence(): () => void {
  const unsubscribe = useEventStore.subscribe(() => {
    if (pending) return;
    const wait = Math.max(0, PERSIST_THROTTLE_MS - (Date.now() - lastWrite));
    pending = setTimeout(flush, wait);
  });

  // pagehide is the reliable one on iOS Safari; visibilitychange covers
  // tab switches and the desktop case. Both are cheap, so we take both.
  const onHide = () => {
    if (document.visibilityState === "hidden") flush();
  };
  const onPageHide = () => flush();
  document.addEventListener("visibilitychange", onHide);
  window.addEventListener("pagehide", onPageHide);

  return () => {
    unsubscribe();
    document.removeEventListener("visibilitychange", onHide);
    window.removeEventListener("pagehide", onPageHide);
    if (pending) clearTimeout(pending);
  };
}
