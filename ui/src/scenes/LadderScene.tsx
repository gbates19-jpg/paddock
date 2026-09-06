import { AnimatePresence, motion } from "framer-motion";
import { runnerKey, useEventStore } from "../store/eventStore";
import type { OrderEvent, PriceLevel } from "../lib/events";
import { ticksBetween, tickDown, tickUp } from "../lib/ticks";
import { colors, colorsCss, fonts } from "../theme";

const DEPTH_ROWS = 3;
const LADDER_WINDOW = 10;

function maxSize(levels: PriceLevel[]): number {
  return Math.max(1, ...levels.map((l) => l.size));
}

function OrderChip({ order }: { order: OrderEvent }) {
  const isBack = order.side === "back";
  const complete = order.matched_size >= order.size;
  return (
    <motion.div
      key={complete ? `${order.order_id}-matched` : order.order_id}
      layout
      initial={{ opacity: 0, scale: 0.4, y: isBack ? 6 : -6 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.3 }}
      transition={{ type: "spring", stiffness: 420, damping: 24 }}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 999,
        fontSize: 11,
        fontFamily: fonts.mono,
        background: isBack ? "rgba(79, 209, 255, 0.18)" : "rgba(255, 138, 92, 0.18)",
        border: `1px solid ${isBack ? colorsCss.back : colorsCss.lay}`,
        color: isBack ? colorsCss.back : colorsCss.lay,
      }}
    >
      {order.side.toUpperCase()} {order.price} · {order.matched_size}/{order.size}
      {complete && order.matched_size > 0 ? " ✓" : ""}
    </motion.div>
  );
}

