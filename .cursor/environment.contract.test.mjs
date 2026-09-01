import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { access } from "node:fs/promises";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const envJson = JSON.parse(await readFile(new URL("./environment.json", import.meta.url), "utf8"));
const installSh = await readFile(new URL("./install.sh", import.meta.url), "utf8");
const validateSh = await readFile(new URL("./validate.sh", import.meta.url), "utf8");
const installPs1 = await readFile(new URL("./install.ps1", import.meta.url), "utf8");
const validatePs1 = await readFile(new URL("./validate.ps1", import.meta.url), "utf8");
const bootstrapDoc = await readFile(new URL("./BOOTSTRAP.md", import.meta.url), "utf8");
const gitattributes = await readFile(new URL("../.gitattributes", import.meta.url), "utf8");

const shellScripts = [
  ["install.sh", installSh],
  ["validate.sh", validateSh],
];

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

test("install.ps1 stays lockfile-only and avoids privileged bootstrap", () => {
  assert.doesNotMatch(installPs1, /sudo /);
  assert.doesNotMatch(installPs1, /apt-get install/);
  assert.doesNotMatch(installPs1, /npm install/);
  assert.match(installPs1, /ci --ignore-scripts --no-audit --no-fund/);
  assert.match(installPs1, /ensurepip is unavailable/);
  assert.match(installPs1, /validate\.ps1/);
});

test("shell scripts remain LF-only in the repository contract", () => {
  for (const [name, source] of shellScripts) {
    assert.doesNotMatch(source, /\r/, `${name} must not contain CRLF (breaks bash pipefail)`);
  }
});

test("CRLF shell scripts fail bash before contract logic runs", () => {
  const dir = mkdtempSync(join(tmpdir(), "cursor-crlf-"));
  const script = join(dir, "validate.sh");
  writeFileSync(script, validateSh.replace(/\n/g, "\r\n"));
  assert.throws(
    () => execFileSync("bash", [script], { encoding: "utf8" }),
    (error) => /pipefail|invalid option/.test(String(error.stderr ?? error.message)),
  );
});

test("validate.sh delegates to node contract tests without bash heredocs", () => {
  assert.doesNotMatch(validateSh, /<<['"]?[A-Z_]+/);
  assert.match(validateSh, /node --test \.cursor\/environment\.contract\.test\.mjs/);
  assert.match(validateSh, /node is unavailable in this environment/);
  assert.match(validateSh, /CRLF line endings/);
});

test(".gitattributes enforces LF for Cursor shell and contract files", () => {
  assert.match(gitattributes, /\.cursor\/\*\.sh text eol=lf/);
  assert.match(gitattributes, /\.cursor\/\*\.mjs text eol=lf/);
  assert.match(gitattributes, /\.cursor\/\*\.json text eol=lf/);
});

test("frontend lockfile exists for reproducible bootstrap", async () => {
  await access(new URL("../frontend/package-lock.json", import.meta.url));
});

test("Windows bootstrap validates through PowerShell contract script", () => {
  assert.match(installPs1, /validate\.ps1/);
  assert.match(validatePs1, /--test \(Join-Path \$repoRoot "\.cursor\\environment\.contract\.test\.mjs"\)/);
  assert.match(validatePs1, /CRLF line endings/);
  assert.match(validatePs1, /node is unavailable in this environment/);
  assert.match(validatePs1, /exit 127/);
});

test("bootstrap documents Windows and contributor validation commands", () => {
  assert.match(bootstrapDoc, /install\.ps1/);
  assert.match(bootstrapDoc, /validate\.ps1/);
  assert.match(bootstrapDoc, /validate\.sh/);
  assert.match(bootstrapDoc, /environment\.contract\.test\.mjs/);
  assert.match(bootstrapDoc, /npm ci --ignore-scripts --no-audit --no-fund/);
  assert.match(bootstrapDoc, /CRLF/);
  assert.match(bootstrapDoc, /\.gitattributes/);
});
