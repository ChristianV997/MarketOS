import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const srcRoot = path.resolve(__dirname, "../src");

test("integration: main router mounts operator research portfolio and isolated client CRM shell", async () => {
  const mainSource = await readFile(path.join(srcRoot, "main.tsx"), "utf8");

  // Operator routes mounted inside Shell
  assert.match(mainSource, /import\s+OwnerResearchPortfolioPage\s+from\s+["']\.\/features\/owner-research-portfolio\/OwnerResearchPortfolioPage["']/);
  assert.match(mainSource, /path:\s*["']\/operator\/research["'],\s*element:\s*<OwnerResearchPortfolioPage\s*\/>/);
  assert.match(mainSource, /path:\s*["']\/research["'],\s*element:\s*<OwnerResearchPortfolioPage\s*\/>/);

  // Client routes mounted inside ClientShell
  assert.match(mainSource, /import\s+ClientShell\s+from\s+["']\.\/components\/layout\/ClientShell["']/);
  assert.match(mainSource, /import\s+ClientProfileOnboardingPage\s+from\s+["']\.\/features\/client-crm-profile\/ClientProfileOnboardingPage["']/);
  assert.match(mainSource, /element:\s*<ClientShell\s*\/>/);
  assert.match(mainSource, /path:\s*["']\/client\/profile["'],\s*element:\s*<ClientProfileOnboardingPage\s*\/>/);
  assert.match(mainSource, /path:\s*["']\/crm["'],\s*element:\s*<ClientProfileOnboardingPage\s*\/>/);
});

test("integration: sidebar exposes accessible navigation for operator dashboard, research, and client CRM", async () => {
  const sidebarSource = await readFile(path.join(srcRoot, "components/layout/Sidebar.tsx"), "utf8");

  assert.match(sidebarSource, /to:\s*["']\/["'],\s*icon:\s*LayoutDashboard,\s*label:\s*["']Dashboard["']/);
  assert.match(sidebarSource, /to:\s*["']\/operator\/research["'],\s*icon:\s*ListOrdered,\s*label:\s*["']Research Portfolio["']/);
  assert.match(sidebarSource, /to:\s*["']\/operator\/services["'],\s*icon:\s*ClipboardList,\s*label:\s*["']Service Workbench["']/);
  assert.match(sidebarSource, /to:\s*["']\/client\/profile["'],\s*icon:\s*UserCheck,\s*label:\s*["']Client CRM["']/);
});

test("tenant isolation: ClientShell never imports operator stores, metrics, or WebSocket", async () => {
  const clientShellSource = await readFile(path.join(srcRoot, "components/layout/ClientShell.tsx"), "utf8");

  // Must provide landmark
  assert.match(clientShellSource, /<main\b[^>]*>/);

  // Must NOT import operator stores or sockets
  assert.doesNotMatch(clientShellSource, /useWsStore/);
  assert.doesNotMatch(clientShellSource, /useRuntimeStore/);
  assert.doesNotMatch(clientShellSource, /useMetrics/);
  assert.doesNotMatch(clientShellSource, /useWebSocket/);
  assert.doesNotMatch(clientShellSource, /useSnapshot/);
  assert.doesNotMatch(clientShellSource, /usePlaybook/);
});

test("truthful UI: owner research and client CRM do not share selectors or fallback tenants", async () => {
  const ownerIndex = await readFile(path.join(srcRoot, "features/owner-research-portfolio/index.ts"), "utf8");
  const clientIndex = await readFile(path.join(srcRoot, "features/client-crm-profile/index.ts"), "utf8");

  // Completely separate exports and contracts
  assert.match(ownerIndex, /OwnerResearchPortfolioPage/);
  assert.match(clientIndex, /ClientProfileOnboardingPage/);

  assert.doesNotMatch(ownerIndex, /client-crm-profile/);
  assert.doesNotMatch(clientIndex, /owner-research-portfolio/);
});

test("ClientShell makes no isolation claim, keeps a 44px operator link, and announces route changes", async () => {
  const shell = await readFile(path.join(srcRoot, "components/layout/ClientShell.tsx"), "utf8");
  const code = shell.replace(/\/\*[\s\S]*?\*\//g, "");

  // The server enforces isolation; a layout label must not claim it.
  assert.doesNotMatch(code, /Isolated|isolated/);
  assert.doesNotMatch(code, /Shield/);

  // No fixed-height header that overflows at 320px; the operator link is a 44px target.
  assert.doesNotMatch(code, /<header[^>]*(?<![\w-])h-12(?![\w-])/);
  assert.match(code, /<header[^>]*\bflex-wrap\b/);
  assert.match(code, /min-h-\[44px\][^"]*min-w-\[44px\]|min-w-\[44px\][^"]*min-h-\[44px\]/);

  // One landmark that can take programmatic focus, no extra padding around the page's own.
  assert.equal((code.match(/<main\b/g) ?? []).length, 1);
  assert.match(code, /<main[^>]*tabIndex=\{-1\}/);
  assert.doesNotMatch(code, /<main[^>]*\bp-[0-9]/);

  // Route change: focus moves to main after the first render, and the title is client-specific and restored.
  assert.match(code, /useLocation\(\)/);
  assert.match(code, /firstRender/);
  assert.match(code, /main\.current\?\.focus\(\)/);
  assert.match(code, /document\.title = CLIENT_TITLE/);
  assert.match(code, /document\.title = previous/);
});

test("ClientShell provides an initial keyboard-visible skip link targeting client main without duplicate landmarks", async () => {
  const shell = await readFile(path.join(srcRoot, "components/layout/ClientShell.tsx"), "utf8");
  const code = shell.replace(/\/\*[\s\S]*?\*\//g, "");

  // Skip link must exist, precede <header>, target #client-main, and have standard accessible text
  assert.match(code, /<a\b[^>]*href="#client-main"[^>]*>[\s\S]*?Skip to main content[\s\S]*?<\/a>\s*<header\b/);

  // Remains keyboard-visible via sr-only + focus:not-sr-only + focus:absolute
  assert.match(code, /sr-only\b/);
  assert.match(code, /focus:not-sr-only\b/);
  assert.match(code, /focus:absolute\b/);

  // Focus target is <main id="client-main" tabIndex={-1}>
  assert.match(code, /<main[^>]*id="client-main"[^>]*tabIndex=\{-1\}/);

  // No duplicate landmarks (skip link is not wrapped in <nav>, and only 1 main and 1 header exist)
  assert.equal((code.match(/<main\b/g) ?? []).length, 1, "exactly one main landmark");
  assert.equal((code.match(/<header\b/g) ?? []).length, 1, "exactly one header landmark");
  assert.equal((code.match(/<nav\b/g) ?? []).length, 1, "only the view switch nav landmark in shell chrome");
});

test("owner research and client CRM entries use different sidebar icons", async () => {
  const sidebarSource = await readFile(path.join(srcRoot, "components/layout/Sidebar.tsx"), "utf8");
  const icons = [...sidebarSource.matchAll(/to:\s*"([^"]+)",\s*icon:\s*(\w+)/g)].map((m) => [m[1], m[2]]);
  const research = icons.find(([to]) => to === "/operator/research")[1];
  const cockpit = icons.find(([to]) => to === "/operator/first-phase")[1];
  assert.notEqual(research, cockpit);
});
