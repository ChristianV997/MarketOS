#!/usr/bin/env node
/**
 * Loopback Chrome CDP probe for the operator-journey fixture harness.
 * Prints sanitized JSON only. Does not install browsers or write secrets.
 *
 * Usage: node operator_browser_cdp_probe.mjs <plan.json>
 * plan: { chrome, urls: string[], artifactDir, reducedMotion: bool }
 */
import { spawn } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { setTimeout as sleep } from "node:timers/promises";

const plan = JSON.parse(await readFile(process.argv[2], "utf8"));
const port = 9333 + Math.floor(Math.random() * 200);
const userData = `/tmp/marketos-cdp-${Date.now()}`;
const chrome = spawn(
  plan.chrome,
  [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--disable-extensions",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${userData}`,
    "about:blank",
  ],
  { stdio: "ignore" },
);

async function waitJson(url) {
  for (let i = 0; i < 40; i++) {
    try {
      const res = await fetch(url);
      if (res.ok) return await res.json();
    } catch {
      /* retry */
    }
    await sleep(150);
  }
  throw new Error("cdp_timeout");
}

class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(JSON.stringify(msg.error)));
        else resolve(msg.result);
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }
  async eval(expression) {
    const result = await this.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    return result.result?.value;
  }
}

const SNAP = `(() => ({
  surface: document.getElementById("status-banner")?.dataset?.surface || null,
  banner: (document.getElementById("status-banner")?.textContent || "").slice(0, 240),
  requests: (window.__mosRequests || []).map((item) => ({ method: item.method, url: String(item.url).slice(0, 180) })),
  hasSkip: !!document.getElementById("skip-link"),
  skipText: (document.getElementById("skip-link")?.textContent || "").trim().slice(0, 80),
  viewport: document.getElementById("viewport-label")?.textContent || "",
  width: window.innerWidth,
  overflowX: document.documentElement.scrollWidth - window.innerWidth,
  evidence: window.__mosAcceptance?.evidence || [],
  claimsLive: /evidence class:\\s*live_validated/i.test(document.body.innerText),
  liveText: (document.querySelector('[aria-live="polite"]')?.textContent || "").trim().slice(0, 240),
  motion: getComputedStyle(document.body).transitionDuration,
  tableOverflow: (() => {
    const scroller = document.querySelector(".table-scroll");
    if (!scroller) return null;
    return scroller.scrollWidth - scroller.clientWidth;
  })(),
}))()`;

const results = [];
try {
  await mkdir(plan.artifactDir, { recursive: true });
  await waitJson(`http://127.0.0.1:${port}/json/version`);
  const pages = await waitJson(`http://127.0.0.1:${port}/json/list`);
  const page = pages.find((item) => item.type === "page") || pages[0];
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve);
    ws.addEventListener("error", reject);
  });
  const cdp = new Cdp(ws);
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  if (plan.reducedMotion) {
    await cdp.send("Emulation.setEmulatedMedia", {
      features: [{ name: "prefers-reduced-motion", value: "reduce" }],
    });
  }
  for (const item of plan.urls) {
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: item.width || 1440,
      height: item.height || 900,
      deviceScaleFactor: 1,
      mobile: (item.width || 1440) < 768,
    });
    await cdp.send("Page.navigate", { url: item.url });
    await sleep(700);
    const snap = await cdp.eval(SNAP);
    let tabOrder = null;
    if (item.keyboard) {
      tabOrder = [];
      for (let i = 0; i < 3; i++) {
        await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
        await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
        await sleep(40);
        tabOrder.push(await cdp.eval(`(document.activeElement?.id || document.activeElement?.textContent || "").trim().slice(0, 80)`));
      }
    }
    let shot = null;
    if (item.screenshot) {
      const captured = await cdp.send("Page.captureScreenshot", { format: "png" });
      shot = `${plan.artifactDir}/${item.label}.png`;
      await writeFile(shot, Buffer.from(captured.data, "base64"));
    }
    let deep = null;
    if (item.deep) {
      await cdp.eval(`document.getElementById("svc-export")?.click()`);
      await sleep(80);
      deep = await cdp.eval(`(() => {
        const preview = document.getElementById("svc-export-preview");
        const text = (preview?.textContent || "").trim().slice(0, 240);
        const row = document.querySelector("#svc-rows tr");
        row?.focus();
        const focusedRow = document.activeElement?.dataset?.id || null;
        document.getElementById("svc-filter")?.focus();
        return {
          exportText: text,
          exportVisible: preview ? !preview.classList.contains("hidden") : false,
          focusedRow,
          focusReturnedTo: document.activeElement?.id || null,
          liveText: (document.getElementById("status-banner")?.textContent || "").trim().slice(0, 240),
          motion: getComputedStyle(document.body).transitionDuration,
          tableOverflow: (() => {
            const scroller = document.querySelector(".table-scroll");
            return scroller ? scroller.scrollWidth - scroller.clientWidth : null;
          })(),
          evidenceLabel: "fixture_browser_tested",
        };
      })()`);
    }
    results.push({ url: item.url, label: item.label, snap, tabOrder, screenshot: shot, deep });
  }
  ws.close();
  process.stdout.write(JSON.stringify({ ok: true, browser: "chrome-cdp", results }));
} catch (error) {
  process.stdout.write(JSON.stringify({ ok: false, reason: String(error?.message || error), results }));
  process.exitCode = 0;
} finally {
  chrome.kill("SIGTERM");
}
