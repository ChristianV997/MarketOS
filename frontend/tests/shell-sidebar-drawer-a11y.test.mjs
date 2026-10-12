import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import {
  DRAWER_MAX_WIDTH_PX,
  DRAWER_MEDIA_QUERY,
  NAV_TOGGLE_ID,
  OPERATOR_MAIN_ID,
  SIDEBAR_NAV_ID,
  SKIP_TO_MAIN_ID,
  isDrawerMode,
  mainContentBlocksKeyboardWhenDrawerOpen,
  mainContentIsInert,
  navigationToggleLabel,
  shouldCloseDrawerOnKey,
  shouldCloseDrawerOnRouteChange,
  shouldCloseDrawerOnSkip,
  sidebarIsInert,
} from "../src/components/layout/sidebarDrawer.ts";

const shellSrc = await readFile(new URL("../src/components/layout/Shell.tsx", import.meta.url), "utf8");
const sidebarSrc = await readFile(new URL("../src/components/layout/Sidebar.tsx", import.meta.url), "utf8");
const cssSrc = await readFile(new URL("../src/index.css", import.meta.url), "utf8");

test("drawer mode matches Tailwind md (767px and below)", () => {
  assert.equal(DRAWER_MAX_WIDTH_PX, 767);
  assert.equal(isDrawerMode(320), true);
  assert.equal(isDrawerMode(390), true);
  assert.equal(isDrawerMode(420), true);
  assert.equal(isDrawerMode(767), true);
  assert.equal(isDrawerMode(768), false);
  assert.equal(isDrawerMode(1280), false);
  assert.match(DRAWER_MEDIA_QUERY, /max-width: 767px/);
});

