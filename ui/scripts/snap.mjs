// Visual verification without the Claude-in-Chrome extension: starts the
// dev server, opens ?demo=1, captures a screenshot of each scene (Floor,
// Paddock, Ladder on a depth-having runner, Ladder on a no-depth runner)
// plus a short webm of the Floor, at BOTH a desktop viewport (1280x800)
// and a phone viewport (390x844, iPhone 12-ish) — and fails the whole run
// if the page logged any console error or uncaught exception along the
// way. Also samples the Floor scene's Pixi ticker FPS during the demo
// stream's dense tick-burst (its stand-in for a real Pro replay's ~50ms
// tick rate) and prints it, so a regression in render cost shows up here
// instead of only being noticed as "it feels laggy".
//
// Scene/runner navigation goes through window.__paddockStore (see
// src/main.tsx, dev-only) rather than clicking canvas coordinates —
// PixiJS scenes have no stable DOM to select against, and pixel
// coordinates would be fragile against window size / live price
// movement. Only the Paddock tab button is a real DOM click, since
// that's an actual button. The Book HUD is a persistent bottom bar (see
// src/scenes/BookScene.tsx), not a separate tab, so it's already visible
// in every capture below rather than needing its own.

import { spawn } from "node:child_process";
import { existsSync, mkdirSync, renameSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const SNAP_DIR = path.join(ROOT, "snapshots");
const PORT = 5183;
const BASE_URL = `http://localhost:${PORT}`;

// Real Brighton market/runner ids from data/basic/2026/09 — see
// src/data/demoEvents.ts's header comment for provenance.
const DEMO_MARKET_ID = "1.261733284";
const DEPTH_SELECTION_ID = 5240218; // Shining Guest — given synthetic depth for the demo
const NO_DEPTH_SELECTION_ID = 84836613; // Loleeta — deliberately left with none

const VIEWPORTS = [
  { name: "", width: 1280, height: 800 }, // desktop — unsuffixed filenames, as before
  { name: "-phone", width: 390, height: 844 },
];

function waitForServer(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = async () => {
      try {
        const res = await fetch(url);
        if (res.ok || res.status === 404) return resolve();
      } catch {
        // not up yet
      }
      if (Date.now() > deadline) return reject(new Error(`dev server did not come up within ${timeoutMs}ms`));
      setTimeout(attempt, 250);
    };
    attempt();
  });
}

function attachErrorCollectors(page, sink, sceneLabel) {
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      sink.push({ scene: sceneLabel, text: msg.text() });
    }
  });
  page.on("pageerror", (err) => {
    sink.push({ scene: sceneLabel, text: err.message });
  });
}

