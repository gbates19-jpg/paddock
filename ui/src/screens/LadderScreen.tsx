// LADDER — the industry layout traders already know: LAY | PRICE | BACK,
// vertical, best price near the middle. Our orders sit in their own cell
// as amber chips; a fill flashes the row; the header carries our net
// position and what closing right now would lock in.
//
// The brief called for a fourth TRADED column (volume-at-price). The bus
// only carries aggregate traded_volume, not a per-price trade ladder —
// adding that is an engine change, out of scope here — so total traded
// volume stays in the header instead of a histogram column that would
// have to be invented.
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useEventStore, runnerKey } from "../store/eventStore";
import { hedge, money, runnerPosition } from "../lib/position";
import { snapToTick, ticksBetween, tickDown, tickUp } from "../lib/ticks";
import { colors, fonts } from "../theme";
import type { OrderEvent, PriceLevel } from "../lib/events";

const DEPTH_ROWS = 3;
const HALF_WINDOW = 8;

function maxSize(levels: PriceLevel[]): number {
  return Math.max(1, ...levels.map((l) => l.size));
}

function OrderChip({ order }: { order: OrderEvent }) {
  const isBack = order.side === "back";
  const complete = order.matched_size >= order.size;
  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.5 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.4 }}
      transition={{ type: "spring", stiffness: 450, damping: 26 }}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 7px",
        borderRadius: 999,
        fontSize: 10.5,
        fontFamily: fonts.mono,
        fontWeight: 600,
        background: colors.oursDim,
        border: `1px solid ${colors.ours}`,
        color: colors.ours,
      }}
    >
      {isBack ? "B" : "L"} {order.price} · {order.matched_size}/{order.size}
      {complete && order.matched_size > 0 ? " ✓" : ""}
    </motion.div>
  );
}

