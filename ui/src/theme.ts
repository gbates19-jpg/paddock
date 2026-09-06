// Single source of truth for colour/spacing/type across every screen.
//
// v2 design language (see project doc paddock-ui-v2-brief.md):
//   - near-black ground, two panel tones for depth, hairline borders —
//     depth from LAYERING, not glow/blur.
//   - ONE accent (amber) means "ours": any order, position, or exposure
//     we hold. Market data on its own is neutral grey/white.
//   - green/red are reserved for MONEY only (P&L, if-win/if-lose) — never
//     used to mean "good state" or "bad state" elsewhere.
//   - back = blue, lay = pink, Betfair's own convention, so the ladder
//     reads without a legend.
export const colors = {
  bg: "#0a0c11",
  bgHex: "#0a0c11",
  panel: "#12151d", // raised one layer
  panel2: "#181c26", // raised two layers (rows, cards within panels)
  panelBorder: "rgba(255,255,255,0.07)",
  panelBorderStrong: "rgba(255,255,255,0.14)",

  text: "#e8eaf0",
  textDim: "#8891a3",
  textFaint: "#525a6b",

  ours: "#f0a93c", // the one accent — anything we own
  oursDim: "rgba(240, 169, 60, 0.14)",

  back: "#3d8bfd",
  backDim: "rgba(61, 139, 253, 0.14)",
  lay: "#ef5da8",
  layDim: "rgba(239, 93, 168, 0.14)",

  pos: "#33c17a", // money up
  neg: "#e2564f", // money down
  posDim: "rgba(51, 193, 122, 0.14)",
  negDim: "rgba(226, 86, 79, 0.14)",

  live: "#33c17a",
  warn: "#e0a530",
  idle: "#525a6b",
} as const;

export const spacing = { xs: 4, sm: 8, md: 16, lg: 24, xl: 32 };

export const fonts = {
  // @fontsource/inter and @fontsource/jetbrains-mono, self-hosted (see
  // index.css imports) — no CDN, so the phone view never blocks on a
  // font request over the tailnet.
  sans: "'Inter', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif",
  mono: "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace",
};

export const radius = { sm: 6, md: 10, lg: 14 };

export const isMobile = () => typeof window !== "undefined" && window.innerWidth < 720;

export const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function moneyColor(n: number): string {
  if (n > 0.004) return colors.pos;
  if (n < -0.004) return colors.neg;
  return colors.textDim;
}
