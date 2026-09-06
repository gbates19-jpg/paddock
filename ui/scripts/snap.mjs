// Visual verification without the Claude-in-Chrome extension: starts the
// dev server, opens ?demo=1, captures each screen (Pipeline, Race card
// with an open position, Ladder on a depth-having runner, Ladder on a
// no-depth runner) at BOTH a desktop viewport (1280x800) and a phone
// viewport (390x844, iPhone 12-ish) — and fails the whole run if the page
// logged any console error or uncaught exception along the way.
//
// v2 is plain DOM/CSS (no PixiJS scenes, no canvas, no FPS sampling —
// see screens/PipelineScreen.tsx's header comment for why). Runner
// selection still goes through window.__paddockStore (see src/main.tsx,
// dev-only) rather than clicking — it's the one navigation Playwright
// can't do through a real control, since the race card's rows are the
// only way in and their layout can shift.
//
// Each capture below is timed against the demo's own offsetMs schedule
// in src/data/demoEvents.ts (real ms, not scaled) so the Race card is
// grabbed with an open, hedged position and the Ladder is grabbed with
// an order chip resting in it — not at t=0 with nothing to look at.

import { spawn } from "node:child_process";
import { existsSync, mkdirSync, rmSync } from "node:fs";
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
const DEPTH_SELECTION_ID = 5240218; // Shining Guest — our favourite, given synthetic depth for the demo
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

function attachErrorCollectors(page, sink, label) {
  page.on("console", (msg) => {
    if (msg.type() === "error") sink.push({ scene: label, text: msg.text() });
  });
  page.on("pageerror", (err) => sink.push({ scene: label, text: err.message }));
}

async function captureViewport(browser, viewport, consoleErrors, expectedFiles) {
  const suffix = viewport.name;
  console.log(`\n=== Viewport ${viewport.width}x${viewport.height}${suffix ? ` (${suffix.slice(1)})` : ""} ===`);

  const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height } });

  async function freshDemoPage(label) {
    const page = await context.newPage();
    attachErrorCollectors(page, consoleErrors, `${label}${suffix}`);
    await page.goto(`${BASE_URL}/?demo=1`, { waitUntil: "load" });
    await page.waitForSelector("text=Pipeline", { timeout: 10_000 });
    return page;
  }

  async function selectRunner(page, selectionId) {
    await page.evaluate(
      ({ marketId, selectionId }) => {
        // @ts-expect-error dev-only hook, see src/main.tsx
        window.__paddockStore.getState().selectRunner(marketId, selectionId);
      },
      { marketId: DEMO_MARKET_ID, selectionId }
    );
  }

  // --- Pipeline: mid-way through the ticking phase, some flow to see ---
  const pipelinePage = await freshDemoPage("pipeline");
  await pipelinePage.waitForTimeout(3500);
  await pipelinePage.screenshot({ path: path.join(SNAP_DIR, `pipeline${suffix}.png`) });
  console.log(`Captured pipeline${suffix}.png`);
  expectedFiles.push(`pipeline${suffix}.png`);
  await pipelinePage.close();

  // --- Race card: after the first hedge locks, so a position shows ---
  const racePage = await freshDemoPage("race");
  await racePage.waitForTimeout(13_500);
  await racePage.click("text=Race card");
  await racePage.waitForTimeout(300);
  await racePage.screenshot({ path: path.join(SNAP_DIR, `race${suffix}.png`) });
  console.log(`Captured race${suffix}.png`);
  expectedFiles.push(`race${suffix}.png`);
  await racePage.close();

  // --- Ladder, depth-having runner: after the lay is resting (~9s) ---
  const ladderProPage = await freshDemoPage("ladder-pro");
  await ladderProPage.waitForTimeout(9800);
  await selectRunner(ladderProPage, DEPTH_SELECTION_ID);
  await ladderProPage.waitForTimeout(600);
  await ladderProPage.screenshot({ path: path.join(SNAP_DIR, `ladder-pro${suffix}.png`) });
  console.log(`Captured ladder-pro${suffix}.png`);
  expectedFiles.push(`ladder-pro${suffix}.png`);
  await ladderProPage.close();

  // --- Ladder, no-depth (Basic Plan) runner ---
  const ladderBasicPage = await freshDemoPage("ladder-basic");
  await ladderBasicPage.waitForTimeout(1500);
  await selectRunner(ladderBasicPage, NO_DEPTH_SELECTION_ID);
  await ladderBasicPage.waitForTimeout(600);
  await ladderBasicPage.screenshot({ path: path.join(SNAP_DIR, `ladder-basic${suffix}.png`) });
  console.log(`Captured ladder-basic${suffix}.png`);
  expectedFiles.push(`ladder-basic${suffix}.png`);
  await ladderBasicPage.close();

  // --- Ladder tab tapped directly, nothing selected yet — the tab used to
  // be disabled in this state, which just looked broken; it must now show
  // the "pick a runner" placeholder instead of nothing ---
  const ladderEmptyPage = await freshDemoPage("ladder-empty");
  await ladderEmptyPage.waitForTimeout(1000);
  await ladderEmptyPage.click("text=Ladder");
  await ladderEmptyPage.waitForTimeout(300);
  await ladderEmptyPage.screenshot({ path: path.join(SNAP_DIR, `ladder-empty${suffix}.png`) });
  console.log(`Captured ladder-empty${suffix}.png`);
  expectedFiles.push(`ladder-empty${suffix}.png`);
  await ladderEmptyPage.close();

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