function Row({
  price,
  backSize,
  laySize,
  maxBack,
  maxLay,
  isLtp,
  ordersAtPrice,
}: {
  price: number;
  backSize: number;
  laySize: number;
  maxBack: number;
  maxLay: number;
  isLtp: boolean;
  ordersAtPrice: OrderEvent[];
}) {
  return (
    <div
      style={{
        background: isLtp ? colors.oursDim : "transparent",
        boxShadow: isLtp ? `inset 0 0 0 1px ${colors.ours}55` : undefined,
        borderRadius: 6,
      }}
    >
      <div style={{ display: "grid", gridTemplateColumns: "1fr 74px 1fr", alignItems: "center", height: 28 }}>
        <div style={{ display: "flex", justifyContent: "flex-end", paddingRight: 2 }}>
          {laySize > 0 && (
            <motion.div
              animate={{ width: `${(laySize / maxLay) * 100}%` }}
              transition={{ duration: 0.25 }}
              style={{
                height: 18,
                background: colors.layDim,
                borderRight: `2px solid ${colors.lay}`,
                display: "flex",
                alignItems: "center",
                justifyContent: "flex-end",
                paddingRight: 6,
                fontSize: 10.5,
                color: colors.lay,
                fontFamily: fonts.mono,
                minWidth: 2,
              }}
            >
              {laySize.toFixed(0)}
            </motion.div>
          )}
        </div>
        <div
          style={{
            textAlign: "center",
            fontFamily: fonts.mono,
            fontSize: 13,
            fontWeight: 700,
            color: isLtp ? colors.ours : backSize > 0 || laySize > 0 ? colors.text : colors.textFaint,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {price.toFixed(2)}
        </div>
        <div style={{ display: "flex", justifyContent: "flex-start", paddingLeft: 2 }}>
          {backSize > 0 && (
            <motion.div
              animate={{ width: `${(backSize / maxBack) * 100}%` }}
              transition={{ duration: 0.25 }}
              style={{
                height: 18,
                background: colors.backDim,
                borderLeft: `2px solid ${colors.back}`,
                display: "flex",
                alignItems: "center",
                paddingLeft: 6,
                fontSize: 10.5,
                color: colors.back,
                fontFamily: fonts.mono,
                minWidth: 2,
              }}
            >
              {backSize.toFixed(0)}
            </motion.div>
          )}
        </div>
      </div>
      {ordersAtPrice.length > 0 && (
        <div style={{ display: "flex", gap: 4, justifyContent: "center", paddingBottom: 4 }}>
          <AnimatePresence>
            {ordersAtPrice.map((o) => (
              <OrderChip key={o.order_id} order={o} />
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}

function Placeholder({ text }: { text: string }) {
  return (
    <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: colors.textFaint, fontFamily: fonts.sans, fontSize: 13 }}>
      {text}
    </div>
  );
}

export function LadderScreen() {
  const selected = useEventStore((s) => s.selectedRunner);
  const markets = useEventStore((s) => s.markets);
  const runnerPrices = useEventStore((s) => s.runnerPrices);
  const ordersByRunner = useEventStore((s) => s.ordersByRunner);
  const clear = useEventStore((s) => s.clearSelectedRunner);

  const scrollRef = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);
  const idleTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Every hook below must run on every render regardless of `selected` —
  // React's rules of hooks forbid an early return before them, so the
  // "nothing selected" case is handled once, in the JSX at the bottom,
  // rather than bailing out here (that would change the hook count
  // between the null and non-null renders).
  const key = selected ? runnerKey(selected.marketId, selected.selectionId) : null;
  const rp = key ? runnerPrices[key] : undefined;
  const market = selected ? markets[selected.marketId] : undefined;
  const runner = market?.runners.find((r) => r.selection_id === selected?.selectionId);
  const orders = key ? Object.values(ordersByRunner[key] ?? {}) : [];
  const pos = runnerPosition(orders);
  const hasDepth = !!rp && (rp.back.length > 0 || rp.lay.length > 0);

  const observedBack = rp?.back.slice(0, DEPTH_ROWS) ?? [];
  const observedLay = rp?.lay.slice(0, DEPTH_ROWS) ?? [];
  const bestBack = observedBack[0]?.price ?? null;
  const bestLay = observedLay[0]?.price ?? null;
  const closeHedge = hasDepth ? hedge(pos, bestBack, bestLay) : null;

  const touchMid = bestBack != null && bestLay != null ? (bestBack + bestLay) / 2 : bestBack ?? bestLay ?? null;
  const ltpFarFromTouch =
    rp?.ltp != null && touchMid != null && ticksBetween(Math.min(rp.ltp, touchMid), Math.max(rp.ltp, touchMid), HALF_WINDOW + 1).length > HALF_WINDOW - 1;
  const rawCentre = (ltpFarFromTouch ? touchMid : rp?.ltp) ?? touchMid ?? orders[0]?.price ?? 0;
  const centre = rawCentre > 0 ? snapToTick(rawCentre) : 0;

  let hi = centre;
  let lo = centre;
  for (let i = 0; i < HALF_WINDOW; i++) {
    hi = tickUp(hi);
    lo = tickDown(lo);
  }
  const inWindow = (p: number) => p >= lo - 1e-9 && p <= hi + 1e-9;
  const priceSet = new Set<number>(centre > 0 ? ticksBetween(lo, hi, HALF_WINDOW * 2 + 1) : []);
  observedBack.forEach((l) => inWindow(l.price) && priceSet.add(l.price));
  observedLay.forEach((l) => inWindow(l.price) && priceSet.add(l.price));
  orders.forEach((o) => inWindow(o.price) && priceSet.add(o.price));
  const rows = Array.from(priceSet).sort((a, b) => b - a);
  const maxBack = maxSize(observedBack);
  const maxLay = maxSize(observedLay);

  // Auto-centre unless the person is actively scrolling the ladder by
  // hand — a manual scroll suspends follow for a few seconds rather than
  // fighting their gesture, per the brief's "auto-centres... and pins
  // while you scroll it by hand".
  useEffect(() => {
    if (!following) return;
    const el = scrollRef.current;
    const target = el?.querySelector<HTMLElement>("[data-ltp-row]");
    if (el && target) {
      el.scrollTo({ top: target.offsetTop - el.clientHeight / 2 + target.clientHeight / 2, behavior: "smooth" });
    }
  }, [following, centre, rows.length]);

  function onManualScroll() {
    setFollowing(false);
    if (idleTimer.current) clearTimeout(idleTimer.current);
    idleTimer.current = setTimeout(() => setFollowing(true), 4000);
  }

  if (!selected) return <Placeholder text="pick a runner on the race card to open its ladder" />;

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", padding: "8px 14px 10px", position: "relative" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4, flexWrap: "wrap" }}>
        <span style={{ fontFamily: fonts.sans, fontSize: 15, fontWeight: 700, color: colors.text }}>{runner?.name ?? `#${selected.selectionId}`}</span>
        <span style={{ fontFamily: fonts.mono, fontSize: 11, color: colors.textFaint }}>{market?.venue} {market?.race_name}</span>
        {rp?.traded_volume != null && (
          <span style={{ fontFamily: fonts.mono, fontSize: 11, color: colors.textFaint }}>vol {rp.traded_volume.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
        )}
        <button
          onClick={clear}
          style={{ marginLeft: "auto", background: "transparent", border: `1px solid ${colors.panelBorderStrong}`, color: colors.textDim, borderRadius: 6, padding: "4px 10px", fontSize: 11.5, cursor: "pointer", fontFamily: fonts.sans }}
        >
          ← race card
        </button>
      </div>

      {pos.hasPosition && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 14,
            alignItems: "baseline",
            background: colors.oursDim,
            border: `1px solid ${colors.ours}40`,
            borderRadius: 8,
            padding: "7px 12px",
            marginBottom: 8,
            fontFamily: fonts.mono,
            fontSize: 11.5,
          }}
        >
          {pos.backStake > 0 && <span style={{ color: colors.back }}>back {pos.backStake.toFixed(0)} @ {pos.backAvg?.toFixed(2)}</span>}
          {pos.layStake > 0 && <span style={{ color: colors.lay }}>lay {pos.layStake.toFixed(0)} @ {pos.layAvg?.toFixed(2)}</span>}
          <span style={{ color: colors.textDim }}>
            if win <span style={{ color: pos.ifWin >= 0 ? colors.pos : colors.neg, fontWeight: 700 }}>{money(pos.ifWin)}</span>
            {"  "}if lose <span style={{ color: pos.ifLose >= 0 ? colors.pos : colors.neg, fontWeight: 700 }}>{money(pos.ifLose)}</span>
          </span>
          {closeHedge && (
            <span style={{ color: colors.ours, marginLeft: "auto" }}>
              close now: {closeHedge.side} {closeHedge.size.toFixed(2)} @ {closeHedge.price.toFixed(2)} → locks {money(closeHedge.locks)}
            </span>
          )}
        </div>
      )}

      {!rp && <Placeholder text="waiting for price data on this runner…" />}

      {rp && !hasDepth && (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10 }}>
          <div style={{ fontFamily: fonts.mono, fontSize: 12, color: colors.warn }}>NO DEPTH DATA</div>
          <div style={{ fontFamily: fonts.sans, fontSize: 12.5, color: colors.textDim, textAlign: "center", maxWidth: 300 }}>
            This market is Basic Plan — only last-traded-price is available, no order book.
          </div>
          <div style={{ fontFamily: fonts.mono, fontSize: 24, fontWeight: 700, color: colors.text }}>{rp.ltp ?? "—"}</div>
          {orders.length > 0 && (
            <div style={{ display: "flex", gap: 6 }}>
              {orders.map((o) => (
                <OrderChip key={o.order_id} order={o} />
              ))}
            </div>
          )}
        </div>
      )}

      {rp && hasDepth && (
        <div
          ref={scrollRef}
          onWheel={onManualScroll}
          onTouchMove={onManualScroll}
          style={{ flex: 1, minHeight: 0, overflowY: "auto", position: "relative" }}
        >
          <div style={{ display: "grid", gridTemplateColumns: "1fr 74px 1fr", padding: "0 0 4px", fontFamily: fonts.mono, fontSize: 9.5, letterSpacing: "0.06em", color: colors.textFaint }}>
            <span style={{ textAlign: "right", paddingRight: 8 }}>LAY</span>
            <span style={{ textAlign: "center" }}>PRICE</span>
            <span style={{ textAlign: "left", paddingLeft: 8 }}>BACK</span>
          </div>
          {rows.map((price) => {
            const back = observedBack.find((l) => l.price === price);
            const lay = observedLay.find((l) => l.price === price);
            const isLtp = rp.ltp != null && Math.abs(price - rp.ltp) < 1e-6;
            const ordersAtPrice = orders.filter((o) => o.price === price);
            return (
              <div key={price} data-ltp-row={isLtp ? "" : undefined}>
                <Row price={price} backSize={back?.size ?? 0} laySize={lay?.size ?? 0} maxBack={maxBack} maxLay={maxLay} isLtp={isLtp} ordersAtPrice={ordersAtPrice} />
              </div>
            );
          })}
        </div>
      )}

      {!following && hasDepth && (
        <button
          onClick={() => setFollowing(true)}
          style={{
            position: "absolute",
            bottom: 12,
            left: "50%",
            transform: "translateX(-50%)",
            background: colors.panel2,
            border: `1px solid ${colors.panelBorderStrong}`,
            color: colors.text,
            borderRadius: 999,
            padding: "5px 12px",
            fontFamily: fonts.mono,
            fontSize: 11,
            cursor: "pointer",
          }}
        >
          re-centre
        </button>
      )}
    </div>
  );
}
