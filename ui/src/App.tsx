import { useEffect } from "react";
import { startConnection } from "./lib/connection";
import { LadderScreen } from "./screens/LadderScreen";
import { PipelineScreen } from "./screens/PipelineScreen";
import { RaceScreen } from "./screens/RaceScreen";
import { BookHud } from "./components/BookHud";
import type { Screen } from "./store/eventStore";
import { attachPersistence, useEventStore } from "./store/eventStore";
import { colors, fonts } from "./theme";

const SCREEN_LABEL: Record<Screen, string> = {
  pipeline: "Pipeline",
  race: "Race card",
  ladder: "Ladder",
};

const SCREEN_ORDER: Screen[] = ["pipeline", "race", "ladder"];

function NavTabs() {
  const screen = useEventStore((s) => s.screen);
  const setScreen = useEventStore((s) => s.setScreen);

  // Every tab is always reachable — Ladder used to be disabled until a
  // runner was picked on the Race card, which just looked broken (a greyed
  // tab with no explanation). It now always opens; LadderScreen itself
  // shows a "pick a runner on the race card" placeholder when nothing's
  // selected, which actually tells you what to do.
  return (
    <nav
      style={{
        display: "flex",
        gap: 2,
        padding: "10px 12px 8px",
        flexShrink: 0,
      }}
    >
      {SCREEN_ORDER.map((s) => {
        const active = s === screen;
        return (
          <button
            key={s}
            onClick={() => setScreen(s)}
            style={{
              fontFamily: fonts.sans,
              fontSize: 13,
              fontWeight: 600,
              letterSpacing: "-0.01em",
              padding: "7px 14px",
              borderRadius: 8,
              border: "none",
              background: active ? colors.panel2 : "transparent",
              color: active ? colors.text : colors.textDim,
              cursor: "pointer",
            }}
          >
            {SCREEN_LABEL[s]}
          </button>
        );
      })}
    </nav>
  );
}

export default function App() {
  useEffect(() => startConnection(), []);
  // Saves the view to sessionStorage so an iOS tab eviction (switch apps,
  // come back, Safari has reloaded the page) restores what you were
  // looking at instead of an empty room. See store/persist.ts.
  useEffect(() => attachPersistence(), []);
  const screen = useEventStore((s) => s.screen);

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
      <NavTabs />
      <div style={{ position: "relative", flex: 1, minHeight: 0, overflow: "hidden" }}>
        {screen === "pipeline" && <PipelineScreen />}
        {screen === "race" && <RaceScreen />}
        {screen === "ladder" && <LadderScreen />}
      </div>
      <BookHud />
    </div>
  );
}
