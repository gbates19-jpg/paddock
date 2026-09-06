// THE BOOK — the one persistent HUD, visible under every screen. Leads
// with the hero P&L and a plain-English "what just happened" line, backed
// by mode/connection/speed/latency controls. This is the fix for "what's
// going on right now" at a glance, without opening the Story feed.
import { useState } from "react";
import { apiHttpUrl, isDemoMode } from "../lib/connection";
import { useFlash } from "../lib/hooks";
import { useEventStore } from "../store/eventStore";
import { colors, fonts, isMobile, moneyColor } from "../theme";
import { money } from "../lib/position";

const SPEED_PRESETS = [
  { label: "1x", value: 1 },
  { label: "5x", value: 5 },
  { label: "20x", value: 20 },
  { label: "max", value: 0 },
];

function Sparkline({ values, color }: { values: number[]; color: string }) {
  const w = 100;
  const h = 28;
  if (values.length < 2) return <svg width={w} height={h} />;
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const range = max - min || 1;
  const pts = values.map((v, i) => `${((i / (values.length - 1)) * w).toFixed(1)},${(h - ((v - min) / range) * h).toFixed(1)}`).join(" ");
  const zeroY = h - ((0 - min) / range) * h;
  return (
    <svg width={w} height={h}>
      <line x1={0} y1={zeroY} x2={w} y2={zeroY} stroke={colors.textFaint} strokeWidth={1} strokeDasharray="2,3" />
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function ModePill() {
  const runConfig = useEventStore((s) => s.runConfig);
  const connection = useEventStore((s) => s.connection);
  const mode = (runConfig?.mode ?? "replay").toUpperCase();
  const connColor = connection === "connected" || connection === "demo" ? colors.live : connection === "connecting" ? colors.warn : colors.neg;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: 999,
          background: connColor,
          flexShrink: 0,
        }}
        className={connection === "connecting" ? "blink" : undefined}
      />
      <span style={{ fontFamily: fonts.mono, fontSize: 11, fontWeight: 500, letterSpacing: "0.06em", color: colors.textDim }}>
        {mode}
        {runConfig?.fill_model === "ltp_cross" && <span style={{ color: colors.warn }}> · OPTIMISTIC</span>}
      </span>
    </div>
  );
}

function LastAction() {
  const entry = useEventStore((s) => s.story[0]);
  const flash = useFlash(entry?.id, 900);
  if (!entry) {
    return <div style={{ fontFamily: fonts.sans, fontSize: 12.5, color: colors.textFaint }}>watching for the first signal…</div>;
  }
  const dotColor = entry.tone === "good" ? colors.pos : entry.tone === "bad" ? colors.neg : entry.tone === "ours" ? colors.ours : colors.textFaint;
  return (
    <div
      className={flash ? (entry.tone === "good" ? "flash-good" : entry.tone === "bad" ? "flash-bad" : entry.tone === "ours" ? "flash-ours" : undefined) : undefined}
      style={{ display: "flex", alignItems: "baseline", gap: 7, borderRadius: 6, padding: "1px 4px", margin: "-1px -4px" }}
    >
      <span style={{ width: 6, height: 6, borderRadius: 999, background: dotColor, flexShrink: 0, alignSelf: "center" }} />
      <span style={{ fontFamily: fonts.sans, fontSize: 12.5, color: colors.text, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {entry.detail}
      </span>
    </div>
  );
}

function SpeedControl() {
  const runConfig = useEventStore((s) => s.runConfig);
  const [value, setValue] = useState(20);
  const disabled = isDemoMode() || !runConfig;

  async function commit(next: number) {
    setValue(next);
    if (disabled) return;
    try {
      await fetch(apiHttpUrl("/sim/speed"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ speed: next, run_id: runConfig?.run_id }),
      });
    } catch {
      // best-effort
    }
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4 }} title={disabled ? "speed needs a live engine connection" : "replay speed"}>
      {SPEED_PRESETS.map((p) => (
        <button
          key={p.label}
          disabled={disabled}
          onClick={() => commit(p.value)}
          style={{
            fontFamily: fonts.mono,
            fontSize: 10.5,
            padding: "3px 6px",
            borderRadius: 5,
            border: "none",
            cursor: disabled ? "default" : "pointer",
            background: value === p.value ? colors.panel2 : "transparent",
            color: value === p.value ? colors.text : colors.textFaint,
          }}
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}

export function BookHud() {
  const pnl = useEventStore((s) => s.pnl);
  const pnlHistory = useEventStore((s) => s.pnlHistory);
  const runConfig = useEventStore((s) => s.runConfig);
  const mobile = isMobile();

  const runPnl = pnl?.run_pnl ?? 0;
  const pnlFlash = useFlash(pnl?.event_id, 900);

  return (
    <div
      style={{
        flexShrink: 0,
        borderTop: `1px solid ${colors.panelBorder}`,
        background: colors.panel,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: mobile ? 14 : 20,
          padding: mobile ? "9px 12px" : "10px 18px",
        }}
      >
        <div
          className={pnlFlash ? (runPnl >= 0 ? "flash-good" : "flash-bad") : undefined}
          style={{ display: "flex", alignItems: "baseline", gap: 8, borderRadius: 6, padding: "1px 4px", margin: "-1px -4px" }}
        >
          <span
            style={{
              fontFamily: fonts.mono,
              fontSize: mobile ? 19 : 22,
              fontWeight: 700,
              color: moneyColor(runPnl),
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {money(runPnl)}
          </span>
        </div>
        {!mobile && <Sparkline values={pnlHistory} color={moneyColor(runPnl)} />}
        <div style={{ flex: 1, minWidth: 0 }}>
          <LastAction />
        </div>
        {!mobile && (
          <span style={{ fontFamily: fonts.mono, fontSize: 11, color: colors.textFaint, whiteSpace: "nowrap" }}>
            comm {((runConfig?.commission_rate ?? 0.02) * 100).toFixed(0)}%
          </span>
        )}
        {!mobile && <SpeedControl />}
        <ModePill />
      </div>
    </div>
  );
}
