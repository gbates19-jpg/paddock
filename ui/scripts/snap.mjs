// Visual verification without the Claude-in-Chrome extension: starts the
// dev server, opens ?demo=1, captures a screenshot of each scene (Floor,
// Paddock, Ladder on a depth-having runner, Ladder on a no-depth runner)
// plus a short webm of the Floor, and fails the whole run if the page
// logged any console error or uncaught exception along the way.
//
// Scene/runner navigation goes through window.__paddockStore (see
// src/main.tsx, dev-only) rather than clicking canvas coordinates —
// PixiJS scenes have no stable DOM to select against, and pixel
// coordinates would be fragile against window size / live price
// movement. Only the Paddock tab button is a real DOM click, since
// that's an actual button.

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

  try {
    await waitForServer(BASE_URL, 20_000);
    console.log("Dev server is up.");

    const browser = await chromium.launch();

    // --- Floor: recorded as a 10s webm, screenshot taken partway through ---
    const floorContext = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      recordVideo: { dir: SNAP_DIR, size: { width: 1280, height: 800 } },
    });
    const floorPage = await floorContext.newPage();
    attachErrorCollectors(floorPage, consoleErrors, "floor");

    await floorPage.goto(`${BASE_URL}/?demo=1`, { waitUntil: "load" });
    await floorPage.waitForSelector("canvas", { timeout: 10_000 });
    await floorPage.waitForTimeout(3000);
    await floorPage.screenshot({ path: path.join(SNAP_DIR, "floor.png") });
    console.log("Captured floor.png");

    // keep recording for a full 10s total
    await floorPage.waitForTimeout(7000);
    const floorVideo = floorPage.video();
    await floorContext.close();
    if (floorVideo) {
      const savedPath = await floorVideo.path();
      renameSync(savedPath, path.join(SNAP_DIR, "floor.webm"));
      console.log("Captured floor.webm");
    }

    // --- Paddock + Ladder (pro depth, and no-depth) ---
    // Each capture gets its OWN fresh page load rather than sharing one
    // long-lived session: the demo stream loops and closes its market
    // ~9s in, and a shared session accumulates wait time across steps —
    // found this the hard way, the second Ladder capture landed after
    // the demo market had already closed and showed the "#4" selection-id
    // fallback instead of the runner's name.
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });

    async function freshDemoPage() {
      const page = await context.newPage();
      attachErrorCollectors(page, consoleErrors, "paddock/ladder");
      await page.goto(`${BASE_URL}/?demo=1`, { waitUntil: "load" });
      await page.waitForSelector("canvas", { timeout: 10_000 });
      return page;
    }

    const paddockPage = await freshDemoPage();
    await paddockPage.click("text=THE PADDOCK");
    await paddockPage.waitForTimeout(3000);
    await paddockPage.screenshot({ path: path.join(SNAP_DIR, "paddock.png") });
    console.log("Captured paddock.png");
    await paddockPage.close();

    const ladderProPage = await freshDemoPage();
    await ladderProPage.waitForTimeout(1000); // let market.open (fires at t=500ms) land first
    await ladderProPage.evaluate(() => {
      // @ts-expect-error dev-only hook, see src/main.tsx
      window.__paddockStore.getState().selectRunner("1.999999", 1); // depth-having runner
    });
    await ladderProPage.waitForTimeout(3000);
    await ladderProPage.screenshot({ path: path.join(SNAP_DIR, "ladder-pro.png") });
    console.log("Captured ladder-pro.png");
    await ladderProPage.close();

    const ladderBasicPage = await freshDemoPage();
    await ladderBasicPage.waitForTimeout(1000); // let market.open (fires at t=500ms) land first
    await ladderBasicPage.evaluate(() => {
      // @ts-expect-error dev-only hook, see src/main.tsx
      window.__paddockStore.getState().selectRunner("1.999999", 4); // no-depth runner
    });
    await ladderBasicPage.waitForTimeout(3000);
    await ladderBasicPage.screenshot({ path: path.join(SNAP_DIR, "ladder-basic.png") });
    console.log("Captured ladder-basic.png");
    await ladderBasicPage.close();

    await context.close();
    await browser.close();
  } finally {
    devServer.kill();
  }

  if (consoleErrors.length > 0) {
    console.error(`\n${consoleErrors.length} console error(s)/page error(s) during the run:`);
    for (const e of consoleErrors) console.error(`  [${e.scene}] ${e.text}`);
    process.exit(1);
  }

  for (const name of ["floor.png", "floor.webm", "paddock.png", "ladder-pro.png", "ladder-basic.png"]) {
    if (!existsSync(path.join(SNAP_DIR, name))) {
      console.error(`Expected output missing: ${name}`);
      process.exit(1);
    }
  }

  console.log("\nAll snapshots captured, no console errors.");
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

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
