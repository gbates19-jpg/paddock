// Single source of truth for colour/spacing/type across all scenes — one
// accent per event family, used consistently everywhere rather than each
// scene picking its own palette.
export const colors = {
  bg: 0x05070d,
  bgHex: "#05070d",
  panel: "rgba(20, 26, 41, 0.72)",
  panelBorder: "rgba(255,255,255,0.08)",
  grid: 0x1b2333,
  text: "#e4e8f0",
  textDim: "#7c8496",
  textFaint: "#4a5468",

  // event-family accents (bus event `type` prefix -> colour), used by
  // Floor's particles/rings, Paddock's pulses, Ladder's chips, Book's log
  price: 0x4fd1ff, // runner.price
  signal: 0xffb84f, // strategy.signal
  placed: 0x8affc1, // order.placed
  matched: 0x35e07a, // order.matched
  cancelled: 0x8a93a6, // order.cancelled / lapsed
  rejected: 0xff4d6d, // order.rejected / position.unhedged
  pnlPos: 0x35e07a,
  pnlNeg: 0xff4d6d,
  optimistic: 0xffb84f, // ltp_cross badge

  back: 0x4fd1ff,
  lay: 0xff8a5c,

  idle: 0x3a4a63,
  busy: 0x4fd1ff,
  error: 0xff4d6d,
} as const;

export const colorsCss = {
  price: "#4fd1ff",
  signal: "#ffb84f",
  placed: "#8affc1",
  matched: "#35e07a",
  cancelled: "#8a93a6",
  rejected: "#ff4d6d",
  pnlPos: "#35e07a",
  pnlNeg: "#ff4d6d",
  optimistic: "#ffb84f",
  back: "#4fd1ff",
  lay: "#ff8a5c",
} as const;

export const eventColor = (eventType: string): number => {
  if (eventType.startsWith("runner.price")) return colors.price;
  if (eventType.startsWith("strategy.")) return colors.signal;
  if (eventType === "order.placed") return colors.placed;
  if (eventType === "order.matched") return colors.matched;
  if (eventType === "order.cancelled" || eventType === "order.lapsed") return colors.cancelled;
  if (eventType === "order.rejected" || eventType === "position.unhedged") return colors.rejected;
  if (eventType.startsWith("pnl.")) return colors.pnlPos;
  return colors.textDim as unknown as number;
};

export const spacing = { xs: 4, sm: 8, md: 16, lg: 24, xl: 32 };

export const fonts = {
  mono: "ui-monospace, SFMono-Regular, Menlo, monospace",
  sans: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif",
};

export const isMobile = () => typeof window !== "undefined" && window.innerWidth < 640;

export const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
