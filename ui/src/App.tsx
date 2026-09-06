import { AnimatePresence, motion } from "framer-motion";
import type { CSSProperties } from "react";
import { useEffect, useState } from "react";
import { startConnection } from "./lib/connection";
import { BookScene } from "./scenes/BookScene";
import { FloorScene } from "./scenes/FloorScene";
import { LadderScene } from "./scenes/LadderScene";
import { PaddockScene } from "./scenes/PaddockScene";
import type { Scene } from "./store/eventStore";
import { useEventStore } from "./store/eventStore";
import { colors, colorsCss, fonts } from "./theme";

const STATUS_LABEL: Record<string, string> = {
  connecting: "CONNECTING",
  connected: "LIVE",
  disconnected: "DISCONNECTED",
  demo: "DEMO",
};

const STATUS_COLOR: Record<string, string> = {
  connecting: colorsCss.signal,
  connected: colorsCss.pnlPos,
  disconnected: colorsCss.rejected,
  demo: colorsCss.price,
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
  background: colors.panel,
  border: `1px solid ${colors.panelBorder}`,
  backdropFilter: "blur(8px)",
  fontSize: 12,
  letterSpacing: "0.08em",
  fontFamily: fonts.mono,
  whiteSpace: "nowrap",
};

function useIsNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => window.innerWidth < 640);
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 640);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return narrow;
}

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
        color: isOptimistic ? colorsCss.optimistic : colors.textDim,
      }}
    >
      {label}
    </motion.div>
  );
}

function SceneTabs({ narrow }: { narrow: boolean }) {
  const scene = useEventStore((s) => s.scene);
  const setScene = useEventStore((s) => s.setScene);
  const scenes: Scene[] = ["floor", "paddock", "ladder"];

  return (
    <div
      style={{
        display: "flex",
        gap: 4,
        fontFamily: fonts.mono,
        fontSize: narrow ? 11 : 12,
        letterSpacing: "0.06em",
      }}
    >
      {scenes.map((s) => (
        <button
          key={s}
          onClick={() => setScene(s)}
          style={{
            background: s === scene ? "rgba(79, 209, 255, 0.15)" : "transparent",
            border: `1px solid ${s === scene ? colorsCss.price : "rgba(255,255,255,0.1)"}`,
            color: s === scene ? colorsCss.price : colors.textDim,
            borderRadius: 6,
            padding: narrow ? "5px 7px" : "5px 10px",
            cursor: "pointer",
          }}
        >
          {narrow ? SCENE_LABEL[s].replace("THE ", "") : SCENE_LABEL[s]}
        </button>
      ))}
    </div>
  );
}

function Header({ narrow }: { narrow: boolean }) {
  return (
    <div
      style={{
        position: "relative",
        zIndex: 10,
        flexShrink: 0,
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        padding: narrow ? 10 : 16,
        gap: 12,
      }}
    >
      <SceneTabs narrow={narrow} />
      <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-end" }}>
        <ConnectionBadge />
        {!narrow && <ModeBadge />}
      </div>
    </div>
  );
}

export default function App() {
  useEffect(() => startConnection(), []);
  const scene = useEventStore((s) => s.scene);
  const narrow = useIsNarrow();

  return (
    <div
      style={{
        width: "100vw",
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        background: colors.bgHex,
      }}
    >
      <Header narrow={narrow} />
      <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
        {scene === "floor" && <FloorScene />}
        {scene === "paddock" && <PaddockScene />}
        {scene === "ladder" && <LadderScene />}
      </div>
      <BookScene />
    </div>
  );
}
