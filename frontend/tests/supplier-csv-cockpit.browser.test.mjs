import { test, describe, before, after } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { setTimeout as sleep } from "node:timers/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { existsSync } from "node:fs";

const chromePaths = [
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  process.env.CHROME_BIN,
].filter(Boolean);

let chromeBin = chromePaths.find(p => existsSync(p));

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

async function waitJson(url) {
  for (let i = 0; i < 60; i++) {
    try {
      const res = await fetch(url);
      if (res.ok) return await res.json();
    } catch {}
    await sleep(250);
  }
  throw new Error("Timeout waiting for " + url);
}

test("Supplier CSV Preview - Browser Interaction", { skip: !chromeBin }, async (t) => {
  const VITE_PORT = 15000 + Math.floor(Math.random() * 1000);
  const CDP_PORT = 9000 + Math.floor(Math.random() * 1000);
  const CSV_PATH = join(tmpdir(), "test-catalog.csv");
  const BAD_CSV_PATH = join(tmpdir(), "bad-catalog.csv");

  // Write test CSVs
  await writeFile(CSV_PATH, "candidate_id,supplier_title,supplier,unit_cost,shipping_cost,currency\nc-123,Test Widget,manual,12.50,5.00,USD\n");
  await writeFile(BAD_CSV_PATH, "candidate_id,supplier_title,unit_cost\nc-999,InvalidRow,invalidcost\nc-999,DuplicateRow,1.00"); // Missing shipping, invalid cost, duplicate ID

  const frontendDir = existsSync(join(process.cwd(), "frontend", "package.json"))
    ? join(process.cwd(), "frontend")
    : process.cwd();
  const viteBin = join(frontendDir, "node_modules", "vite", "bin", "vite.js");

  // Start Vite dev server
  const viteProcess = spawn(process.execPath, [viteBin, "--port", VITE_PORT.toString(), "--strictPort", "--host", "127.0.0.1"], {
    cwd: frontendDir,
    stdio: "inherit"
  });

  t.after(() => {
    if (viteProcess && viteProcess.pid) {
      try {
        if (process.platform === "win32") {
          spawn("taskkill", ["/pid", viteProcess.pid.toString(), "/f", "/t"], { stdio: "ignore" });
        } else {
          viteProcess.kill("SIGKILL");
        }
      } catch {}
    }
  });

  // Wait for Vite to be ready
  let viteReady = false;
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${VITE_PORT}`);
      if (r.ok) { viteReady = true; break; }
    } catch {}
    await sleep(250);
  }
  if (!viteReady) throw new Error("Vite did not start");

  // Start Chrome
  const userData = join(tmpdir(), `cdp-test-${Date.now()}`);
  const chromeProcess = spawn(
    chromeBin,
    [
      "--headless=new",
      "--disable-gpu",
      "--no-first-run",
      "--disable-extensions",
      `--remote-debugging-port=${CDP_PORT}`,
      `--user-data-dir=${userData}`,
      "about:blank",
    ],
    { stdio: "ignore" }
  );

  t.after(() => {
    if (chromeProcess && chromeProcess.pid) {
      try {
        if (process.platform === "win32") {
          spawn("taskkill", ["/pid", chromeProcess.pid.toString(), "/f", "/t"], { stdio: "ignore" });
        } else {
          chromeProcess.kill("SIGKILL");
        }
      } catch {}
    }
  });

  await waitJson(`http://127.0.0.1:${CDP_PORT}/json/version`);
  const pages = await waitJson(`http://127.0.0.1:${CDP_PORT}/json/list`);
  const page = pages.find(p => p.type === "page") || pages[0];

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  t.after(() => {
    if (ws) ws.close();
  });

  await new Promise((res, rej) => {
    ws.addEventListener("open", res);
    ws.addEventListener("error", rej);
  });

  const cdp = new Cdp(ws);
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("DOM.enable");
  await cdp.send("Network.enable");

  const networkRequests = [];
  ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.method === "Network.requestWillBeSent") {
      networkRequests.push({ url: msg.params.request.url, method: msg.params.request.method });
    }
  });

  await t.test("Load cockpit, select file, verify parse output and selection constraints", async () => {
    await cdp.send("Page.navigate", { url: `http://127.0.0.1:${VITE_PORT}/operator/first-phase` });

    // Wait for page hydration
    await sleep(1000);

    // Wait for React to render the file input
    for (let i = 0; i < 40; i++) {
      const hasInput = await cdp.eval(`!!document.querySelector('input[type="file"]')`);
      if (hasInput) break;
      await sleep(200);
    }

    const preUploadRequestCount = networkRequests.length;

    // Set file input
    let doc = await cdp.send("DOM.getDocument", { depth: -1 });
    let fileInputNode = await cdp.send("DOM.querySelector", { nodeId: doc.root.nodeId, selector: 'input[type="file"]' });

    for (let i = 0; i < 20; i++) {
      if (fileInputNode.nodeId) break;
      await sleep(200);
      doc = await cdp.send("DOM.getDocument", { depth: -1 });
      fileInputNode = await cdp.send("DOM.querySelector", { nodeId: doc.root.nodeId, selector: 'input[type="file"]' });
    }

    assert.ok(fileInputNode.nodeId, "File input found");

    await cdp.send("DOM.setFileInputFiles", {
      files: [CSV_PATH],
      nodeId: fileInputNode.nodeId
    });

    // Wait for CSV preview to render
    for (let i = 0; i < 20; i++) {
      const hasTable = await cdp.eval(`!!document.querySelector('table[aria-label="Supplier Catalog CSV Preview"]')`);
      if (hasTable) break;
      await sleep(200);
    }

    const postUploadRequests = networkRequests.slice(preUploadRequestCount);
    const apiRequests = postUploadRequests.filter(req =>
      req.method !== "GET" || req.url.includes("/upload")
    );
    assert.strictEqual(apiRequests.length, 0, "Preview must remain local/draft-only, no upload requests allowed");

    // Verify row rendered correctly
    const rowContent = await cdp.eval(`document.querySelector('tbody tr td:nth-child(3)')?.textContent || ""`);
    assert.match(rowContent, /c-123/, "Candidate ID should be rendered");

    // Click the row
    await cdp.eval(`document.querySelector('tbody tr')?.click()`);
    await sleep(200);

    // Verify selection (should be selected because it's valid)
    const isSelected = await cdp.eval(`document.querySelector('tbody tr')?.classList.contains('bg-indigo-950/50')`);
    assert.ok(isSelected, "Valid row should be selectable");
  });

  await t.test("Invalid rows cannot be selected", async () => {
    // Clear preview
    await cdp.eval(`document.querySelector('button[aria-label="Clear CSV preview"]')?.click()`);
    await sleep(200);

    // Upload bad CSV
    let doc = await cdp.send("DOM.getDocument", { depth: -1 });
    let fileInputNode = await cdp.send("DOM.querySelector", { nodeId: doc.root.nodeId, selector: 'input[type="file"]' });

    for (let i = 0; i < 20; i++) {
      if (fileInputNode.nodeId) break;
      await sleep(200);
      doc = await cdp.send("DOM.getDocument", { depth: -1 });
      fileInputNode = await cdp.send("DOM.querySelector", { nodeId: doc.root.nodeId, selector: 'input[type="file"]' });
    }

    await cdp.send("DOM.setFileInputFiles", { files: [BAD_CSV_PATH], nodeId: fileInputNode.nodeId });

    for (let i = 0; i < 20; i++) {
      const hasIssues = await cdp.eval(`document.querySelector('tbody tr td:last-child')?.textContent || ""`);
      if (hasIssues.includes("malformed_unit_cost")) break;
      await sleep(200);
    }

    // Check validation errors are rendered
    const hasIssues = await cdp.eval(`document.querySelector('tbody tr td:last-child')?.textContent || ""`);
    assert.match(hasIssues, /malformed_unit_cost/, "Should show validation issues");

    // Verify invalid row is not interactive (no role="button", no tabindex="0")
    const invalidRole = await cdp.eval(`document.querySelector('tbody tr')?.getAttribute('role')`);
    const invalidTabIndex = await cdp.eval(`document.querySelector('tbody tr')?.getAttribute('tabindex')`);
    assert.strictEqual(invalidRole, null, "Invalid row must not have role='button'");
    assert.strictEqual(invalidTabIndex, null, "Invalid row must not have tabIndex");

    // Try clicking invalid row
    await cdp.eval(`document.querySelector('tbody tr')?.click()`);
    await sleep(200);

    // Verify it is NOT selected
    const isSelected = await cdp.eval(`document.querySelector('tbody tr')?.classList.contains('bg-indigo-950/50')`);
    assert.strictEqual(isSelected, false, "Invalid row must NOT become selected");

    // Try keyboard Enter on invalid row
    await cdp.eval(`
      const tr = document.querySelector('tbody tr');
      tr?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    `);
    await sleep(200);
    const isSelectedKey = await cdp.eval(`document.querySelector('tbody tr')?.classList.contains('bg-indigo-950/50')`);
    assert.strictEqual(isSelectedKey, false, "Invalid row must NOT become selected via keyboard");
  });

  await t.test("Valid rows support keyboard navigation with Enter key selection", async () => {
    // Clear preview
    await cdp.eval(`document.querySelector('button[aria-label="Clear CSV preview"]')?.click()`);
    await sleep(200);

    // Re-upload valid CSV
    let doc = await cdp.send("DOM.getDocument", { depth: -1 });
    let fileInputNode = await cdp.send("DOM.querySelector", { nodeId: doc.root.nodeId, selector: 'input[type="file"]' });
    await cdp.send("DOM.setFileInputFiles", { files: [CSV_PATH], nodeId: fileInputNode.nodeId });

    for (let i = 0; i < 20; i++) {
      const hasTable = await cdp.eval(`!!document.querySelector('table[aria-label="Supplier Catalog CSV Preview"]')`);
      if (hasTable) break;
      await sleep(200);
    }

    // Verify valid row has role="button" and tabindex="0"
    const validRole = await cdp.eval(`document.querySelector('tbody tr')?.getAttribute('role')`);
    const validTabIndex = await cdp.eval(`document.querySelector('tbody tr')?.getAttribute('tabindex')`);
    assert.strictEqual(validRole, "button", "Valid row must have role='button'");
    assert.strictEqual(validTabIndex, "0", "Valid row must have tabindex='0'");

    // Focus valid row and press Enter
    await cdp.eval(`
      const tr = document.querySelector('tbody tr');
      tr?.focus();
      tr?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    `);
    await sleep(200);

    // Verify row was selected
    const isSelected = await cdp.eval(`document.querySelector('tbody tr')?.classList.contains('bg-indigo-950/50')`);
    assert.ok(isSelected, "Valid row should be selected via Enter key");
  });
});
