import { Application, Container, Graphics, Text, TextStyle } from "pixi.js";
import { useEffect, useRef } from "react";
import { runnerKey, useEventStore } from "../store/eventStore";
import type { MarketOpen, RunnerPrice } from "../lib/events";

const TRACK_LEFT = 220;
const TRACK_RIGHT_MARGIN = 40;
const LANE_HEIGHT = 34;
const CARD_TOP_PADDING = 56;
const CARD_GAP = 24;
const TRAIL_LENGTH = 14;

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

interface LaneVisual {
  container: Container;
  dot: Graphics;
  label: Text;
  trail: Graphics;
  trailHistory: number[];
  color: number;
}

interface CardVisual {
  container: Container;
  bg: Graphics;
  title: Text;
  lanes: Map<number, LaneVisual>;
}

export function PaddockScene() {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const app = new Application();
    let destroyed = false;
    const cards = new Map<string, CardVisual>();
    const worldLayer = new Container();

    const titleStyle = new TextStyle({
      fill: 0xe4e8f0,
      fontFamily: "ui-sans-serif, system-ui, sans-serif",
      fontSize: 14,
      fontWeight: "600",
    });
    const labelStyle = new TextStyle({
      fill: 0xaab4c8,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
      fontSize: 12,
    });

    function ensureCard(marketId: string, market: MarketOpen): CardVisual {
      let card = cards.get(marketId);
      if (card) return card;
      const container = new Container();
      const bg = new Graphics();
      const title = new Text({
        text: `${market.venue ?? "?"} — ${market.race_name ?? market.market_id}`,
        style: titleStyle,
      });
      title.x = 16;
      title.y = 14;
      container.addChild(bg, title);
      worldLayer.addChild(container);
      card = { container, bg, title, lanes: new Map() };
      cards.set(marketId, card);
      return card;
    }

    function ensureLane(card: CardVisual, selectionId: number, name: string | null, laneIndex: number): LaneVisual {
      let lane = card.lanes.get(selectionId);
      if (lane) return lane;
      const container = new Container();
      const trail = new Graphics();
      const dot = new Graphics();
      const color = RUNNER_COLORS[laneIndex % RUNNER_COLORS.length];
      const label = new Text({ text: name ?? `#${selectionId}`, style: labelStyle });
      label.anchor.set(0, 0.5);
      label.x = 0;
      container.addChild(trail, dot, label);
      card.container.addChild(container);
      lane = { container, dot, label, trail, trailHistory: [], color };
      card.lanes.set(selectionId, lane);
      return lane;
    }

    (async () => {
      await app.init({ background: 0x0a0e17, resizeTo: host, antialias: true });
      if (destroyed) {
        app.destroy(true, { children: true });
        return;
      }
      host.appendChild(app.canvas);
      app.stage.addChild(worldLayer);

      app.ticker.add(() => {
        const state = useEventStore.getState();
        const markets = Object.values(state.markets);
        const seen = new Set<string>();
        const trackWidth = Math.max(100, app.screen.width - TRACK_LEFT - TRACK_RIGHT_MARGIN);

        let cardY = 0;
        markets.forEach((market) => {
          seen.add(market.market_id);
          const card = ensureCard(market.market_id, market);
          card.container.y = cardY;

          const laneCount = Math.max(1, market.runners.length);
          const cardHeight = CARD_TOP_PADDING + laneCount * LANE_HEIGHT + 16;

          card.bg.clear();
          card.bg
            .roundRect(8, 0, app.screen.width - 16, cardHeight, 12)
            .fill({ color: 0x141a29, alpha: 0.72 })
            .stroke({ width: 1, color: 0xffffff, alpha: 0.06 });

          // max probability this tick, so the favourite sits furthest right
          let maxProb = 0;
          for (const r of market.runners) {
            const rp = state.runnerPrices[runnerKey(market.market_id, r.selection_id)];
            maxProb = Math.max(maxProb, impliedProbability(bestPrice(rp)));
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

            lane.dot.clear();
            lane.dot.circle(x, 0, 8).fill({ color: lane.color, alpha: 0.95 });
            lane.dot.circle(x, 0, 12).fill({ color: lane.color, alpha: 0.2 });

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
            color: "#7c8496",
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
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
