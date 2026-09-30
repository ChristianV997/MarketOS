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
  assert.match(sidebarSource, /to:\s*["']\/operator\/research["'],\s*icon:\s*Telescope,\s*label:\s*["']Research Portfolio["']/);
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
