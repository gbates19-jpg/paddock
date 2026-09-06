import { Application, Container, Graphics, Text, TextStyle } from "pixi.js";
import { useEffect, useRef } from "react";
import { attachFpsMeter } from "../lib/fps";
import { useEventStore } from "../store/eventStore";
import { colors, eventColor, fonts } from "../theme";

const NODE_COLORS = {
  idle: colors.idle,
  busy: colors.busy,
  error: colors.error,
} as const;

// Main pipeline reads left-to-right the way data actually flows: the
// stream ingests ticks, the strategy reasons over them, the executor
// places orders, pnl marks them. keep_alive/data_loader don't sit on that
// path — they're drawn as satellites underneath instead of forced into
// the row.
const MAIN_ROW = ["stream", "strategy", "executor", "pnl"];
const SATELLITES = ["keep_alive", "data_loader"];

interface NodeVisual {
  container: Container;
  ring: Graphics;
  core: Graphics;
  label: Text;
  spin: number;
  shakeUntil: number;
  lastState: string;
}

interface ParticleVisual {
  gfx: Graphics;
  bornAt: number;
  from: string;
  to: string;
}

const DURATION_MS = 900;

function resolveNodeName(knownNames: string[], name: string): string {
  if (knownNames.includes(name)) return name;
  if (name === "strategy") {
    const match = knownNames.find((n) => n.startsWith("strategy:"));
    if (match) return match;
  }
  return name;
}

function flowSlot(resolvedName: string, extras: string[]): { row: "main" | "sat"; index: number } {
  const mainIndex = MAIN_ROW.findIndex((n) => n === resolvedName || (n === "strategy" && resolvedName.startsWith("strategy:")));
  if (mainIndex >= 0) return { row: "main", index: mainIndex };
  const satIndex = SATELLITES.indexOf(resolvedName);
  if (satIndex >= 0) return { row: "sat", index: satIndex };
  return { row: "sat", index: SATELLITES.length + extras.indexOf(resolvedName) };
}

