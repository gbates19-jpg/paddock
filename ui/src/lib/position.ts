// Position maths — everything the screens say about "where am I" is
// derived here from the order events, nothing else. Commission is NOT
// applied (the engine's pnl.update carries the commissioned figure; these
// are the standard pre-commission exposure numbers a Betfair screen shows).
import type { OrderEvent } from "./events";

export interface RunnerPosition {
  backStake: number; // matched back stake on this runner
  backAvg: number | null; // average matched back price
  layStake: number; // matched lay stake
  layAvg: number | null;
  restingBack: number; // unmatched size still working
  restingLay: number;
  ifWin: number; // P&L on this runner's OWN orders if it wins
  ifLose: number; // ...if it loses
  hasPosition: boolean;
}

function isLive(o: OrderEvent): boolean {
  return o.type !== "order.cancelled" && o.type !== "order.lapsed";
}

export function runnerPosition(orders: OrderEvent[]): RunnerPosition {
  let backStake = 0;
  let backWeighted = 0;
  let layStake = 0;
  let layWeighted = 0;
  let restingBack = 0;
  let restingLay = 0;
  for (const o of orders) {
    const m = o.matched_size;
    if (o.side === "back") {
      backStake += m;
      backWeighted += m * o.price;
      if (isLive(o)) restingBack += Math.max(0, o.size - m);
    } else {
      layStake += m;
      layWeighted += m * o.price;
      if (isLive(o)) restingLay += Math.max(0, o.size - m);
    }
  }
  const backAvg = backStake > 0 ? backWeighted / backStake : null;
  const layAvg = layStake > 0 ? layWeighted / layStake : null;
  // back: win +stake*(price-1), lose -stake. lay: win -stake*(price-1), lose +stake
  const ifWin = backStake * ((backAvg ?? 1) - 1) - layStake * ((layAvg ?? 1) - 1);
  const ifLose = -backStake + layStake;
  return {
    backStake,
    backAvg,
    layStake,
    layAvg,
    restingBack,
    restingLay,
    ifWin: round2(ifWin),
    ifLose: round2(ifLose),
    hasPosition: backStake > 0 || layStake > 0 || restingBack > 0 || restingLay > 0,
  };
}

// Exposure per runner ACROSS the market: our orders on other runners
// affect this runner's if-win too (a back on X loses its stake if Y wins).
export function marketExposure(
  ordersByRunner: Record<number, OrderEvent[]>,
  selectionIds: number[]
): Record<number, { ifWin: number }> {
  const positions: Record<number, RunnerPosition> = {};
  for (const sid of selectionIds) positions[sid] = runnerPosition(ordersByRunner[sid] ?? []);
  const out: Record<number, { ifWin: number }> = {};
  for (const sid of selectionIds) {
    let total = positions[sid].ifWin;
    for (const other of selectionIds) {
      if (other === sid) continue;
      total += positions[other].ifLose;
    }
    out[sid] = { ifWin: round2(total) };
  }
  return out;
}

// What a closing (hedging) trade at the current touch would lock in on
// every outcome. Net back -> lay to close at best lay; net lay -> back to
// close at best back. Returns null when flat or no price to close at.
export function hedge(
  pos: RunnerPosition,
  bestBack: number | null,
  bestLay: number | null
): { side: "back" | "lay"; price: number; size: number; locks: number } | null {
  const netBackLiability = pos.backStake * ((pos.backAvg ?? 1) - 1); // what we win if it wins, from backs
  const netLayLiability = pos.layStake * ((pos.layAvg ?? 1) - 1);
  const winIf = netBackLiability - netLayLiability; // ifWin from own orders
  const loseIf = -pos.backStake + pos.layStake;
  if (Math.abs(winIf - loseIf) < 0.005) return null; // already flat/green
  if (winIf > loseIf) {
    // long the runner: lay to close
    if (!bestLay) return null;
    const size = (winIf - loseIf) / bestLay;
    return { side: "lay", price: bestLay, size: round2(size), locks: round2(loseIf + size) };
  }
  if (!bestBack) return null;
  const size = (loseIf - winIf) / bestBack;
  return { side: "back", price: bestBack, size: round2(size), locks: round2(winIf + size * (bestBack - 1)) };
}

export function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

export function money(n: number, withSign = true): string {
  const s = Math.abs(n).toFixed(2);
  if (n < -0.004) return `−£${s}`;
  if (n > 0.004) return `${withSign ? "+" : ""}£${s}`;
  return "£0.00";
}