async function captureViewport(browser, viewport, consoleErrors, expectedFiles) {
  const suffix = viewport.name;
  console.log(`\n=== Viewport ${viewport.width}x${viewport.height}${suffix ? ` (${suffix.slice(1)})` : ""} ===`);

  // --- Floor: recorded as a 10s webm, screenshot + FPS sample taken
  // partway through (inside the demo stream's dense tick-burst) ---
  const floorContext = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    recordVideo: { dir: SNAP_DIR, size: { width: viewport.width, height: viewport.height } },
  });
  const floorPage = await floorContext.newPage();
  attachErrorCollectors(floorPage, consoleErrors, `floor${suffix}`);

  await floorPage.goto(`${BASE_URL}/?demo=1`, { waitUntil: "load" });
  await floorPage.waitForSelector("canvas", { timeout: 10_000 });
  await floorPage.waitForTimeout(5500); // land inside the dense-burst window (~4.8s-7.8s in)
  const fps = await floorPage.evaluate(() => window.__paddockFPS?.floor ?? null);
  console.log(`Floor FPS during dense tick-burst: ${fps ?? "unavailable"}`);
  await floorPage.screenshot({ path: path.join(SNAP_DIR, `floor${suffix}.png`) });
  console.log(`Captured floor${suffix}.png`);
  expectedFiles.push(`floor${suffix}.png`);

  await floorPage.waitForTimeout(4500); // keep recording for a full 10s total
  const floorVideo = floorPage.video();
  await floorContext.close();
  if (floorVideo) {
    const savedPath = await floorVideo.path();
    renameSync(savedPath, path.join(SNAP_DIR, `floor${suffix}.webm`));
    console.log(`Captured floor${suffix}.webm`);
    expectedFiles.push(`floor${suffix}.webm`);
  }

  // --- Paddock + Ladder (pro depth, and no-depth) ---
  // Each capture gets its OWN fresh page load rather than sharing one
  // long-lived session: the demo stream loops and closes its market
  // ~9s in, and a shared session accumulates wait time across steps —
  // found this the hard way, the second Ladder capture landed after
  // the demo market had already closed and showed the "#4" selection-id
  // fallback instead of the runner's name.
  const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height } });

  async function freshDemoPage() {
    const page = await context.newPage();
    attachErrorCollectors(page, consoleErrors, `paddock/ladder${suffix}`);
    await page.goto(`${BASE_URL}/?demo=1`, { waitUntil: "load" });
    await page.waitForSelector("canvas", { timeout: 10_000 });
    return page;
  }

  const paddockPage = await freshDemoPage();
  await paddockPage.click("text=PADDOCK");
  await paddockPage.waitForTimeout(3000);
  await paddockPage.screenshot({ path: path.join(SNAP_DIR, `paddock${suffix}.png`) });
  console.log(`Captured paddock${suffix}.png`);
  expectedFiles.push(`paddock${suffix}.png`);
  await paddockPage.close();

  const ladderProPage = await freshDemoPage();
  await ladderProPage.waitForTimeout(1000); // let market.open (fires at t=400ms) land first
  await ladderProPage.evaluate(
    ({ marketId, selectionId }) => {
      // @ts-expect-error dev-only hook, see src/main.tsx
      window.__paddockStore.getState().selectRunner(marketId, selectionId);
    },
    { marketId: DEMO_MARKET_ID, selectionId: DEPTH_SELECTION_ID }
  );
  await ladderProPage.waitForTimeout(3000);
  await ladderProPage.screenshot({ path: path.join(SNAP_DIR, `ladder-pro${suffix}.png`) });
  console.log(`Captured ladder-pro${suffix}.png`);
  expectedFiles.push(`ladder-pro${suffix}.png`);
  await ladderProPage.close();

  const ladderBasicPage = await freshDemoPage();
  await ladderBasicPage.waitForTimeout(1000);
  await ladderBasicPage.evaluate(
    ({ marketId, selectionId }) => {
      // @ts-expect-error dev-only hook, see src/main.tsx
      window.__paddockStore.getState().selectRunner(marketId, selectionId);
    },
    { marketId: DEMO_MARKET_ID, selectionId: NO_DEPTH_SELECTION_ID }
  );
  await ladderBasicPage.waitForTimeout(3000);
  await ladderBasicPage.screenshot({ path: path.join(SNAP_DIR, `ladder-basic${suffix}.png`) });
  console.log(`Captured ladder-basic${suffix}.png`);
  expectedFiles.push(`ladder-basic${suffix}.png`);
  await ladderBasicPage.close();

  await context.close();
}

async function main() {
  rmSync(SNAP_DIR, { recursive: true, force: true });
  mkdirSync(SNAP_DIR, { recursive: true });

  console.log(`Starting dev server on port ${PORT}...`);
  const devServer = spawn("npm", ["run", "dev", "--", "--port", String(PORT), "--strictPort"], {
    cwd: ROOT,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let serverOutput = "";
  devServer.stdout.on("data", (d) => (serverOutput += d.toString()));
  devServer.stderr.on("data", (d) => (serverOutput += d.toString()));

  const consoleErrors = [];
  const expectedFiles = [];

  try {
    await waitForServer(BASE_URL, 20_000);
    console.log("Dev server is up.");

    const browser = await chromium.launch(process.env.PW_EXECUTABLE ? { executablePath: process.env.PW_EXECUTABLE } : {});
    for (const viewport of VIEWPORTS) {
      await captureViewport(browser, viewport, consoleErrors, expectedFiles);
    }
    await browser.close();
  } finally {
    devServer.kill();
  }

  if (consoleErrors.length > 0) {
    console.error(`\n${consoleErrors.length} console error(s)/page error(s) during the run:`);
    for (const e of consoleErrors) console.error(`  [${e.scene}] ${e.text}`);
    process.exit(1);
  }

  for (const name of expectedFiles) {
    if (!existsSync(path.join(SNAP_DIR, name))) {
      console.error(`Expected output missing: ${name}`);
      process.exit(1);
    }
  }

  console.log(`\nAll ${expectedFiles.length} snapshots captured across ${VIEWPORTS.length} viewports, no console errors.`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
