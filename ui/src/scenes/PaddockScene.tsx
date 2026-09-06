import { Application, Container, Graphics, Text, TextStyle } from "pixi.js";
import { useEffect, useRef } from "react";
import { attachFpsMeter } from "../lib/fps";
import { runnerKey, useEventStore } from "../store/eventStore";
import type { MarketOpen, RunnerPrice } from "../lib/events";
import { colors, fonts } from "../theme";

const TRACK_LEFT_DESKTOP = 220;
const TRACK_LEFT_PHONE = 150; // phone: labels are the same width, so give the track what is left
const TRACK_RIGHT_MARGIN = 40;
const LANE_HEIGHT = 34;
const CARD_TOP_PADDING = 56;
const CARD_GAP = 24;
const TRAIL_LENGTH = 14;
const FURLONGS = 8;

const RUNNER_COLORS = [0x4fd1ff, 0xffb84f, 0x35e07a, 0xff6b9d, 0xb98aff, 0xffe66d, 0x8affc1, 0xff8a5c];

function impliedProbability(price: number | null): number {
  if (!price || price <= 1) return 0;
  return 1 / price;
}

function bestPrice(rp: RunnerPrice | undefined): number | null {
  if (!rp) return null;
  if (rp.back.length > 0) return rp.back[0].price;
  return rp.ltp;
}

