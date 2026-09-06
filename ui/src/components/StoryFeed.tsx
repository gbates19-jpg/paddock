// The narrative timeline: every signal, order, fill, cancel and P&L
// change as a sentence, newest first. Direct answer to "what just
// happened" — the Book HUD shows only the latest line; this is the log.
import { AnimatePresence, motion } from "framer-motion";
import { useEventStore } from "../store/eventStore";
import type { StoryEntry, StoryTone } from "../lib/story";
import { colors, fonts } from "../theme";

const TONE_COLOR: Record<StoryTone, string> = {
  neutral: colors.textFaint,
  ours: colors.ours,
  good: colors.pos,
  bad: colors.neg,
};

function timeLabel(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString(undefined, { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function Row({ entry }: { entry: StoryEntry }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18 }}
      style={{
        display: "flex",
        gap: 10,
        padding: "6px 4px",
        borderBottom: `1px solid ${colors.panelBorder}`,
        alignItems: "baseline",
      }}
    >
      <span style={{ fontFamily: fonts.mono, fontSize: 10.5, color: colors.textFaint, flexShrink: 0, width: 62 }}>{timeLabel(entry.ts)}</span>
      <span style={{ width: 6, height: 6, borderRadius: 999, background: TONE_COLOR[entry.tone], flexShrink: 0, alignSelf: "center" }} />
      <span style={{ fontFamily: fonts.sans, fontSize: 12.5, fontWeight: 600, color: colors.text, flexShrink: 0 }}>{entry.headline}</span>
      <span style={{ fontFamily: fonts.sans, fontSize: 12.5, color: colors.textDim, minWidth: 0 }}>{entry.detail}</span>
    </motion.div>
  );
}

export function StoryFeed({ limit = 60 }: { limit?: number }) {
  const story = useEventStore((s) => s.story).slice(0, limit);

  return (
    <div
      style={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        background: colors.panel,
        border: `1px solid ${colors.panelBorder}`,
        borderRadius: 12,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "8px 12px",
          fontFamily: fonts.mono,
          fontSize: 10.5,
          letterSpacing: "0.1em",
          color: colors.textDim,
          borderBottom: `1px solid ${colors.panelBorder}`,
          flexShrink: 0,
        }}
      >
        STORY
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "2px 10px" }}>
        {story.length === 0 && (
          <div style={{ padding: "16px 4px", fontFamily: fonts.sans, fontSize: 12.5, color: colors.textFaint }}>nothing has happened yet</div>
        )}
        <AnimatePresence initial={false}>
          {story.map((entry) => (
            <Row key={entry.id} entry={entry} />
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}
