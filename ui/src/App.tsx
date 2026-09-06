import { useEffect, useState } from "react";
import { startConnection } from "./lib/connection";
import { BookScene } from "./scenes/BookScene";
import { FloorScene } from "./scenes/FloorScene";
import { LadderScene } from "./scenes/LadderScene";
import { PaddockScene } from "./scenes/PaddockScene";
import type { Scene } from "./store/eventStore";
import { useEventStore } from "./store/eventStore";
import { colors, colorsCss, fonts } from "./theme";

const SCENE_LABEL: Record<Scene, string> = {
  floor: "THE FLOOR",
  paddock: "THE PADDOCK",
  ladder: "THE LADDER",
};

// The header is ONLY the scene tabs. Connection/mode/P&L/speed all live in
// the single Book HUD at the bottom (scenes/BookScene.tsx) — one place for
// the run's vitals, not a floating badge cluster competing with it. It is a
// real flex row scenes render below, not an overlay (an earlier overlay
// version got painted over by the Paddock's positioned root — caught by
// scripts/snap.mjs, never by reading the code).
function useIsNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => window.innerWidth < 640);
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 640);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return narrow;
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
      <div
        style={{
          fontFamily: fonts.mono,
          fontSize: 11,
          letterSpacing: "0.18em",
          color: colors.textFaint,
          alignSelf: "center",
        }}
      >
        PADDOCK
      </div>
    </div>
  );
}

// Ambient background: two slow-drifting radial glows behind everything.
// Pure CSS (index.css @keyframes), no per-frame JS, and it stops under
// prefers-reduced-motion — cheap enough to leave on for the phone view,
// unlike the animated grain this replaced.
function AmbientBackground() {
  return (
    <div aria-hidden style={{ position: "absolute", inset: 0, pointerEvents: "none", zIndex: 0 }}>
      <div className="ambient-glow ambient-glow-a" />
      <div className="ambient-glow ambient-glow-b" />
      <div className="ambient-vignette" />
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
        position: "relative",
        overflow: "hidden",
      }}
    >
      <AmbientBackground />
      <Header narrow={narrow} />
      <div style={{ position: "relative", flex: 1, minHeight: 0, zIndex: 1 }}>
        {scene === "floor" && <FloorScene />}
        {scene === "paddock" && <PaddockScene />}
        {scene === "ladder" && <LadderScene />}
      </div>
      <BookScene />
    </div>
  );
}
