// THE BOOK — the ONE persistent HUD. Everything about the run that must
// stay visible whatever scene is open lives here and nowhere else: mode,
// connection, P&L + sparkline, commission, speed, latency, alerts. The
// header used to carry its own connection/mode badges as well, which meant
// two places telling you (slightly different) versions of the same thing;
// the header is now just scene tabs.
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import { apiHttpUrl, isDemoMode } from "../lib/connection";
import { useEventStore } from "../store/eventStore";
import type { OrderRejected, PositionUnhedged } from "../lib/events";
import { colors, colorsCss, fonts, isMobile } from "../theme";

const STATUS_LABEL: Record<string, string> = {
  connecting: "CONNECTING",
  connected: "LIVE FEED",
  disconnected: "DISCONNECTED",
  demo: "DEMO",
};

const STATUS_COLOR: Record<string, string> = {
  connecting: colorsCss.signal,
  connected: colorsCss.pnlPos,
  disconnected: colorsCss.rejected,
  demo: colorsCss.price,
};

const SPEED_PRESETS: { label: string; value: number }[] = [
  { label: "1x", value: 1 },
  { label: "5x", value: 5 },
  { label: "20x", value: 20 },
  { label: "max", value: 0 }, // engine convention: speed 0 = as fast as possible
];

const label = (text: string) => (
  <span style={{ fontFamily: fonts.mono, fontSize: 10, letterSpacing: "0.08em", color: colors.textDim }}>{text}</span>
);

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
  const stroke = positive ? colorsCss.pnlPos : colorsCss.pnlNeg;
  return (
    <svg width={w} height={h}>
      <defs>
        <linearGradient id="book-spark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={stroke} stopOpacity={0.25} />
          <stop offset="1" stopColor={stroke} stopOpacity={0} />
        </linearGradient>
      </defs>
      <polygon points={`0,${h} ${points} ${w},${h}`} fill="url(#book-spark-fill)" />
      <line x1={0} y1={zeroY} x2={w} y2={zeroY} stroke={colors.textFaint} strokeWidth={1} strokeDasharray="2,3" />
      <polyline points={points} fill="none" stroke={stroke} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// Mode badge: REPLAY / PAPER lit, LIVE always present but greyed — the
// point is that you can SEE live is a thing this build refuses to do.
function ModeBadge() {
  const runConfig = useEventStore((s) => s.runConfig);
  const mode = runConfig?.mode ?? "replay";
  const isOptimistic = runConfig?.fill_model === "ltp_cross";
  const modes = ["replay", "paper", "live"] as const;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <div style={{ display: "flex", gap: 2, borderRadius: 6, overflow: "hidden", border: `1px solid ${colors.panelBorder}` }}>
        {modes.map((m) => {
          const active = m === mode;
          const isLive = m === "live";
          return (
            <span
              key={m}
              title={isLive ? "LIVE is hard-disabled in this build (Phase 0). See docs/phase1.md." : undefined}
              style={{
                fontFamily: fonts.mono,
                fontSize: 10,
                letterSpacing: "0.1em",
                padding: "3px 7px",
                color: active ? colors.bgHex : isLive ? colors.textFaint : colors.textDim,
                background: active ? colorsCss.price : "transparent",
                textDecoration: isLive ? "line-through" : "none",
                cursor: isLive ? "not-allowed" : "default",
              }}
            >
              {m.toUpperCase()}
            </span>
          );
        })}
      </div>
      {runConfig && (
        <span
          title={
            isOptimistic
              ? "ltp_cross is an optimistic approximation for Basic Plan data — P&L is an upper bound, not a backtest result."
              : undefined
          }
          style={{
            fontFamily: fonts.mono,
            fontSize: 10,
            color: isOptimistic ? colorsCss.optimistic : colors.textDim,
            whiteSpace: "nowrap",
          }}
        >
          {runConfig.fill_model}
          {isOptimistic ? " · optimistic" : ""}
        </span>
      )}
    </div>
  );
}

function ConnectionDot() {
  const connection = useEventStore((s) => s.connection);
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={connection}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: 0.2 }}
        style={{
          fontFamily: fonts.mono,
          fontSize: 11,
          letterSpacing: "0.08em",
          color: STATUS_COLOR[connection],
          whiteSpace: "nowrap",
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: 999,
            background: STATUS_COLOR[connection],
            boxShadow: `0 0 8px ${STATUS_COLOR[connection]}`,
            animation: connection === "connecting" ? "book-blink 1s infinite" : undefined,
          }}
        />
        {STATUS_LABEL[connection]}
      </motion.div>
    </AnimatePresence>
  );
}

// Latency gauge: worst recent latency across workers, drawn as a short
// bar so a spike reads as a shape before you read the number.
function LatencyGauge() {
  const workers = useEventStore((s) => s.workers);
  const worst = useMemo(() => {
    let max: number | null = null;
    for (const w of Object.values(workers)) {
      if (w.last_latency_ms != null && (max == null || w.last_latency_ms > max)) max = w.last_latency_ms;
    }
    return max;
  }, [workers]);

  const frac = worst == null ? 0 : Math.min(1, worst / 500);
  const color = worst == null ? colors.textFaint : worst < 150 ? colorsCss.pnlPos : worst < 400 ? colorsCss.signal : colorsCss.rejected;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }} title="worst last_latency_ms across engine workers">
      {label("LATENCY")}
      <div style={{ width: 56, height: 6, borderRadius: 3, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
        <motion.div animate={{ width: `${frac * 100}%` }} transition={{ duration: 0.3 }} style={{ height: "100%", background: color }} />
      </div>
      <span style={{ fontFamily: fonts.mono, fontSize: 12, color: colors.text, minWidth: 44 }}>
        {worst == null ? "—" : `${worst.toFixed(0)}ms`}
      </span>
    </div>
  );
}

