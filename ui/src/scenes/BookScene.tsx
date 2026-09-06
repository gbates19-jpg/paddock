// THE BOOK — a persistent bottom HUD, not a tab: the run's vitals (P&L,
// mode, speed, alerts) should be visible no matter which scene is open,
// the way a poker table's stack count never disappears when you look at
// the board.
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import { apiHttpUrl, isDemoMode } from "../lib/connection";
import { useEventStore } from "../store/eventStore";
import type { OrderRejected, PositionUnhedged } from "../lib/events";
import { colors, colorsCss, fonts, isMobile } from "../theme";

function Sparkline({ values, positive }: { values: number[]; positive: boolean }) {
  const w = 120;
  const h = 32;
  if (values.length < 2) {
    return <svg width={w} height={h} />;
  }
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const range = max - min || 1;
  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - ((v - min) / range) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const zeroY = h - ((0 - min) / range) * h;
  return (
    <svg width={w} height={h}>
      <line x1={0} y1={zeroY} x2={w} y2={zeroY} stroke={colors.textFaint} strokeWidth={1} strokeDasharray="2,3" />
      <polyline
        points={points}
        fill="none"
        stroke={positive ? colorsCss.pnlPos : colorsCss.pnlNeg}
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

function SpeedSlider() {
  const runConfig = useEventStore((s) => s.runConfig);
  const [value, setValue] = useState(20);
  const [pending, setPending] = useState(false);
  const disabled = isDemoMode() || !runConfig;

  useEffect(() => {
    if (runConfig) setValue(runConfig.speed);
  }, [runConfig?.run_id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function commit(next: number) {
    setValue(next);
    if (disabled) return;
    setPending(true);
    try {
      await fetch(apiHttpUrl("/sim/speed"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ speed: next, run_id: runConfig?.run_id }),
      });
    } catch {
      // best-effort — a dropped request just means the next drag retries
    } finally {
      setPending(false);
    }
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span style={{ fontFamily: fonts.mono, fontSize: 11, color: colors.textDim }}>SPEED</span>
      <input
        type="range"
        min={1}
        max={200}
        step={1}
        value={value}
        disabled={disabled}
        onChange={(e) => commit(Number(e.target.value))}
        style={{ width: 90, accentColor: colorsCss.price }}
        title={disabled ? "speed control needs a live engine connection (not available in ?demo=1)" : undefined}
      />
      <span style={{ fontFamily: fonts.mono, fontSize: 12, color: colors.text, minWidth: 34, opacity: pending ? 0.5 : 1 }}>
        {value.toFixed(0)}x
      </span>
    </div>
  );
}

function AlertFeed() {
  const log = useEventStore((s) => s.log);
  const alerts = useMemo(
    () =>
      log
        .filter((e): e is OrderRejected | PositionUnhedged => e.type === "order.rejected" || e.type === "position.unhedged")
        .slice(0, 4),
    [log]
  );

  if (alerts.length === 0) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, maxWidth: 260 }}>
      <AnimatePresence initial={false}>
        {alerts.map((a) => (
          <motion.div
            key={a.event_id}
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0 }}
            style={{
              fontFamily: fonts.mono,
              fontSize: 11,
              color: colorsCss.rejected,
              background: "rgba(255, 77, 109, 0.1)",
              border: "1px solid rgba(255, 77, 109, 0.3)",
              borderRadius: 6,
              padding: "3px 8px",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
            title={a.reason}
          >
            {a.type === "order.rejected" ? "REJECTED" : "UNHEDGED"} #{a.selection_id} — {a.reason}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

export function BookScene() {
  const pnl = useEventStore((s) => s.pnl);
  const runConfig = useEventStore((s) => s.runConfig);
  const log = useEventStore((s) => s.log);
  const mobile = isMobile();

  const pnlHistory = useMemo(() => {
    const points: number[] = [];
    for (let i = log.length - 1; i >= 0; i--) {
      const e = log[i];
      if (e.type === "pnl.update") points.push(e.run_pnl);
    }
    return points.slice(-40);
  }, [log]);

  const runPnl = pnl?.run_pnl ?? 0;
  const positive = runPnl >= 0;

  return (
    <div
      style={{
        flexShrink: 0,
        display: "flex",
        flexWrap: mobile ? "wrap" : "nowrap",
        alignItems: "center",
        gap: mobile ? 12 : 24,
        padding: mobile ? "10px 12px" : "10px 20px",
        background: colors.panel,
        borderTop: `1px solid ${colors.panelBorder}`,
        backdropFilter: "blur(8px)",
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontFamily: fonts.mono, fontSize: 11, color: colors.textDim }}>RUN P&L</span>
        <span
          style={{
            fontFamily: fonts.mono,
            fontSize: 20,
            fontWeight: 700,
            color: positive ? colorsCss.pnlPos : colorsCss.pnlNeg,
          }}
        >
          {positive ? "+" : ""}
          {runPnl.toFixed(2)}
        </span>
      </div>

      <Sparkline values={pnlHistory} positive={positive} />

      {runConfig && (
        <div style={{ fontFamily: fonts.mono, fontSize: 11, color: colors.textDim, whiteSpace: "nowrap" }}>
          commission {(runConfig.commission_rate * 100).toFixed(0)}%
        </div>
      )}

      <SpeedSlider />

      <div style={{ marginLeft: mobile ? 0 : "auto" }}>
        <AlertFeed />
      </div>
    </div>
  );
}
