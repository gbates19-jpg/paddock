// RACE CARD — "what position am I in, on which runner, at what price?"
// Runners are rows, not lanes on a track: each one is read left to right
// like a line in a racing paper. Anything we hold shows an amber edge and
// an IF-WIN / IF-LOSE column; market data on its own stays neutral.

import { useNow } from "../lib/hooks";
import { useEventStore, runnerKey } from "../store/eventStore";
import { money, runnerPosition } from "../lib/position";
import { colors, fonts, isMobile } from "../theme";
import type { MarketOpen } from "../lib/events";

// Phone screens are ~390px wide: the desktop column widths leave almost
// nothing for the runner name (the one thing you need to identify a row),
// so mobile gets its own, tighter set of fixed widths plus a smaller gap.
function gridColumns(): string {
  return isMobile() ? "3px 1fr 52px 52px 46px 60px" : "3px 1fr 74px 74px 60px 84px";
}
function gridGap(): number {
  return isMobile() ? 6 : 10;
}

// Muted identifying swatches — decorative scanning aid, not "ours" (that's
// amber alone, per the palette rule).
const SWATCHES = ["#5b6b8c", "#8c6b5b", "#5b8c72", "#8c5b7a", "#6b5b8c", "#8c8c5b", "#5b7a8c", "#7a8c5b"];

function countdown(offTime: string | null, now: number): { label: string; urgent: boolean } {
  if (!offTime) return { label: "—", urgent: false };
  const ms = new Date(offTime).getTime() - now;
  if (ms <= 0) return { label: "OFF", urgent: true };
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return { label: `${m}:${s.toString().padStart(2, "0")}`, urgent: ms < 60_000 };
}

function impliedProb(price: number | null): number {
  if (!price || price <= 1) return 0;
  return 1 / price;
}

function StatusPill({ closed, urgent }: { closed: boolean; urgent: boolean }) {
  const label = closed ? "CLOSED" : urgent ? "IN-PLAY SOON" : "PRE-OFF";
  const color = closed ? colors.textFaint : urgent ? colors.warn : colors.live;
  return (
    <span
      style={{
        fontFamily: fonts.mono,
        fontSize: 10,
        letterSpacing: "0.08em",
        color,
        border: `1px solid ${color}55`,
        borderRadius: 999,
        padding: "2px 8px",
      }}
    >
      {label}
    </span>
  );
}

function TickArrow({ dir }: { dir: 1 | -1 | 0 | undefined }) {
  if (!dir) return <span style={{ width: 10, display: "inline-block" }} />;
  return (
    <span style={{ color: dir === 1 ? colors.pos : colors.neg, fontSize: 11, width: 10, display: "inline-block" }}>{dir === 1 ? "▲" : "▼"}</span>
  );
}