function SpeedControl() {
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
      // best-effort — a dropped request just means the next click retries
    } finally {
      setPending(false);
    }
  }

  const title = disabled ? "speed control needs a live engine connection (not available in ?demo=1)" : undefined;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, opacity: pending ? 0.6 : 1 }} title={title}>
      {label("SPEED")}
      <div style={{ display: "flex", gap: 2 }}>
        {SPEED_PRESETS.map((p) => {
          const active = value === p.value;
          return (
            <button
              key={p.label}
              disabled={disabled}
              onClick={() => commit(p.value)}
              style={{
                fontFamily: fonts.mono,
                fontSize: 11,
                padding: "3px 7px",
                borderRadius: 5,
                cursor: disabled ? "not-allowed" : "pointer",
                background: active ? "rgba(79, 209, 255, 0.18)" : "transparent",
                border: `1px solid ${active ? colorsCss.price : "rgba(255,255,255,0.1)"}`,
                color: active ? colorsCss.price : colors.textDim,
              }}
            >
              {p.label}
            </button>
          );
        })}
      </div>
      {/* Free entry as well as presets: Pro-plan replays need ~5000x to be
          watchable (16k updates/market), which no sane preset list covers. */}
      <input
        type="number"
        min={0}
        step={1}
        value={value}
        disabled={disabled}
        onChange={(e) => setValue(Number(e.target.value))}
        onBlur={(e) => commit(Math.max(0, Number(e.target.value) || 0))}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        }}
        title="custom speed (market-seconds per real-second; 0 = max)"
        style={{
          width: 58,
          fontFamily: fonts.mono,
          fontSize: 11,
          padding: "2px 4px",
          borderRadius: 5,
          background: "rgba(255,255,255,0.04)",
          border: "1px solid rgba(255,255,255,0.1)",
          color: colors.text,
        }}
      />
    </div>
  );
}

function AlertFeed() {
  const log = useEventStore((s) => s.log);
  const alerts = useMemo(
    () =>
      log
        .filter((e): e is OrderRejected | PositionUnhedged => e.type === "order.rejected" || e.type === "position.unhedged")
        .slice(0, 3),
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

function Divider() {
  return <div style={{ width: 1, alignSelf: "stretch", background: colors.panelBorder }} />;
}

export function BookScene() {
  const pnl = useEventStore((s) => s.pnl);
  const runConfig = useEventStore((s) => s.runConfig);
  const log = useEventStore((s) => s.log);
  const ordersByRunner = useEventStore((s) => s.ordersByRunner);
  const mobile = isMobile();

  const pnlHistory = useMemo(() => {
    const points: number[] = [];
    for (let i = log.length - 1; i >= 0; i--) {
      const e = log[i];
      if (e.type === "pnl.update") points.push(e.run_pnl);
    }
    return points.slice(-40);
  }, [log]);

  const { matched, unmatched } = useMemo(() => {
    let m = 0;
    let u = 0;
    for (const byId of Object.values(ordersByRunner)) {
      for (const o of Object.values(byId)) {
        if (o.type === "order.cancelled" || o.type === "order.lapsed") continue;
        if (o.matched_size >= o.size) m++;
        else u++;
      }
    }
    return { matched: m, unmatched: u };
  }, [ordersByRunner]);

  const runPnl = pnl?.run_pnl ?? 0;
  const positive = runPnl >= 0;

  return (
    <div
      style={{
        flexShrink: 0,
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        rowGap: 8,
        columnGap: mobile ? 12 : 18,
        padding: mobile ? "8px 12px" : "10px 20px",
        background: colors.panel,
        borderTop: `1px solid ${colors.panelBorder}`,
        backdropFilter: "blur(10px)",
        position: "relative",
        zIndex: 10,
      }}
    >
      <ModeBadge />
      <ConnectionDot />
      {!mobile && <Divider />}

      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        {label("RUN P&L")}
        <motion.span
          key={positive ? "pos" : "neg"}
          initial={{ scale: 0.9 }}
          animate={{ scale: 1 }}
          style={{
            fontFamily: fonts.mono,
            fontSize: 20,
            fontWeight: 700,
            color: positive ? colorsCss.pnlPos : colorsCss.pnlNeg,
            textShadow: `0 0 12px ${positive ? "rgba(53,224,122,0.35)" : "rgba(255,77,109,0.35)"}`,
          }}
        >
          {positive ? "+" : ""}
          {runPnl.toFixed(2)}
        </motion.span>
      </div>

      <Sparkline values={pnlHistory} positive={positive} />

      <div style={{ display: "flex", alignItems: "baseline", gap: 6 }} title="orders matched / unmatched (excl. cancelled)">
        <span style={{ fontFamily: fonts.mono, fontSize: 12, color: colorsCss.matched }}>{matched}</span>
        <span style={{ fontFamily: fonts.mono, fontSize: 10, color: colors.textFaint }}>/</span>
        <span style={{ fontFamily: fonts.mono, fontSize: 12, color: colors.textDim }}>{unmatched}</span>
        {label("MATCHED")}
      </div>

      {runConfig && (
        <span style={{ fontFamily: fonts.mono, fontSize: 11, color: colors.textDim, whiteSpace: "nowrap" }}>
          comm {(runConfig.commission_rate * 100).toFixed(0)}%
        </span>
      )}

      {!mobile && <Divider />}
      <SpeedControl />
      {!mobile && <LatencyGauge />}

      <div style={{ marginLeft: mobile ? 0 : "auto" }}>
        <AlertFeed />
      </div>
    </div>
  );
}
