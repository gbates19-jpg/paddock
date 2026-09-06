// Session persistence — the answer to "I switched apps on my phone, came
// back, and the whole view had reset to nothing."
//
// iOS Safari evicts backgrounded tabs under memory pressure and reloads
// them when you return. We can't stop that. What we CAN stop is the
// reload landing on an empty control room: without this, every piece of
// state (positions, story feed, P&L history, which runner's ladder you
// were on) lived only in memory and was gone, and the view rebuilt itself
// only as fresh events happened to arrive.
//
// So: a slim snapshot goes to sessionStorage, and the store hydrates from
// it on boot. sessionStorage (not localStorage) is deliberate — it's
// scoped to this tab and dies with it, so coming back to a tab you left
// open restores your view, but opening the app fresh tomorrow starts
// clean rather than showing yesterday's prices as though they were live.
//
// What is NOT persisted matters as much as what is:
//   - workers: heartbeats go stale the moment we're backgrounded. Showing
//     a restored "busy" light for a worker that may have died would be a
//     lie, so stages start idle until a real heartbeat lands.
//   - recentTickTs / recentSignalTs: these are rolling rate windows;
//     restoring them would draw phantom throughput that isn't happening.
//   - flowMarks: in-flight animation, meaningless a second later.
//   - connection: always recomputed by the live/demo connector on boot.
//
// Prices and positions ARE restored, and are honestly labelled: the Book
// HUD's connection dot shows "connecting" until the socket is back, so a
// restored view never claims to be a live one.

import type { StoryEntry } from "../lib/story";
import type { MarketOpen, OrderEvent, PnlUpdate, RunConfig, RunnerPrice } from "../lib/events";
import type { Screen, SelectedRunner } from "./eventStore";

const KEY = "paddock.session.v1";
const SCHEMA = 1;

// Anything older than this is thrown away rather than restored: a tab
// resumed the next morning should not open on stale prices.
const MAX_AGE_MS = 6 * 60 * 60 * 1000;

// The story feed keeps 400 in memory; persisting all of them is a lot of
// JSON to write on every background. The most recent 80 is plenty to make
// a restored view feel continuous.
const PERSISTED_STORY_LIMIT = 80;

export interface PersistedState {
  schema: number;
  savedAt: number;
  markets: Record<string, MarketOpen>;
  closedMarkets: Record<string, number>;
  runnerPrices: Record<string, RunnerPrice>;
  tickDir: Record<string, 1 | -1 | 0>;
  ordersByRunner: Record<string, Record<string, OrderEvent>>;
  pnl: PnlUpdate | null;
  runConfig: RunConfig | null;
  story: StoryEntry[];
  pnlHistory: number[];
  screen: Screen;
  selectedRunner: SelectedRunner | null;
}

// Every storage call is wrapped: Safari in private mode throws on access
// rather than returning null, and a quota error mid-write must never take
// the app down with it.
export function loadPersisted(): Partial<PersistedState> | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedState;
    if (parsed?.schema !== SCHEMA) return null;
    if (!parsed.savedAt || Date.now() - parsed.savedAt > MAX_AGE_MS) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function savePersisted(state: PersistedState): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ ...state, schema: SCHEMA, savedAt: Date.now() }));
  } catch {
    // Quota, private mode, or storage disabled — persistence is a
    // convenience, never a requirement. Carry on.
  }
}

export function snapshotForPersist(state: {
  markets: Record<string, MarketOpen>;
  closedMarkets: Record<string, number>;
  runnerPrices: Record<string, RunnerPrice>;
  tickDir: Record<string, 1 | -1 | 0>;
  ordersByRunner: Record<string, Record<string, OrderEvent>>;
  pnl: PnlUpdate | null;
  runConfig: RunConfig | null;
  story: StoryEntry[];
  pnlHistory: number[];
  screen: Screen;
  selectedRunner: SelectedRunner | null;
}): PersistedState {
  return {
    schema: SCHEMA,
    savedAt: Date.now(),
    markets: state.markets,
    closedMarkets: state.closedMarkets,
    runnerPrices: state.runnerPrices,
    tickDir: state.tickDir,
    ordersByRunner: state.ordersByRunner,
    pnl: state.pnl,
    runConfig: state.runConfig,
    story: state.story.slice(0, PERSISTED_STORY_LIMIT),
    pnlHistory: state.pnlHistory,
    screen: state.screen,
    selectedRunner: state.selectedRunner,
  };
}
