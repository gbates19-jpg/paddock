import type { Application } from "pixi.js";

// Pixi's ticker already keeps a rolling FPS average — this just publishes
// it somewhere scripts/snap.mjs (no access to React/Pixi internals) can
// read it from after driving the page for a few seconds.
declare global {
  interface Window {
    __paddockFPS?: Record<string, number>;
  }
}

export function attachFpsMeter(app: Application, sceneName: string): void {
  window.__paddockFPS ??= {};
  app.ticker.add(() => {
    window.__paddockFPS![sceneName] = Math.round(app.ticker.FPS);
  });
}
