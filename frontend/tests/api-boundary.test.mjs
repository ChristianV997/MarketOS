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

test("canonical and dashboard clients do not embed provider credentials", async () => {
  const forbidden = ["sk-live-", "ghp_", "SHOPIFY_ACCESS_TOKEN", "STRIPE_SECRET_KEY"];
  for (const path of ["../src/lib/api.ts", "../src/lib/canonicalEventsApi.ts", "../src/hooks/useWebSocket.ts"]) {
    const source = await readFile(new URL(path, import.meta.url), "utf8");
    for (const token of forbidden) {
      assert.equal(source.includes(token), false, `${path} must not embed ${token}`);
    }
  }
});