test("named toggle labels and expanded contract", () => {
  assert.equal(navigationToggleLabel(false), "Open navigation");
  assert.equal(navigationToggleLabel(true), "Close navigation");
  assert.match(shellSrc, /aria-label=\{toggleLabel\}/);
  assert.match(shellSrc, /aria-expanded=\{drawerMode \? navOpen : undefined\}/);
  assert.match(shellSrc, /aria-controls=\{SIDEBAR_NAV_ID\}/);
  assert.match(shellSrc, /type="button"/);
  assert.match(shellSrc, /id=\{NAV_TOGGLE_ID\}/);
  assert.match(shellSrc, /className="md:hidden inline-flex/);
  assert.equal(NAV_TOGGLE_ID, "operator-nav-toggle");
});

test("Escape closes only an open mobile drawer", () => {
  assert.equal(shouldCloseDrawerOnKey("Escape", { open: true, drawerMode: true }), true);
  assert.equal(shouldCloseDrawerOnKey("Escape", { open: false, drawerMode: true }), false);
  assert.equal(shouldCloseDrawerOnKey("Escape", { open: true, drawerMode: false }), false);
  assert.equal(shouldCloseDrawerOnKey("Enter", { open: true, drawerMode: true }), false);
  assert.match(shellSrc, /shouldCloseDrawerOnKey/);
  assert.match(shellSrc, /toggleRef\.current\?\.focus\(\)/);
});

test("closed mobile sidebar is inert; desktop is never inert", () => {
  assert.equal(sidebarIsInert(true, false), true);
  assert.equal(sidebarIsInert(true, true), false);
  assert.equal(sidebarIsInert(false, false), false);
  assert.match(sidebarSrc, /inert/);
  assert.match(sidebarSrc, /tabIndex=\{inert \? -1 : undefined\}/);
});

test("open mobile drawer inerts main content; desktop/tablet never do", () => {
  assert.equal(mainContentIsInert(true, true), true);
  assert.equal(mainContentIsInert(true, false), false);
  assert.equal(mainContentIsInert(false, true), false);
  assert.equal(mainContentIsInert(false, false), false);
  assert.equal(mainContentBlocksKeyboardWhenDrawerOpen(true, true), true);
  assert.equal(mainContentBlocksKeyboardWhenDrawerOpen(false, true), false);
  assert.equal(mainContentBlocksKeyboardWhenDrawerOpen(true, false), false);
  // Mirror the sidebar inert/hidden pattern on the main landmark only (header
  // toggle + scrim stay available for Tab / Shift+Tab / Escape / dismiss).
  assert.match(shellSrc, /mainContentIsInert/);
  assert.match(shellSrc, /mainInert/);
  assert.match(shellSrc, /aria-hidden=\{mainInert \|\| undefined\}/);
  assert.match(shellSrc, /\{\.\.\.\(mainInert \? \{ inert: "" \} : \{\}\)\}/);
  assert.match(shellSrc, /focusMainAfterDrawerClose/);
});

test("route changes close an open drawer and move focus to main", () => {
  assert.equal(shouldCloseDrawerOnRouteChange(true, true), true);
  assert.equal(shouldCloseDrawerOnRouteChange(true, false), false);
  assert.equal(shouldCloseDrawerOnRouteChange(false, true), false);
  assert.match(shellSrc, /location\.pathname/);
  assert.match(shellSrc, /setNavOpen\(false\)/);
  assert.match(shellSrc, /mainRef\.current\?\.focus\(\)/);
  assert.match(shellSrc, /firstRender/);
});

test("skip-to-main is the first focusable control and focuses the main landmark", () => {
  const shellOpen = shellSrc.indexOf("return (");
  const skipIdx = shellSrc.indexOf("Skip to main content", shellOpen);
  const sidebarIdx = shellSrc.indexOf("<Sidebar", shellOpen);
  const headerIdx = shellSrc.indexOf("<header", shellOpen);
  const mainIdx = shellSrc.indexOf("<main", shellOpen);
  assert.ok(skipIdx > 0 && sidebarIdx > skipIdx, "skip link precedes the sidebar rail in DOM order");
  assert.ok(headerIdx > skipIdx && mainIdx > skipIdx);
  assert.match(shellSrc, /relative flex h-screen/);
  assert.match(shellSrc, /absolute left-3 top-2/);
  assert.match(shellSrc, /z-\[70\]/);
  assert.match(shellSrc, /focus:opacity-100/);
  assert.doesNotMatch(shellSrc, /sr-only focus:not-sr-only/);
  assert.match(shellSrc, new RegExp(`id=\\{OPERATOR_MAIN_ID\\}|id="${OPERATOR_MAIN_ID}"`));
  assert.match(shellSrc, new RegExp(`id=\\{SKIP_TO_MAIN_ID\\}`));
  assert.equal(OPERATOR_MAIN_ID, "operator-main");
  assert.equal(SKIP_TO_MAIN_ID, "operator-skip-to-main");
  assert.equal(SIDEBAR_NAV_ID, "operator-sidebar-nav");
  assert.equal(shouldCloseDrawerOnSkip(true, true), true);
  assert.equal(shouldCloseDrawerOnSkip(true, false), false);
  assert.match(shellSrc, /onClick=\{activateSkipToMain\}/);
  assert.match(shellSrc, /shouldCloseDrawerOnSkip/);
  assert.match(shellSrc, /mainRef\.current\?\.focus\(\)/);
  const skipHandlerStart = shellSrc.indexOf("const activateSkipToMain");
  const skipHandlerEnd = shellSrc.indexOf("return (", skipHandlerStart);
  assert.ok(skipHandlerStart >= 0 && skipHandlerEnd > skipHandlerStart);
  assert.doesNotMatch(shellSrc.slice(skipHandlerStart, skipHandlerEnd), /event\.preventDefault\(\)/);
  assert.match(shellSrc, /aria-label="Operator workspace"/);
  assert.match(shellSrc, /tabIndex=\{-1\}/);
});

test("desktop keyboard users can skip the persistent rail before any nav link", () => {
  // Contract lock: the rail remains in the accessibility tree on md+, so the
  // skip control must appear before <Sidebar> or Tab still walks every link.
  const body = shellSrc.slice(shellSrc.indexOf("return ("));
  assert.match(body, /Skip to main content[\s\S]*<Sidebar/);
  assert.doesNotMatch(body, /<Sidebar[\s\S]*Skip to main content/);
});

test("operator nav landmark has an accessible name and visible focus rings", () => {
  assert.match(sidebarSrc, /aria-label="Operator"/);
  assert.match(sidebarSrc, /id=\{SIDEBAR_NAV_ID\}/);
  assert.match(sidebarSrc, /focus-visible:outline/);
  assert.match(sidebarSrc, /aria-hidden="true"/);
  assert.equal((sidebarSrc.match(/<nav\b/g) ?? []).length, 1);
  assert.match(sidebarSrc, /\/operator\/research/);
  assert.match(sidebarSrc, /\/client\/profile/);
});

test("narrow overlay leaves the live-status header above the scrim", () => {
  assert.match(shellSrc, /<div className="relative flex-1 flex flex-col/);
  assert.doesNotMatch(shellSrc, /<div className="relative z-50 flex-1 flex flex-col/);
  assert.match(shellSrc, /<header className="relative z-50/);
  assert.match(shellSrc, /NAV_SCRIM_ID/);
  assert.match(shellSrc, /top-12/);
  assert.match(shellSrc, /Dismiss navigation/);
  assert.match(sidebarSrc, /max-md:top-12/);
  assert.match(sidebarSrc, /max-md:-translate-x-full/);
  assert.match(sidebarSrc, /md:static/);
  assert.match(shellSrc, /reconnecting/);
  assert.match(shellSrc, /ROAS/);
  assert.match(shellSrc, /min-w-0 flex-1 overflow-auto/);
  assert.match(shellSrc, /overflow-x-auto/);
  assert.match(shellSrc, /role="status"/);
  assert.match(shellSrc, /aria-live="polite"/);
});

test("drawer uses inert boundary instead of a focus-trap dependency", () => {
  assert.doesNotMatch(shellSrc, /focus-trap|focusTrap|trapFocus|focus-trap-react/);
  assert.doesNotMatch(sidebarSrc, /focus-trap|focusTrap|trapFocus|focus-trap-react/);
  assert.match(shellSrc, /mainContentIsInert/);
  assert.match(shellSrc, /inert: ""/);
});

test("Tab and Shift+Tab cannot reach main controls while the mobile drawer is open", () => {
  // Contract: open drawer => main inert/aria-hidden; closed or md+ => main available.
  assert.equal(mainContentBlocksKeyboardWhenDrawerOpen(true, true), true);
  assert.equal(mainContentBlocksKeyboardWhenDrawerOpen(true, false), false);
  assert.equal(mainContentBlocksKeyboardWhenDrawerOpen(false, false), false);
  assert.equal(mainContentBlocksKeyboardWhenDrawerOpen(false, true), false);
  // Shell wires the helper onto <main>, not the header chrome (toggle stays in tab order).
  const mainBlock = shellSrc.slice(shellSrc.indexOf("<main"), shellSrc.indexOf("</main>") + 7);
  assert.match(mainBlock, /mainInert/);
  assert.match(mainBlock, /inert/);
  assert.match(mainBlock, /aria-hidden/);
  assert.match(shellSrc, /id=\{NAV_TOGGLE_ID\}/);
  assert.match(shellSrc, /NAV_SCRIM_ID/);
  // Escape + scrim still restore focus to the toggle (not stranded in main).
  assert.match(shellSrc, /toggleRef\.current\?\.focus\(\)/);
  assert.match(shellSrc, /Dismiss navigation/);
  assert.match(shellSrc, /shouldCloseDrawerOnKey/);
});

test("desktop and tablet persistent rail never inerts main content", () => {
  assert.equal(isDrawerMode(768), false);
  assert.equal(isDrawerMode(820), false);
  assert.equal(isDrawerMode(1280), false);
  assert.equal(mainContentIsInert(false, true), false);
  assert.equal(mainContentIsInert(false, false), false);
  assert.match(shellSrc, /className="md:hidden inline-flex/);
  assert.match(sidebarSrc, /md:static md:z-auto md:translate-x-0/);
  assert.match(sidebarSrc, /md:static/);
});

test("reduced-motion remains global; drawer adds no uncapped animation", () => {
  assert.match(cssSrc, /prefers-reduced-motion/);
  assert.match(sidebarSrc, /max-md:duration-200/);
});

test("shell remains GET-only: no mutation fetch or provider authority", () => {
  assert.doesNotMatch(shellSrc, /method:\s*["']POST["']/);
  assert.doesNotMatch(sidebarSrc, /method:\s*["']POST["']/);
  assert.doesNotMatch(shellSrc, /createOrder|placeOrder|publish|sendMessage|adSpend/);
  assert.match(sidebarSrc, /\/operator\/services/);
  assert.match(sidebarSrc, /\/operator\/first-phase/);
  assert.match(sidebarSrc, /\/operator\/research/);
  assert.match(sidebarSrc, /\/client\/profile/);
});

test("exactly one main and one header landmark in the operator shell", () => {
  assert.equal((shellSrc.match(/<main\b/g) ?? []).length, 1);
  assert.equal((shellSrc.match(/<header\b/g) ?? []).length, 1);
});