function countdown(offTime: string | null): string {
  if (!offTime) return "--:--";
  const ms = new Date(offTime).getTime() - Date.now();
  if (ms <= 0) return "OFF";
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

interface LaneVisual {
  container: Container;
  horse: Graphics;
  star: Graphics;
  label: Text;
  trail: Graphics;
  trailHistory: number[];
  color: number;
}

interface CardVisual {
  container: Container;
  bg: Graphics;
  finishPost: Graphics;
  furlongMarks: Graphics;
  title: Text;
  countdownText: Text;
  lanes: Map<number, LaneVisual>;
}

// A racehorse in profile as ONE polygon (units ~ 1px at lane scale, drawn
// facing +x): head/neck, back, hindquarters, tail, four legs in a mid-
// gallop pose. Traced by hand so it reads as a horse at 30px, not as the
// ellipse-with-a-wedge it replaced (which read as a beetle in the first
// screenshots). A polygon also means one fill call per horse per frame.
const HORSE_POLY: number[] = [
  // head (nose top) -> ears -> neck top -> withers -> back -> croup -> tail
  20, -6, 18, -9, 15, -10, 13, -13, 11, -10, 8, -9, 4, -8, 0, -8, -5, -8, -9, -8,
  -13, -6, -16, -3, -19, -2,
  // tail
  -21, 1, -20, 5, -17, 3,
  // hind leg (back), trailing
  -15, 4, -17, 10, -14, 10, -12, 5,
  // belly to front legs
  -9, 5, -4, 6,
  // front leg (back, extended forward)
  2, 5, 5, 11, 8, 11, 5, 5,
  // chest -> throat -> jaw -> nose bottom
  9, 3, 12, 0, 15, -1, 18, -2, 21, -3,
];

function drawHorse(g: Graphics, color: number, facingRight: boolean, isFavourite: boolean) {
  g.clear();
  const dir = facingRight ? 1 : -1;
  const pts: number[] = [];
  for (let i = 0; i < HORSE_POLY.length; i += 2) pts.push(HORSE_POLY[i] * dir, HORSE_POLY[i + 1]);
  g.circle(0, 0, 18).fill({ color, alpha: isFavourite ? 0.22 : 0.12 });
  g.poly(pts).fill({ color, alpha: 0.96 });
  // eye
  g.circle(dir * 14, -7, 1.1).fill({ color: colors.bg, alpha: 0.9 });
}

export function PaddockScene() {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const app = new Application();
    let destroyed = false;
    let initialized = false;
    const cards = new Map<string, CardVisual>();
    const worldLayer = new Container();

    const titleStyle = new TextStyle({
      fill: colors.text,
      fontFamily: fonts.sans,
      fontSize: 14,
      fontWeight: "600",
    });
    const countdownStyle = new TextStyle({
      fill: colors.signal,
      fontFamily: fonts.mono,
      fontSize: 13,
      fontWeight: "600",
    });
    const labelStyle = new TextStyle({
      fill: colors.textDim,
      fontFamily: fonts.mono,
      fontSize: 12,
    });

    function ensureCard(marketId: string, market: MarketOpen): CardVisual {
      let card = cards.get(marketId);
      if (card) return card;
      const container = new Container();
      const bg = new Graphics();
      const furlongMarks = new Graphics();
      const finishPost = new Graphics();
      const title = new Text({
        text: `${market.venue ?? "?"} — ${market.race_name ?? market.market_id}`,
        style: titleStyle,
      });
      const countdownText = new Text({ text: "", style: countdownStyle });
      title.x = 16;
      title.y = 14;
      countdownText.anchor.set(1, 0);
      countdownText.y = 14;
      container.addChild(bg, furlongMarks, finishPost, title, countdownText);
      worldLayer.addChild(container);
      card = { container, bg, finishPost, furlongMarks, title, countdownText, lanes: new Map() };
      cards.set(marketId, card);
      return card;
    }

    function ensureLane(card: CardVisual, selectionId: number, name: string | null, laneIndex: number): LaneVisual {
      let lane = card.lanes.get(selectionId);
      if (lane) return lane;
      const container = new Container();
      const trail = new Graphics();
      const horse = new Graphics();
      const star = new Graphics();
      const color = RUNNER_COLORS[laneIndex % RUNNER_COLORS.length];
      const label = new Text({ text: name ?? `#${selectionId}`, style: labelStyle });
      label.anchor.set(0, 0.5);
      label.x = 0;
      container.addChild(trail, horse, star, label);
      card.container.addChild(container);
      lane = { container, horse, star, label, trail, trailHistory: [], color };
      card.lanes.set(selectionId, lane);
      return lane;
    }

    (async () => {
      await app.init({ backgroundAlpha: 0, resizeTo: host, antialias: true });
      if (destroyed) {
        app.destroy(true, { children: true });
        return;
      }
      initialized = true;
      host.appendChild(app.canvas);
      app.stage.addChild(worldLayer);
      attachFpsMeter(app, "paddock");

      app.ticker.add(() => {
        const state = useEventStore.getState();
        // next-off first — the race closest to going off is the one worth
        // watching, so it belongs at the top of the stack
        const markets = Object.values(state.markets).sort((a, b) => {
          const ta = a.off_time ? new Date(a.off_time).getTime() : Infinity;
          const tb = b.off_time ? new Date(b.off_time).getTime() : Infinity;
          return ta - tb;
        });
        const seen = new Set<string>();
        const TRACK_LEFT = app.screen.width < 640 ? TRACK_LEFT_PHONE : TRACK_LEFT_DESKTOP;
        const trackWidth = Math.max(100, app.screen.width - TRACK_LEFT - TRACK_RIGHT_MARGIN);

        let cardY = 0;
        markets.forEach((market) => {
          seen.add(market.market_id);
          const card = ensureCard(market.market_id, market);
          card.container.y = cardY;
          card.countdownText.text = countdown(market.off_time);
          card.countdownText.x = app.screen.width - 24;

          const laneCount = Math.max(1, market.runners.length);
          const cardHeight = CARD_TOP_PADDING + laneCount * LANE_HEIGHT + 16;

          card.bg.clear();
          card.bg
            .roundRect(8, 0, app.screen.width - 16, cardHeight, 12)
            .fill({ color: 0x141a29, alpha: 0.72 })
            .stroke({ width: 1, color: 0xffffff, alpha: 0.06 });

          card.furlongMarks.clear();
          card.finishPost.clear();
          for (let f = 1; f < FURLONGS; f++) {
            const fx = TRACK_LEFT + 20 + (f / FURLONGS) * (trackWidth - 40);
            card.furlongMarks
              .moveTo(fx, CARD_TOP_PADDING - 8)
              .lineTo(fx, CARD_TOP_PADDING + laneCount * LANE_HEIGHT)
              .stroke({ width: 1, color: colors.grid, alpha: 0.5 });
          }
          const postX = TRACK_LEFT + 20 + (trackWidth - 40);
          card.finishPost
            .moveTo(postX, CARD_TOP_PADDING - 12)
            .lineTo(postX, CARD_TOP_PADDING + laneCount * LANE_HEIGHT)
            .stroke({ width: 2, color: colors.text, alpha: 0.5 });

          // max probability this tick, so the favourite sits furthest right
          let maxProb = 0;
          let favouriteSelection: number | null = null;
          for (const r of market.runners) {
            const rp = state.runnerPrices[runnerKey(market.market_id, r.selection_id)];
            const prob = impliedProbability(bestPrice(rp));
            if (prob > maxProb) {
              maxProb = prob;
              favouriteSelection = r.selection_id;
            }
          }

          market.runners.forEach((runner, laneIndex) => {
            const lane = ensureLane(card, runner.selection_id, runner.name, laneIndex);
            lane.container.y = CARD_TOP_PADDING + laneIndex * LANE_HEIGHT;
            lane.label.x = 0;

            const rp = state.runnerPrices[runnerKey(market.market_id, runner.selection_id)];
            const price = bestPrice(rp);
            const prob = impliedProbability(price);
            const frac = maxProb > 0 ? prob / maxProb : 0;
            const x = TRACK_LEFT + 20 + frac * (trackWidth - 40);

            lane.trailHistory.push(x);
            if (lane.trailHistory.length > TRAIL_LENGTH) lane.trailHistory.shift();

            lane.trail.clear();
            lane.trailHistory.forEach((tx, i) => {
              const alpha = (i / TRAIL_LENGTH) * 0.35;
              lane.trail.circle(tx, 0, 4).fill({ color: lane.color, alpha });
            });

            // Bob while moving: a horse that just changed price is galloping,
            // one sitting on its price is standing. Motion amount = how far it
            // moved in the last few frames, so a big price move gallops harder.
            const recent = lane.trailHistory.length > 4 ? Math.abs(x - lane.trailHistory[lane.trailHistory.length - 5]) : 0;
            const gallop = Math.min(1, recent / 12);
            const bob = gallop > 0.02 ? Math.sin(performance.now() / 90) * 2.2 * gallop : 0;
            drawHorse(lane.horse, lane.color, true, runner.selection_id === favouriteSelection && maxProb > 0);
            lane.horse.x = x;
            lane.horse.y = bob;

            lane.star.clear();
            if (runner.selection_id === favouriteSelection && maxProb > 0) {
              const sx = x - 32;
              const spikes = 5;
              const outer = 6;
              const inner = 2.6;
              const pts: number[] = [];
              for (let i = 0; i < spikes * 2; i++) {
                const r = i % 2 === 0 ? outer : inner;
                const a = (Math.PI / spikes) * i - Math.PI / 2;
                pts.push(sx + Math.cos(a) * r, Math.sin(a) * r);
              }
              lane.star.poly(pts).fill({ color: colors.signal, alpha: 0.95 });
            }

            if (!lane.container.eventMode || lane.container.eventMode === "none") {
              lane.container.eventMode = "static";
              lane.container.cursor = "pointer";
              lane.container.hitArea = { contains: () => true } as never;
              lane.container.on("pointerdown", () => {
                useEventStore.getState().selectRunner(market.market_id, runner.selection_id);
              });
            }

            const priceLabel = price ? price.toFixed(2) : "—";
            lane.label.text = `${runner.name ?? `#${runner.selection_id}`}  ${priceLabel}`;
          });

          cardY += cardHeight + CARD_GAP;
        });

        for (const [marketId, card] of cards) {
          if (!seen.has(marketId)) {
            card.container.destroy({ children: true });
            cards.delete(marketId);
          }
        }
      });
    })();

    return () => {
      destroyed = true;
      // See FloorScene's identical guard: React 19 StrictMode double-
      // invokes effects in dev, and app.init() may not have resolved by
      // the time the first mount's cleanup runs.
      if (!initialized) return;
      app.ticker.stop();
      for (const card of cards.values()) card.container.destroy({ children: true });
      if (app.canvas?.parentElement) app.canvas.parentElement.removeChild(app.canvas);
      app.destroy(true, { children: true });
    };
  }, []);

  const markets = useEventStore((s) => s.markets);
  const hasMarkets = Object.keys(markets).length > 0;

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <div ref={hostRef} style={{ width: "100%", height: "100%" }} />
      {!hasMarkets && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: colors.textDim,
            fontFamily: fonts.mono,
            fontSize: 13,
            pointerEvents: "none",
          }}
        >
          waiting for a market to open…
        </div>
      )}
    </div>
  );
}
