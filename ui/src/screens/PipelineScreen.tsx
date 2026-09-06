// PIPELINE — "what is the engine doing right now?" One module per worker
// stage, each an instrument with its own live number, not a node graph you
// have to interpret. A channel between stages carries a travelling mark
// per event so motion answers "is it working" before you read anything.
// (Deviates from the Phase 0 brief's PixiJS-for-scenes mandate: this is
// plain DOM/CSS — text-heavy instruments and a handful of travelling dots
// don't need a canvas, and it's one less runtime to keep smooth on a
// phone. Flagged to Gary; Pixi stayed for nothing here.)
import { AnimatePresence, motion } from "framer-motion";
import { useNow } from "../lib/hooks";
import { useEventStore } from "../store/eventStore";
import { colors, fonts, prefersReducedMotion } from "../theme";
import { money } from "../lib/position";
import type { WorkerState } from "../lib/events";
import { StoryFeed } from "../components/StoryFeed";

type StageId = "stream" | "strategy" | "executor" | "book";
const STAGES: { id: StageId; label: string }[] = [
  { id: "stream", label: "STREAM" },
  { id: "strategy", label: "STRATEGY" },
  { id: "executor", label: "EXECUTOR" },
  { id: "book", label: "BOOK" },
];

const STATE_COLOR: Record<WorkerState, string> = {
  idle: colors.textFaint,
  busy: colors.live,
  error: colors.neg,
};

function stageState(workers: ReturnType<typeof useEventStore.getState>["workers"], stage: StageId): WorkerState {
  if (stage === "book") return workers["pnl"]?.state ?? "idle";
  if (stage === "stream") return workers["stream"]?.state ?? "idle";
  if (stage === "executor") return workers["executor"]?.state ?? "idle";
  const strategyKey = Object.keys(workers).find((k) => k.startsWith("strategy:"));
  return strategyKey ? workers[strategyKey].state : "idle";
}

function StageCard({ stage, metric, sub }: { stage: StageId; metric: string; sub: string }) {
  const workers = useEventStore((s) => s.workers);
  const state = stageState(workers, stage);
  const label = STAGES.find((s) => s.id === stage)!.label;
  return (
    <div
      style={{
        flex: "1 1 0",
        minWidth: 0,
        background: colors.panel,
        border: `1px solid ${colors.panelBorder}`,
        borderRadius: 12,
        padding: "14px 14px 12px",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span
          className={state === "busy" ? "blink" : undefined}
          style={{ width: 7, height: 7, borderRadius: 999, background: STATE_COLOR[state], flexShrink: 0 }}
        />
        <span style={{ fontFamily: fonts.mono, fontSize: 10.5, letterSpacing: "0.1em", color: colors.textDim }}>{label}</span>
      </div>
      <div style={{ fontFamily: fonts.mono, fontSize: 22, fontWeight: 700, color: colors.text, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {metric}
      </div>
      <div style={{ fontFamily: fonts.sans, fontSize: 11, color: colors.textFaint }}>{sub}</div>
    </div>
  );
}

function FlowChannel() {
  const flowMarks = useEventStore((s) => s.flowMarks);
  const pruneFlowMark = useEventStore((s) => s.pruneFlowMark);
  const reduced = prefersReducedMotion();
  // Only render marks whose from/to are adjacent real stages, mapped onto
  // this one shared 3-gap channel (matches the brief's single strip).
  const visible = flowMarks.slice(-40);

  if (reduced) return <div style={{ height: 3, background: colors.panelBorder, margin: "0 8px" }} />;

  return (
    <div style={{ position: "relative", height: 22, margin: "0 8px" }}>
      <div style={{ position: "absolute", left: 0, right: 0, top: "50%", height: 1, background: colors.panelBorder }} />
      <AnimatePresence>
        {visible.map((mark) => (
          <FlowDot key={mark.id} kind={mark.kind} onDone={() => pruneFlowMark(mark.id)} />
        ))}
      </AnimatePresence>
    </div>
  );
}

const KIND_COLOR: Record<string, string> = {
  "runner.price": colors.textDim,
  "strategy.signal": colors.ours,
  "order.placed": colors.ours,
  "order.matched": colors.pos,
  "order.cancelled": colors.textFaint,
  "order.lapsed": colors.textFaint,
  "pnl.update": colors.pos,
};

function FlowDot({ kind, onDone }: { kind: string; onDone: () => void }) {
  const color = KIND_COLOR[kind] ?? colors.textDim;
  return (
    <motion.span
      initial={{ left: "0%", opacity: 0 }}
      animate={{ left: "100%", opacity: [0, 1, 1, 0] }}
      transition={{ duration: 0.9, ease: "linear" }}
      onAnimationComplete={onDone}
      style={{
        position: "absolute",
        top: "50%",
        width: 6,
        height: 6,
        borderRadius: 999,
        background: color,
        transform: "translate(-50%, -50%)",
        boxShadow: `0 0 6px ${color}`,
      }}
    />
  );
}

export function PipelineScreen() {
  const now = useNow(1000);
  const recentTickTs = useEventStore((s) => s.recentTickTs);
  const recentSignalTs = useEventStore((s) => s.recentSignalTs);
  const ordersByRunner = useEventStore((s) => s.ordersByRunner);
  const pnl = useEventStore((s) => s.pnl);
  const markets = useEventStore((s) => s.markets);
  const closedMarkets = useEventStore((s) => s.closedMarkets);

  const ticksPerSec = (recentTickTs.filter((t) => t > now - 15_000).length / 15).toFixed(1);
  const signalsPerMin = recentSignalTs.filter((t) => t > now - 60_000).length;

  let openOrders = 0;
  for (const byId of Object.values(ordersByRunner)) {
    for (const o of Object.values(byId)) {
      if (o.type === "order.cancelled" || o.type === "order.lapsed") continue;
      if (o.matched_size < o.size) openOrders++;
    }
  }

  const openMarkets = Object.values(markets).filter((m) => !closedMarkets[m.market_id]).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", padding: "4px 16px 12px", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "stretch" }}>
        <StageCard stage="stream" metric={`${ticksPerSec}/s`} sub={`${openMarkets} market${openMarkets === 1 ? "" : "s"} live`} />
        <FlowChannel />
        <StageCard stage="strategy" metric={String(signalsPerMin)} sub="signals / min" />
        <FlowChannel />
        <StageCard stage="executor" metric={String(openOrders)} sub={openOrders === 1 ? "order working" : "orders working"} />
        <FlowChannel />
        <StageCard stage="book" metric={money(pnl?.run_pnl ?? 0)} sub={pnl ? `${pnl.fill_model}` : "no fills yet"} />
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        <StoryFeed />
      </div>
    </div>
  );
}
