import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const packageJson = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
const lockJson = JSON.parse(await readFile(new URL("../package-lock.json", import.meta.url), "utf8"));
const apiSource = await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8");

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

test("API helpers fail closed when the backend is unavailable", () => {
  assert.match(apiSource, /if \(!r\.ok\) throw new Error\(\`\$\{r\.status\} \$\{path\}\`\)/g);
  assert.match(apiSource, /const BASE = .*\?\? "";/);
  assert.match(apiSource, /const r = await fetch\(/g);
});