export function FloorScene() {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const app = new Application();
    let destroyed = false;
    let initialized = false;

    const nodeVisuals = new Map<string, NodeVisual>();
    const particleVisuals = new Map<string, ParticleVisual>();
    const bgLayer = new Container();
    const worldLayer = new Container();
    const particleLayer = new Container();
    const grid = new Graphics();
    bgLayer.addChild(grid);

    const layoutName = new TextStyle({
      fill: colors.textDim,
      fontFamily: fonts.mono,
      fontSize: 12,
    });
    const layoutNameNarrow = new TextStyle({
      fill: colors.textDim,
      fontFamily: fonts.mono,
      fontSize: 9,
    });

    const SHORT_LABELS: Record<string, string> = {
      stream: "stream",
      executor: "exec",
      pnl: "pnl",
      keep_alive: "alive",
      data_loader: "loader",
    };

    // Full worker names ("strategy:BaselineFavouriteScalp") are wider
    // than the gap between nodes on a phone-width screen and overlap
    // their neighbours — abbreviate below NARROW_PX rather than shrinking
    // text to the point of being unreadable.
    const NARROW_PX = 640;
    function shortLabel(name: string): string {
      if (name.startsWith("strategy:")) return "strat";
      return SHORT_LABELS[name] ?? name.slice(0, 6);
    }

    function drawGrid() {
      const w = app.screen.width || 800;
      const h = app.screen.height || 500;
      const step = 48;
      grid.clear();
      for (let x = 0; x < w; x += step) grid.moveTo(x, 0).lineTo(x, h);
      for (let y = 0; y < h; y += step) grid.moveTo(0, y).lineTo(w, y);
      grid.stroke({ width: 1, color: colors.grid, alpha: 0.35 });

      // static connector line through the main pipeline row, so the
      // left-to-right data flow reads as a path even with no traffic on it
      const pad = w * 0.12;
      const gap = (w - pad * 2) / Math.max(1, MAIN_ROW.length - 1);
      const y = h * 0.4;
      grid.moveTo(pad, y).lineTo(pad + gap * (MAIN_ROW.length - 1), y).stroke({ width: 2, color: colors.grid, alpha: 0.8 });
    }

    function nodePosition(name: string, names: string[]): { x: number; y: number } {
      const extras = names.filter(
        (n) => !MAIN_ROW.includes(n) && !n.startsWith("strategy:") && !SATELLITES.includes(n)
      );
      const slot = flowSlot(name, extras);
      const w = app.screen.width || 800;
      const h = app.screen.height || 500;
      if (slot.row === "main") {
        const pad = w * 0.12;
        const gap = (w - pad * 2) / Math.max(1, MAIN_ROW.length - 1);
        return { x: pad + slot.index * gap, y: h * 0.4 };
      }
      const satCount = SATELLITES.length + extras.length;
      const pad = w * 0.3;
      const gap = (w - pad * 2) / Math.max(1, satCount - 1 || 1);
      return { x: satCount > 1 ? pad + slot.index * gap : w / 2, y: h * 0.78 };
    }

    function ensureNode(name: string): NodeVisual {
      let node = nodeVisuals.get(name);
      if (node) return node;
      const container = new Container();
      const ring = new Graphics();
      const core = new Graphics();
      const label = new Text({ text: name, style: layoutName });
      label.anchor.set(0.5, 0);
      label.y = 22;
      container.addChild(ring, core, label);
      worldLayer.addChild(container);
      node = { container, ring, core, label, spin: 0, shakeUntil: 0, lastState: "idle" };
      nodeVisuals.set(name, node);
      return node;
    }

    function drawNode(node: NodeVisual, state: "idle" | "busy" | "error", pulse: number) {
      const color = NODE_COLORS[state];
      node.core.clear();
      node.core.circle(0, 0, 22 + pulse * 8).fill({ color, alpha: 0.08 });
      node.core.circle(0, 0, 16 + pulse * 6).fill({ color, alpha: 0.22 });
      node.core.circle(0, 0, 10 + pulse * 4).fill({ color, alpha: 0.95 });

      node.ring.clear();
      if (state === "busy" && !reduceMotion) {
        node.ring.arc(0, 0, 20, node.spin, node.spin + Math.PI * 1.2).stroke({ width: 2, color });
      } else if (state === "error") {
        node.ring.circle(0, 0, 20).stroke({ width: 2, color });
      }
    }

    (async () => {
      await app.init({
        backgroundAlpha: 0, // App's ambient background shows through
        resizeTo: host,
        antialias: true,
      });
      if (destroyed) {
        app.destroy(true, { children: true });
        return;
      }
      initialized = true;
      host.appendChild(app.canvas);
      app.stage.addChild(bgLayer, worldLayer, particleLayer);
      attachFpsMeter(app, "floor");
      drawGrid();
      app.renderer.on("resize", drawGrid);

      // "strategy" is a slot in MAIN_ROW for layout purposes only — the
      // real node is whatever concrete "strategy:<Name>" worker heartbeat
      // shows up (see flowSlot/resolveNodeName below); creating a literal
      // "strategy" node here too would draw two overlapping labels in the
      // same spot the moment a real strategy heartbeat arrives.
      for (const name of MAIN_ROW) if (name !== "strategy") ensureNode(name);
      for (const name of SATELLITES) ensureNode(name);

      app.ticker.add(() => {
        const state = useEventStore.getState();
        const names = Array.from(
          new Set([...MAIN_ROW.filter((n) => n !== "strategy"), ...SATELLITES, ...Object.keys(state.workers)])
        );

        const narrow = (app.screen.width || 800) < NARROW_PX;
        for (const name of names) {
          const node = ensureNode(name);
          const pos = nodePosition(name, names);
          node.container.x = pos.x;
          node.container.y = pos.y;
          node.label.style = narrow ? layoutNameNarrow : layoutName;
          node.label.text = narrow ? shortLabel(name) : name;

          const hb = state.workers[name];
          const workerState = hb?.state ?? "idle";
          if (workerState === "busy" && !reduceMotion) node.spin += 0.08;
          if (workerState === "error" && node.lastState !== "error") node.shakeUntil = performance.now() + 400;
          node.lastState = workerState;

          let shakeX = 0;
          if (node.shakeUntil > performance.now()) {
            shakeX = Math.sin(performance.now() / 30) * 3;
          }
          node.container.x += shakeX;

          const pulse = workerState === "busy" ? (Math.sin(performance.now() / 140) + 1) / 2 : 0;
          drawNode(node, workerState, pulse);
        }

        // particles: mirror store.particles into pixi graphics, animate progress by wall clock
        const seen = new Set<string>();
        for (const p of state.particles) {
          seen.add(p.id);
          let pv = particleVisuals.get(p.id);
          if (!pv) {
            const gfx = new Graphics();
            particleLayer.addChild(gfx);
            pv = { gfx, bornAt: p.bornAt, from: p.from, to: p.to };
            particleVisuals.set(p.id, pv);
          }
          const elapsed = performance.now() - pv.bornAt;
          const t = Math.min(1, elapsed / DURATION_MS);
          const fromName = resolveNodeName(names, p.from);
          const toName = resolveNodeName(names, p.to);
          const a = nodePosition(fromName, names);
          const b = nodePosition(toName, names);
          const midX = (a.x + b.x) / 2;
          const midY = (a.y + b.y) / 2 - 40;
          const x = (1 - t) * (1 - t) * a.x + 2 * (1 - t) * t * midX + t * t * b.x;
          const y = (1 - t) * (1 - t) * a.y + 2 * (1 - t) * t * midY + t * t * b.y;
          const color = eventColor(p.kind);
          pv.gfx.clear();
          pv.gfx.circle(x, y, p.size * 0.7).fill({ color, alpha: 0.15 });
          pv.gfx.circle(x, y, p.size * 0.4).fill({ color, alpha: 1 - t * 0.3 });

          if (t >= 1) {
            pv.gfx.destroy();
            particleVisuals.delete(p.id);
            useEventStore.getState().pruneParticle(p.id);
          }
        }
        for (const [id, pv] of particleVisuals) {
          if (!seen.has(id)) {
            pv.gfx.destroy();
            particleVisuals.delete(id);
          }
        }
      });
    })();

    return () => {
      destroyed = true;
      // React 19 StrictMode double-invokes effects in dev: mount, cleanup,
      // mount again. If the first mount's async app.init() hasn't resolved
      // yet when its cleanup runs, app.ticker (and the rest of the app)
      // doesn't exist yet — the `if (destroyed)` branch above handles
      // destroying it once init does resolve, so there's nothing to do
      // here yet. Found this the hard way: it threw "Cannot read
      // properties of undefined (reading 'stop')" under Playwright, which
      // is the first time this code ever ran in a real browser.
      if (!initialized) return;
      app.ticker.stop();
      for (const node of nodeVisuals.values()) node.container.destroy({ children: true });
      for (const pv of particleVisuals.values()) pv.gfx.destroy();
      if (app.canvas?.parentElement) app.canvas.parentElement.removeChild(app.canvas);
      app.destroy(true, { children: true });
    };
  }, []);

  return <div ref={hostRef} style={{ width: "100%", height: "100%" }} />;
}
