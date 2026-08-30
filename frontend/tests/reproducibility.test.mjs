import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const packageJson = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
const lockJson = JSON.parse(await readFile(new URL("../package-lock.json", import.meta.url), "utf8"));
const apiSource = await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const apiBaseSource = await readFile(new URL("../src/lib/apiBase.ts", import.meta.url), "utf8");
const eventsSource = await readFile(new URL("../src/lib/canonicalEventsApi.ts", import.meta.url), "utf8");
const wsSource = await readFile(new URL("../src/hooks/useWebSocket.ts", import.meta.url), "utf8");
const viteSource = await readFile(new URL("../vite.config.ts", import.meta.url), "utf8");

test("package scripts and lockfile are deterministic", () => {
  assert.deepEqual(Object.keys(packageJson.scripts), ["dev", "typecheck", "test", "build", "preview"]);
  assert.equal(lockJson.lockfileVersion, 3);
  assert.deepEqual(lockJson.packages[""].dependencies, packageJson.dependencies);
  assert.deepEqual(lockJson.packages[""].devDependencies, packageJson.devDependencies);
});

test("frontend commands do not install, publish, or activate providers", () => {
  const scripts = Object.values(packageJson.scripts).join(" ").toLowerCase();
  for (const marker of ["curl", "wget", "npm install", "pnpm install", "publish", "docker", "ssh"]) {
    assert.equal(scripts.includes(marker), false, `unsafe package script marker: ${marker}`);
  }
});

test("API helpers share base-url resolution and fail closed on non-OK responses", () => {
  assert.match(apiBaseSource, /VITE_API_BASE_URL/);
  assert.match(apiBaseSource, /VITE_API_URL/);
  assert.match(apiSource, /resolveApiBaseUrl/);
  assert.match(apiSource, /joinApiPath/);
  assert.match(apiSource, /if \(!r\.ok\) throw new Error\(`\$\{r\.status\} \$\{path\}`\)/);
  assert.match(eventsSource, /Unable to load operator events/);
  assert.match(eventsSource, /method: "GET"/);
});

test("websocket hook reconnects and ignores malformed frames", () => {
  assert.match(wsSource, /RECONNECT_MS/);
  assert.match(wsSource, /MAX_RECONNECT_ATTEMPTS/);
  assert.match(wsSource, /attemptsRef\.current >= MAX_RECONNECT_ATTEMPTS/);
  assert.match(wsSource, /attemptsRef\.current = 0/);
  assert.match(wsSource, /malformed frames are ignored/);
  assert.match(wsSource, /\/ws/);
  assert.match(wsSource, /reconnectTimerRef/);
  assert.match(wsSource, /clearReconnectTimer/);
  assert.match(wsSource, /activeRef\.current = false/);
});

test("vite dev proxy forwards backend root routes and websocket path", () => {
  assert.match(viteSource, /BACKEND_ROOT_PROXY/);
  assert.match(viteSource, /metrics\|snapshot/);
  assert.match(viteSource, /"\/api"/);
  assert.match(viteSource, /"\/ws"/);
});