function LadderRow({
  price,
  backSize,
  laySize,
  maxBackSize,
  maxLaySize,
  ordersAtPrice,
  isSpread,
}: {
  price: number;
  backSize: number;
  laySize: number;
  maxBackSize: number;
  maxLaySize: number;
  ordersAtPrice: OrderEvent[];
  isSpread: boolean;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 90px 1fr",
        alignItems: "center",
        height: 30,
        background: isSpread ? "rgba(255,255,255,0.02)" : "transparent",
      }}
    >
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        {backSize > 0 && (
          <motion.div
            animate={{ width: `${(backSize / maxBackSize) * 100}%` }}
            transition={{ duration: 0.25 }}
            style={{
              height: 20,
              background: "rgba(79, 209, 255, 0.35)",
              borderRadius: "4px 0 0 4px",
              display: "flex",
              alignItems: "center",
              justifyContent: "flex-end",
              paddingRight: 6,
              fontSize: 11,
              color: "#cdeeff",
              fontFamily: fonts.mono,
              minWidth: 2,
            }}
          >
            {backSize.toFixed(0)}
          </motion.div>
        )}
      </div>
      <div
        style={{
          textAlign: "center",
          fontFamily: fonts.mono,
          fontSize: 13,
          fontWeight: 600,
          color: backSize > 0 || laySize > 0 ? colors.text : colors.textFaint,
        }}
      >
        {price.toFixed(2)}
      </div>
      <div style={{ display: "flex", justifyContent: "flex-start" }}>
        {laySize > 0 && (
          <motion.div
            animate={{ width: `${(laySize / maxLaySize) * 100}%` }}
            transition={{ duration: 0.25 }}
            style={{
              height: 20,
              background: "rgba(255, 138, 92, 0.35)",
              borderRadius: "0 4px 4px 0",
              display: "flex",
              alignItems: "center",
              paddingLeft: 6,
              fontSize: 11,
              color: "#ffd9c4",
              fontFamily: fonts.mono,
              minWidth: 2,
            }}
          >
            {laySize.toFixed(0)}
          </motion.div>
        )}
      </div>
      {ordersAtPrice.length > 0 && (
        <div style={{ gridColumn: "1 / -1", display: "flex", gap: 4, justifyContent: "center", marginTop: -2 }}>
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

export function LadderScene() {
  const selected = useEventStore((s) => s.selectedRunner);
  const markets = useEventStore((s) => s.markets);
  const runnerPrices = useEventStore((s) => s.runnerPrices);
  const ordersByRunner = useEventStore((s) => s.ordersByRunner);
  const clear = useEventStore((s) => s.clearSelectedRunner);

  if (!selected) {
    return (
      <Placeholder text="click a runner in The Paddock to open its ladder" />
    );
  }

  const key = runnerKey(selected.marketId, selected.selectionId);
  const rp = runnerPrices[key];
  const market = markets[selected.marketId];
  const runner = market?.runners.find((r) => r.selection_id === selected.selectionId);
  const orders = Object.values(ordersByRunner[key] ?? {});

  const hasDepth = !!rp && (rp.back.length > 0 || rp.lay.length > 0);

  const backMatched = orders.filter((o) => o.side === "back").reduce((s, o) => s + o.matched_size, 0);
  const layMatched = orders.filter((o) => o.side === "lay").reduce((s, o) => s + o.matched_size, 0);
  const isGreen = backMatched > 0 && layMatched >= backMatched - 0.01;

  return (
    <div style={{ width: "100%", height: "100%", padding: "24px 32px", overflow: "auto" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 16 }}>
        <div style={{ fontFamily: fonts.sans, fontSize: 16, fontWeight: 600, color: colors.text }}>
          {runner?.name ?? `#${selected.selectionId}`}
        </div>
        <div style={{ fontFamily: fonts.mono, fontSize: 12, color: colors.textDim }}>
          {market?.venue} {market?.race_name}
        </div>
        {rp?.traded_volume != null && (
          <div style={{ fontFamily: fonts.mono, fontSize: 12, color: colors.textDim }}>
            vol {rp.traded_volume.toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </div>
        )}
        <button
          onClick={clear}
          style={{
            marginLeft: "auto",
            background: "transparent",
            border: "1px solid rgba(255,255,255,0.15)",
            color: colors.textDim,
            borderRadius: 6,
            padding: "4px 10px",
            fontSize: 12,
            cursor: "pointer",
          }}
        >
          ← back to Paddock
        </button>
      </div>

      {!rp && <Placeholder text="waiting for price data on this runner…" />}

      {rp && !hasDepth && (
        <div
          style={{
            borderRadius: 12,
            border: "1px dashed rgba(255,255,255,0.15)",
            padding: "32px 24px",
            textAlign: "center",
            color: "#7c8496",
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          }}
        >
          <div style={{ fontSize: 13, marginBottom: 8, color: "#ffb84f" }}>NO DEPTH DATA</div>
          <div style={{ fontSize: 12 }}>
            This market is Basic Plan — only last-traded-price is available, no order book.
          </div>
          <div style={{ fontSize: 20, marginTop: 16, color: "#e4e8f0" }}>ltp {rp.ltp ?? "—"}</div>
          {orders.length > 0 && (
            <div style={{ marginTop: 16, display: "flex", gap: 6, justifyContent: "center" }}>
              {orders.map((o) => (
                <OrderChip key={o.order_id} order={o} />
              ))}
            </div>
          )}
        </div>
      )}

      {rp && hasDepth && (
        <div style={{ position: "relative" }}>
          {isGreen && (
            <div
              style={{
                position: "absolute",
                inset: -8,
                background: "rgba(53, 224, 122, 0.08)",
                border: "1px solid rgba(53, 224, 122, 0.3)",
                borderRadius: 8,
                pointerEvents: "none",
              }}
            />
          )}
          <div style={{ position: "relative" }}>
            {(() => {
              const observedBack = rp.back.slice(0, DEPTH_ROWS);
              const observedLay = rp.lay.slice(0, DEPTH_ROWS);
              const maxBack = maxSize(observedBack);
              const maxLay = maxSize(observedLay);
              const bestBack = observedBack[0]?.price;
              const bestLay = observedLay[0]?.price;

              // Fill the gap between best-lay and best-back, AND a few
              // ticks beyond each touch price, with real ladder ticks —
              // not just the sparse levels the feed happened to report.
              // A tight one-tick spread (common near the top of the book)
              // would otherwise render as just two floating bars; real
              // ladders always show empty rows beyond the touch too.
              const rawHi = Math.max(bestLay ?? 0, bestBack ?? 0, ...orders.map((o) => o.price));
              const rawLo = Math.min(bestLay ?? rawHi, bestBack ?? rawHi, ...orders.map((o) => o.price));
              const hi = rawHi > 0 ? tickUp(tickUp(rawHi)) : 0;
              const lo = rawHi > 0 ? tickDown(tickDown(rawLo)) : 0;
              const tickRows = hi > 0 ? ticksBetween(lo, hi, LADDER_WINDOW) : [];

              const prices = new Set<number>(tickRows);
              observedBack.forEach((l) => prices.add(l.price));
              observedLay.forEach((l) => prices.add(l.price));
              orders.forEach((o) => prices.add(o.price));
              const sortedPrices = Array.from(prices).sort((a, b) => b - a);

              return sortedPrices.map((price) => {
                const back = observedBack.find((l) => l.price === price);
                const lay = observedLay.find((l) => l.price === price);
                const ordersAtPrice = orders.filter((o) => o.price === price);
                const isSpread = bestBack != null && bestLay != null && price < bestLay && price > bestBack;
                return (
                  <LadderRow
                    key={price}
                    price={price}
                    backSize={back?.size ?? 0}
                    laySize={lay?.size ?? 0}
                    maxBackSize={maxBack}
                    maxLaySize={maxLay}
                    ordersAtPrice={ordersAtPrice}
                    isSpread={isSpread}
                  />
                );
              });
            })()}
          </div>
          <div style={{ marginTop: 12, fontFamily: fonts.mono, fontSize: 12, color: colors.textDim }}>
            ltp {rp.ltp ?? "—"} {isGreen && <span style={{ color: colorsCss.pnlPos }}>· hedged flat</span>}
          </div>
        </div>
      )}
    </div>
  );
}

function Placeholder({ text }: { text: string }) {
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: colors.textDim,
        fontFamily: fonts.mono,
        fontSize: 13,
      }}
    >
      {text}
    </div>
  );
}
