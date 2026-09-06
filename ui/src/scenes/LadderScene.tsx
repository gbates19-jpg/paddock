import { AnimatePresence, motion } from "framer-motion";
import { runnerKey, useEventStore } from "../store/eventStore";
import type { OrderEvent, PriceLevel } from "../lib/events";

const DEPTH_ROWS = 3;

function maxSize(levels: PriceLevel[]): number {
  return Math.max(1, ...levels.map((l) => l.size));
}

function OrderChip({ order }: { order: OrderEvent }) {
  const isBack = order.side === "back";
  const complete = order.matched_size >= order.size;
  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.6 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.4 }}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 999,
        fontSize: 11,
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        background: isBack ? "rgba(79, 209, 255, 0.18)" : "rgba(255, 138, 92, 0.18)",
        border: `1px solid ${isBack ? "#4fd1ff" : "#ff8a5c"}`,
        color: isBack ? "#4fd1ff" : "#ff8a5c",
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
}: {
  price: number;
  backSize: number;
  laySize: number;
  maxBackSize: number;
  maxLaySize: number;
  ordersAtPrice: OrderEvent[];
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 90px 1fr", alignItems: "center", height: 30 }}>
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
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
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
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          fontSize: 13,
          fontWeight: 600,
          color: "#e4e8f0",
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
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
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
        <div style={{ fontFamily: "ui-sans-serif, system-ui, sans-serif", fontSize: 16, fontWeight: 600, color: "#e4e8f0" }}>
          {runner?.name ?? `#${selected.selectionId}`}
        </div>
        <div style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 12, color: "#7c8496" }}>
          {market?.venue} {market?.race_name}
        </div>
        <button
          onClick={clear}
          style={{
            marginLeft: "auto",
            background: "transparent",
            border: "1px solid rgba(255,255,255,0.15)",
            color: "#aab4c8",
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
              const maxBack = maxSize(rp.back.slice(0, DEPTH_ROWS));
              const maxLay = maxSize(rp.lay.slice(0, DEPTH_ROWS));
              const prices = new Set<number>();
              rp.back.slice(0, DEPTH_ROWS).forEach((l) => prices.add(l.price));
              rp.lay.slice(0, DEPTH_ROWS).forEach((l) => prices.add(l.price));
              orders.forEach((o) => prices.add(o.price));
              const sortedPrices = Array.from(prices).sort((a, b) => b - a);
              return sortedPrices.map((price) => {
                const back = rp.back.find((l) => l.price === price);
                const lay = rp.lay.find((l) => l.price === price);
                const ordersAtPrice = orders.filter((o) => o.price === price);
                return (
                  <LadderRow
                    key={price}
                    price={price}
                    backSize={back?.size ?? 0}
                    laySize={lay?.size ?? 0}
                    maxBackSize={maxBack}
                    maxLaySize={maxLay}
                    ordersAtPrice={ordersAtPrice}
                  />
                );
              });
            })()}
          </div>
          <div style={{ marginTop: 12, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 12, color: "#7c8496" }}>
            ltp {rp.ltp ?? "—"} {isGreen && <span style={{ color: "#35e07a" }}>· hedged flat</span>}
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
        color: "#7c8496",
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        fontSize: 13,
      }}
    >
      {text}
    </div>
  );
}
