import { Application, Container, Graphics, Text, TextStyle } from "pixi.js";
import { useEffect, useRef } from "react";
import { useEventStore } from "../store/eventStore";

const NODE_COLORS = {
  idle: 0x3a4a63,
  busy: 0x4fd1ff,
  error: 0xff4d6d,
} as const;

const PARTICLE_COLORS: Record<string, number> = {
  "runner.price": 0x4fd1ff,
  "strategy.signal": 0xffb84f,
  "order.placed": 0x8affc1,
  "order.matched": 0x35e07a,
  "order.cancelled": 0x8a93a6,
  "order.lapsed": 0x8a93a6,
  "pnl.update": 0xffd54f,
};

const BASE_WORKER_ORDER = ["stream", "keep_alive", "executor", "data_loader", "pnl"];

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

export function FloorScene() {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const app = new Application();
    let destroyed = false;

    const nodeVisuals = new Map<string, NodeVisual>();
    const particleVisuals = new Map<string, ParticleVisual>();
    const worldLayer = new Container();
    const particleLayer = new Container();

    const layoutName = new TextStyle({
      fill: 0xaab4c8,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
      fontSize: 12,
    });

    function nodePosition(name: string, names: string[]): { x: number; y: number } {
      const idx = Math.max(0, names.indexOf(name));
      const angle = (idx / Math.max(1, names.length)) * Math.PI * 2 - Math.PI / 2;
      const w = app.screen.width || 800;
      const h = app.screen.height || 500;
      const cx = w / 2;
      const cy = h / 2;
      const r = Math.min(w, h) * 0.32;
      return { x: cx + Math.cos(angle) * r, y: cy + Math.sin(angle) * r };
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
      node.core.circle(0, 0, 10 + pulse * 4).fill({ color, alpha: 0.9 });
      node.core.circle(0, 0, 16 + pulse * 6).fill({ color, alpha: 0.18 });

      node.ring.clear();
      if (state === "busy" && !reduceMotion) {
        node.ring.arc(0, 0, 20, node.spin, node.spin + Math.PI * 1.2).stroke({ width: 2, color });
      } else if (state === "error") {
        node.ring.circle(0, 0, 20).stroke({ width: 2, color });
      }
    }

    (async () => {
      await app.init({
        background: 0x0a0e17,
        resizeTo: host,
        antialias: true,
      });
      if (destroyed) {
        app.destroy(true, { children: true });
        return;
      }
      host.appendChild(app.canvas);
      app.stage.addChild(worldLayer, particleLayer);

      for (const name of BASE_WORKER_ORDER) ensureNode(name);

      app.ticker.add(() => {
        const state = useEventStore.getState();
        const names = Array.from(new Set([...BASE_WORKER_ORDER, ...Object.keys(state.workers)]));

        for (const name of names) {
          const node = ensureNode(name);
          const pos = nodePosition(name, names);
          node.container.x = pos.x;
          node.container.y = pos.y;

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
          const color = PARTICLE_COLORS[p.kind] ?? 0xffffff;
          pv.gfx.clear();
          pv.gfx.circle(x, y, p.size * 0.5).fill({ color, alpha: 1 - t * 0.3 });

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
      app.ticker.stop();
      for (const node of nodeVisuals.values()) node.container.destroy({ children: true });
      for (const pv of particleVisuals.values()) pv.gfx.destroy();
      if (app.canvas?.parentElement) app.canvas.parentElement.removeChild(app.canvas);
      app.destroy(true, { children: true });
    };
  }, []);

  return <div ref={hostRef} style={{ width: "100%", height: "100%" }} />;
}
