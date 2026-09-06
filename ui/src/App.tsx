import { AnimatePresence, motion } from "framer-motion";
import type { CSSProperties } from "react";
import { useEffect } from "react";
import { startConnection } from "./lib/connection";
import { FloorScene } from "./scenes/FloorScene";
import { LadderScene } from "./scenes/LadderScene";
import { PaddockScene } from "./scenes/PaddockScene";
import type { Scene } from "./store/eventStore";
import { useEventStore } from "./store/eventStore";

const STATUS_LABEL: Record<string, string> = {
  connecting: "CONNECTING",
  connected: "LIVE",
  disconnected: "DISCONNECTED",
  demo: "DEMO",
};

const STATUS_COLOR: Record<string, string> = {
  connecting: "#ffb84f",
  connected: "#35e07a",
  disconnected: "#ff4d6d",
  demo: "#4fd1ff",
};

const SCENE_LABEL: Record<Scene, string> = {
  floor: "THE FLOOR",
  paddock: "THE PADDOCK",
  ladder: "THE LADDER",
};

// Note: NOT position:absolute-relative-to-viewport — that was a real bug.
// Scenes (Paddock, Ladder) have their own content starting at the top of
// their container, and either painted over these badges (Paddock's root
// div is position:relative, which — per CSS stacking rules — promotes it
// into the same "positioned, z-index:auto" bucket as these badges, and
// being later in the DOM it then paints on top of them) or visually
// collided with them (Ladder's own header row, with no reserved
// clearance). Found both via the very first real screenshots this UI
// ever got (scripts/snap.mjs) — never caught without actually rendering
// it. Fixed by making the header a real flex row that scenes render
// below, not a floating overlay on top of whatever a scene draws.
const badgeStyle: CSSProperties = {
  padding: "6px 12px",
  borderRadius: 999,
  background: "rgba(20, 26, 41, 0.72)",
  border: "1px solid rgba(255,255,255,0.08)",
  backdropFilter: "blur(8px)",
  fontSize: 12,
  letterSpacing: "0.08em",
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  whiteSpace: "nowrap",
};

function ConnectionBadge() {
  const connection = useEventStore((s) => s.connection);
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={connection}
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -6 }}
        transition={{ duration: 0.2 }}
        style={{ ...badgeStyle, color: STATUS_COLOR[connection] }}
      >
        ● {STATUS_LABEL[connection]}
      </motion.div>
    </AnimatePresence>
  );
}

function ModeBadge() {
  const runConfig = useEventStore((s) => s.runConfig);
  if (!runConfig) return null;

  const isOptimistic = runConfig.fill_model === "ltp_cross";
  const label = isOptimistic
    ? `${runConfig.mode.toUpperCase()} · ${runConfig.fill_model} (optimistic)`
    : `${runConfig.mode.toUpperCase()} · ${runConfig.fill_model}`;

  return (
    <motion.div
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      title={
        isOptimistic
          ? "ltp_cross is an optimistic approximation for Basic Plan data — P&L is an upper bound, not a backtest result."
          : undefined
      }
      style={{
        ...badgeStyle,
        color: isOptimistic ? "#ffb84f" : "#7c8496",
      }}
    >
      {label}
    </motion.div>
  );
}

function SceneTabs() {
  const scene = useEventStore((s) => s.scene);
  const setScene = useEventStore((s) => s.setScene);
  const scenes: Scene[] = ["floor", "paddock", "ladder"];

  return (
    <div
      style={{
        display: "flex",
        gap: 4,
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        fontSize: 12,
        letterSpacing: "0.06em",
      }}
    >
      {scenes.map((s) => (
        <button
          key={s}
          onClick={() => setScene(s)}
          style={{
            background: s === scene ? "rgba(79, 209, 255, 0.15)" : "transparent",
            border: `1px solid ${s === scene ? "#4fd1ff" : "rgba(255,255,255,0.1)"}`,
            color: s === scene ? "#4fd1ff" : "#7c8496",
            borderRadius: 6,
            padding: "5px 10px",
            cursor: "pointer",
          }}
        >
          {SCENE_LABEL[s]}
        </button>
      ))}
    </div>
  );
}

function Header() {
  return (
    <div
      style={{
        position: "relative",
        zIndex: 10,
        flexShrink: 0,
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        padding: 16,
        gap: 12,
      }}
    >
      <SceneTabs />
      <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-end" }}>
        <ConnectionBadge />
        <ModeBadge />
      </div>
    </div>
  );
}

export default function App() {
  useEffect(() => startConnection(), []);
  const scene = useEventStore((s) => s.scene);

  return (
    <div
      style={{
        width: "100vw",
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        background: "#05070d",
      }}
    >
      <Header />
      <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
        {scene === "floor" && <FloorScene />}
        {scene === "paddock" && <PaddockScene />}
        {scene === "ladder" && <LadderScene />}
      </div>
    </div>
  );
}
