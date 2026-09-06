import { AnimatePresence, motion } from "framer-motion";
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
        style={{
          position: "absolute",
          top: 16,
          right: 16,
          padding: "6px 12px",
          borderRadius: 999,
          background: "rgba(20, 26, 41, 0.72)",
          border: "1px solid rgba(255,255,255,0.08)",
          backdropFilter: "blur(8px)",
          fontSize: 12,
          letterSpacing: "0.08em",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          color: STATUS_COLOR[connection],
        }}
      >
        ● {STATUS_LABEL[connection]}
      </motion.div>
    </AnimatePresence>
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
      <FloorScene />
    </div>
  );
}
