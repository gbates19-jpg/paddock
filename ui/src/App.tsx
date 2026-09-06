import { AnimatePresence, motion } from "framer-motion";
import type { CSSProperties } from "react";
import { useEffect } from "react";
import { startConnection } from "./lib/connection";
import { FloorScene } from "./scenes/FloorScene";
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

const badgeStyle: CSSProperties = {
  position: "absolute",
  right: 16,
  padding: "6px 12px",
  borderRadius: 999,
  background: "rgba(20, 26, 41, 0.72)",
  border: "1px solid rgba(255,255,255,0.08)",
  backdropFilter: "blur(8px)",
  fontSize: 12,
  letterSpacing: "0.08em",
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
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
        style={{ ...badgeStyle, top: 16, color: STATUS_COLOR[connection] }}
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
        top: 52,
        color: isOptimistic ? "#ffb84f" : "#7c8496",
      }}
    >
      {label}
    </motion.div>
  );
}

export default function App() {
  useEffect(() => startConnection(), []);

  return (
    <div style={{ position: "relative", width: "100vw", height: "100vh" }}>
      <div
        style={{
          position: "absolute",
          top: 16,
          left: 16,
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          fontSize: 13,
          color: "#7c8496",
          letterSpacing: "0.08em",
        }}
      >
        PADDOCK — THE FLOOR
      </div>
      <ConnectionBadge />
      <ModeBadge />
      <FloorScene />
    </div>
  );
}
