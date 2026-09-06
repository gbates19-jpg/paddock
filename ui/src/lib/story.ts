// The Story feed: every significant bus event rewritten as a sentence a
// person would say out loud. This is the direct fix for "it means
// nothing" — the screens show state, the story says what just happened
// and why. Pure function of (event, what we already know).
import type { MarketOpen, OrderEvent, PaddockEvent } from "./events";
import { money } from "./position";

export type StoryKind = "market" | "signal" | "order" | "fill" | "cancel" | "pnl" | "alert" | "system";
export type StoryTone = "neutral" | "ours" | "good" | "bad";

export interface StoryEntry {
  id: string;
  ts: number;
  kind: StoryKind;
  tone: StoryTone;
  headline: string; // short, bold — "BACK matched"
  detail: string; // the sentence
  marketId?: string;
  selectionId?: number;
}

export interface StoryContext {
  markets: Record<string, MarketOpen>;
  // the previous known state of this order id, if any (to phrase matches)
  previousOrder?: OrderEvent;
  runPnlBefore?: number | null;
}

function runnerName(ctx: StoryContext, marketId: string, selectionId: number): string {
  const r = ctx.markets[marketId]?.runners.find((x) => x.selection_id === selectionId);
  return r?.name ?? `#${selectionId}`;
}

function raceName(ctx: StoryContext, marketId: string): string {
  const m = ctx.markets[marketId];
  return m?.race_name ?? m?.venue ?? marketId;
}

const gbp = (n: number) => `£${n.toFixed(2).replace(/\.00$/, "")}`;

export function storyFor(event: PaddockEvent, ctx: StoryContext): StoryEntry | null {
  const base = { id: event.event_id, ts: event.ts_ms };
  switch (event.type) {
    case "market.open":
      return {
        ...base,
        kind: "market",
        tone: "neutral",
        headline: "Market open",
        detail: `${event.race_name ?? event.market_id} — ${event.runners.length} runners, watching`,
        marketId: event.market_id,
      };
    case "market.close":
      return {
        ...base,
        kind: "market",
        tone: "neutral",
        headline: "Market closed",
        detail: `${raceName(ctx, event.market_id)} is done`,
        marketId: event.market_id,
      };
    case "strategy.signal":
      return {
        ...base,
        kind: "signal",
        tone: "ours",
        headline: "Strategy signal",
        detail: `${runnerName(ctx, event.market_id, event.selection_id)}: ${event.reason}`,
        marketId: event.market_id,
        selectionId: event.selection_id,
      };
    case "order.placed": {
      const side = event.side.toUpperCase();
      return {
        ...base,
        kind: "order",
        tone: "ours",
        headline: `${side} placed`,
        detail: `${gbp(event.size)} ${event.side} at ${event.price} on ${runnerName(ctx, event.market_id, event.selection_id)}, waiting to match`,
        marketId: event.market_id,
        selectionId: event.selection_id,
      };
    }
    case "order.matched": {
      const name = runnerName(ctx, event.market_id, event.selection_id);
      const prevMatched = ctx.previousOrder?.matched_size ?? 0;
      const justNow = event.matched_size - prevMatched;
      const full = event.matched_size >= event.size;
      const side = event.side.toUpperCase();
      return {
        ...base,
        kind: "fill",
        tone: "ours",
        headline: full ? `${side} matched` : `${side} part-matched`,
        detail: full
          ? `${gbp(event.size)} ${event.side} at ${event.price} on ${name} is in`
          : `${gbp(justNow)} of ${gbp(event.size)} ${event.side} at ${event.price} on ${name} matched, ${gbp(event.size - event.matched_size)} still waiting`,
        marketId: event.market_id,
        selectionId: event.selection_id,
      };
    }
    case "order.cancelled":
    case "order.lapsed": {
      const name = runnerName(ctx, event.market_id, event.selection_id);
      const unmatched = event.size - event.matched_size;
      return {
        ...base,
        kind: "cancel",
        tone: "neutral",
        headline: event.type === "order.cancelled" ? `${event.side.toUpperCase()} cancelled` : `${event.side.toUpperCase()} lapsed`,
        detail: `${gbp(unmatched)} ${event.side} at ${event.price} on ${name} pulled${event.matched_size > 0 ? ` (${gbp(event.matched_size)} had matched)` : ""}`,
        marketId: event.market_id,
        selectionId: event.selection_id,
      };
    }
    case "order.rejected":
      return {
        ...base,
        kind: "alert",
        tone: "bad",
        headline: "Order rejected",
        detail: `${event.side} at ${event.price} on ${runnerName(ctx, event.market_id, event.selection_id)}: ${event.reason}`,
        marketId: event.market_id,
        selectionId: event.selection_id,
      };
    case "position.unhedged":
      return {
        ...base,
        kind: "alert",
        tone: "bad",
        headline: "Unhedged",
        detail: `${gbp(event.remaining_size)} ${event.side} left open on ${runnerName(ctx, event.market_id, event.selection_id)} after ${event.attempts} attempts: ${event.reason}`,
        marketId: event.market_id,
        selectionId: event.selection_id,
      };
    case "pnl.update": {
      const before = ctx.runPnlBefore ?? 0;
      const delta = event.run_pnl - before;
      if (Math.abs(delta) < 0.005) return null;
      const where = event.market_id ? ` on ${raceName(ctx, event.market_id)}` : "";
      return {
        ...base,
        kind: "pnl",
        tone: delta >= 0 ? "good" : "bad",
        headline: delta >= 0 ? `Locked ${money(delta)}` : `Lost ${money(delta)}`,
        detail: `run P&L now ${money(event.run_pnl)}${where}`,
        marketId: event.market_id ?? undefined,
      };
    }
    case "log":
      if (event.level === "debug") return null;
      return {
        ...base,
        kind: "system",
        tone: event.level === "error" ? "bad" : "neutral",
        headline: event.level === "error" ? "Engine error" : "Engine",
        detail: event.msg,
      };
    default:
      return null;
  }
}
