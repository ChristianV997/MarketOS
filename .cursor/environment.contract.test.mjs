import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const envJson = JSON.parse(await readFile(new URL("./environment.json", import.meta.url), "utf8"));
const installSh = await readFile(new URL("./install.sh", import.meta.url), "utf8");
const bootstrapDoc = await readFile(new URL("./BOOTSTRAP.md", import.meta.url), "utf8");

test("environment.json declares bounded localhost dev terminals", () => {
  assert.equal(envJson.install, "bash .cursor/install.sh");
  assert.equal(envJson.terminals.length, 2);
  for (const terminal of envJson.terminals) {
    assert.match(terminal.command, /127\.0\.0\.1/);
    assert.doesNotMatch(terminal.command, /0\.0\.0\.0/);
  }
});

test("install.sh stays lockfile-only and avoids privileged bootstrap", () => {
  assert.doesNotMatch(installSh, /sudo /);
  assert.doesNotMatch(installSh, /apt-get install/);
  assert.doesNotMatch(installSh, /npm install/);
  assert.match(installSh, /npm --prefix frontend ci --ignore-scripts --no-audit --no-fund/);
  assert.match(installSh, /ensurepip is unavailable/);
});

test("bootstrap documents Windows and contributor validation commands", () => {
  assert.match(bootstrapDoc, /install\.ps1/);
  assert.match(bootstrapDoc, /validate\.sh/);
  assert.match(bootstrapDoc, /environment\.contract\.test\.mjs/);
  assert.match(bootstrapDoc, /npm ci --ignore-scripts --no-audit --no-fund/);
});
