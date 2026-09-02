import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const apiBaseSource = await readFile(new URL("../src/lib/apiBase.ts", import.meta.url), "utf8");
const headerSource = await readFile(new URL("../src/components/PhaseHeader.tsx", import.meta.url), "utf8");

test("backend-unavailable UI does not claim live connectivity", () => {
  assert.match(headerSource, /connected \? "live" : "reconnecting"/);
  assert.match(headerSource, /reconnecting/);
});

test("api base helper preserves empty default for same-origin dev proxy", () => {
  assert.match(apiBaseSource, /return base\.replace\(\/\\\/\$\/, ""\)/);
  assert.match(apiBaseSource, /\?\? ""/);
});

/** Facsimile of apiBase.ts helpers for executable normalization checks. */
function resolveApiBaseUrl(baseUrl, legacyUrl) {
  const base = baseUrl ?? legacyUrl ?? "";
  return base.replace(/\/$/, "");
}

function joinApiPath(baseUrl, path) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${baseUrl}${normalizedPath}`;
}

test("api base URL normalization is deterministic", () => {
  assert.equal(resolveApiBaseUrl(undefined, undefined), "");
  assert.equal(resolveApiBaseUrl("https://api.example.com/", undefined), "https://api.example.com");
  assert.equal(resolveApiBaseUrl(undefined, "https://legacy.example.com/"), "https://legacy.example.com");
  assert.equal(
    resolveApiBaseUrl("https://primary.example.com/", "https://legacy.example.com/"),
    "https://primary.example.com",
  );
  assert.equal(joinApiPath("", "/metrics"), "/metrics");
  assert.equal(joinApiPath("https://api.example.com", "metrics"), "https://api.example.com/metrics");
  assert.equal(joinApiPath("https://api.example.com", "/api/events/readiness"), "https://api.example.com/api/events/readiness");
});

test("api base source honors VITE_API_BASE_URL before VITE_API_URL", () => {
  const primary = apiBaseSource.indexOf("VITE_API_BASE_URL");
  const legacy = apiBaseSource.indexOf("VITE_API_URL");
  assert.ok(primary >= 0 && legacy > primary);
});

test("canonical and dashboard clients do not embed provider credentials", async () => {
  const forbidden = ["sk-live-", "ghp_", "SHOPIFY_ACCESS_TOKEN", "STRIPE_SECRET_KEY"];
  for (const path of ["../src/lib/api.ts", "../src/lib/canonicalEventsApi.ts", "../src/hooks/useWebSocket.ts"]) {
    const source = await readFile(new URL(path, import.meta.url), "utf8");
    for (const token of forbidden) {
      assert.equal(source.includes(token), false, `${path} must not embed ${token}`);
    }
  }
});