function RunnerRow({ market, selectionId, name, swatch }: { market: MarketOpen; selectionId: number; name: string | null; swatch: string }) {
  const key = runnerKey(market.market_id, selectionId);
  const rp = useEventStore((s) => s.runnerPrices[key]);
  const tickDir = useEventStore((s) => s.tickDir[key]);
  const ordersRecord = useEventStore((s) => s.ordersByRunner[key]);
  const selectRunner = useEventStore((s) => s.selectRunner);

  const orders = ordersRecord ? Object.values(ordersRecord) : [];
  const pos = runnerPosition(orders);
  const bestBack = rp?.back[0]?.price ?? null;
  const bestLay = rp?.lay[0]?.price ?? null;
  const bestBackSize = rp?.back[0]?.size ?? null;
  const bestLaySize = rp?.lay[0]?.size ?? null;
  const prob = impliedProb(rp?.ltp ?? bestBack);
  const mobile = isMobile();
  const priceFont = mobile ? 11 : 12.5;

  return (
    <button
      onClick={() => selectRunner(market.market_id, selectionId)}
      style={{
        display: "grid",
        gridTemplateColumns: gridColumns(),
        alignItems: "center",
        gap: gridGap(),
        width: "100%",
        textAlign: "left",
        padding: "9px 10px 9px 0",
        background: "transparent",
        border: "none",
        borderBottom: `1px solid ${colors.panelBorder}`,
        cursor: "pointer",
        color: "inherit",
        font: "inherit",
      }}
    >
      <span style={{ alignSelf: "stretch", background: pos.hasPosition ? colors.ours : "transparent", borderRadius: 2 }} />

      <span style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 0 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: swatch, flexShrink: 0 }} />
          <span style={{ fontFamily: fonts.sans, fontSize: 13.5, fontWeight: 600, color: colors.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {name ?? `#${selectionId}`}
          </span>
        </span>
        <span style={{ height: 3, borderRadius: 2, background: colors.panel2, overflow: "hidden" }}>
          <span style={{ display: "block", height: "100%", width: `${Math.min(100, prob * 100)}%`, background: colors.textDim }} />
        </span>
      </span>

      <span style={{ fontFamily: fonts.mono, fontSize: priceFont, textAlign: "right" }}>
        {bestBack != null ? (
          <>
            <div style={{ color: colors.back, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{bestBack.toFixed(2)}</div>
            <div style={{ color: colors.textFaint, fontSize: 10 }}>{bestBackSize?.toFixed(0)}</div>
          </>
        ) : (
          <span style={{ color: colors.textFaint }}>—</span>
        )}
      </span>

      <span style={{ fontFamily: fonts.mono, fontSize: priceFont, textAlign: "right" }}>
        {bestLay != null ? (
          <>
            <div style={{ color: colors.lay, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{bestLay.toFixed(2)}</div>
            <div style={{ color: colors.textFaint, fontSize: 10 }}>{bestLaySize?.toFixed(0)}</div>
          </>
        ) : (
          <span style={{ color: colors.textFaint }}>—</span>
        )}
      </span>

      <span style={{ fontFamily: fonts.mono, fontSize: priceFont, textAlign: "right", display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 3 }}>
        <TickArrow dir={tickDir} />
        <span style={{ color: colors.text, fontVariantNumeric: "tabular-nums" }}>{rp?.ltp?.toFixed(2) ?? "—"}</span>
      </span>

      <span style={{ fontFamily: fonts.mono, fontSize: mobile ? 10.5 : 11.5, textAlign: "right" }}>
        {pos.hasPosition ? (
          <>
            <div style={{ color: pos.ifWin >= 0 ? colors.pos : colors.neg, fontWeight: 600 }}>{money(pos.ifWin)}</div>
            <div style={{ color: pos.ifLose >= 0 ? colors.pos : colors.neg, fontSize: 10 }}>{money(pos.ifLose)}</div>
          </>
        ) : (
          <span style={{ color: colors.textFaint }}>—</span>
        )}
      </span>
    </button>
  );
}

function ColumnHeader() {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: gridColumns(),
        gap: gridGap(),
        padding: "0 10px 6px 0",
        fontFamily: fonts.mono,
        fontSize: 9.5,
        letterSpacing: "0.06em",
        color: colors.textFaint,
      }}
    >
      <span />
      <span>RUNNER</span>
      <span style={{ textAlign: "right" }}>BACK</span>
      <span style={{ textAlign: "right" }}>LAY</span>
      <span style={{ textAlign: "right" }}>LTP</span>
      <span style={{ textAlign: "right" }}>WIN / LOSE</span>
    </div>
  );
}

function MarketCard({ market }: { market: MarketOpen }) {
  const now = useNow(1000);
  const closedMarkets = useEventStore((s) => s.closedMarkets);
  const closed = !!closedMarkets[market.market_id];
  const { label, urgent } = countdown(market.off_time, now);

  return (
    <div style={{ background: colors.panel, border: `1px solid ${colors.panelBorder}`, borderRadius: 12, padding: "12px 12px 4px", marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10, gap: 10 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: fonts.sans, fontSize: 14.5, fontWeight: 700, color: colors.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {market.race_name ?? market.venue ?? market.market_id}
          </div>
          <div style={{ fontFamily: fonts.mono, fontSize: 11, color: colors.textFaint }}>{market.runners.length} runners</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          <StatusPill closed={closed} urgent={urgent} />
          <span style={{ fontFamily: fonts.mono, fontSize: 16, fontWeight: 700, color: urgent && !closed ? colors.warn : colors.text, fontVariantNumeric: "tabular-nums", minWidth: 44, textAlign: "right" }}>
            {label}
          </span>
        </div>
      </div>
      <ColumnHeader />
      <div>
        {market.runners.map((r, i) => (
          <RunnerRow key={r.selection_id} market={market} selectionId={r.selection_id} name={r.name} swatch={SWATCHES[i % SWATCHES.length]} />
        ))}
      </div>
    </div>
  );
}

export function RaceScreen() {
  const markets = useEventStore((s) => s.markets);
  const closedMarkets = useEventStore((s) => s.closedMarkets);
  const list = Object.values(markets).sort((a, b) => {
    const aClosed = !!closedMarkets[a.market_id];
    const bClosed = !!closedMarkets[b.market_id];
    if (aClosed !== bClosed) return aClosed ? 1 : -1;
    const ta = a.off_time ? new Date(a.off_time).getTime() : Infinity;
    const tb = b.off_time ? new Date(b.off_time).getTime() : Infinity;
    return ta - tb;
  });

  if (list.length === 0) {
    return (
      <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: colors.textFaint, fontFamily: fonts.sans, fontSize: 13 }}>
        waiting for a market to open…
      </div>
    );
  }

  return (
    <div style={{ height: "100%", overflowY: "auto", padding: "8px 14px 16px" }}>
      {list.map((m) => (
        <MarketCard key={m.market_id} market={m} />
      ))}
    </div>
  );
}
