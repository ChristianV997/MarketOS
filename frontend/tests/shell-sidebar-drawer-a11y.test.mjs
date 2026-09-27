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
  assert.match(shellSrc, new RegExp(`id=\\{NAV_TOGGLE_ID\\}|id="${NAV_TOGGLE_ID}"`));
  assert.match(shellSrc, /type="button"/);
  assert.match(shellSrc, /id=\{NAV_TOGGLE_ID\}/);
  assert.match(shellSrc, /className="md:hidden inline-flex/);
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

test("route changes close an open drawer so the next page is not trapped", () => {
  assert.equal(shouldCloseDrawerOnRouteChange(true, true), true);
  assert.equal(shouldCloseDrawerOnRouteChange(true, false), false);
  assert.equal(shouldCloseDrawerOnRouteChange(false, true), false);
  assert.match(shellSrc, /location\.pathname/);
  assert.match(shellSrc, /setNavOpen\(false\)/);
});

test("skip-to-main is first useful tab stop below the live-status header", () => {
  const headerIdx = shellSrc.indexOf("<header");
  const headerEnd = shellSrc.indexOf("</header>");
  const skipIdx = shellSrc.indexOf("Skip to main content");
  const mainIdx = shellSrc.indexOf("<main");
  assert.ok(headerIdx > 0 && skipIdx > headerEnd && skipIdx < mainIdx);
  assert.match(shellSrc, /relative flex h-screen/);
  assert.match(shellSrc, /absolute left-3 top-14/);
  assert.match(shellSrc, /focus:opacity-100/);
  assert.doesNotMatch(shellSrc, /sr-only focus:not-sr-only/);
  assert.match(shellSrc, new RegExp(`id=\\{OPERATOR_MAIN_ID\\}|id="${OPERATOR_MAIN_ID}"`));
  assert.match(shellSrc, new RegExp(`id=\\{SKIP_TO_MAIN_ID\\}`));
  assert.equal(OPERATOR_MAIN_ID, "operator-main");
  assert.equal(SKIP_TO_MAIN_ID, "operator-skip-to-main");
  assert.equal(SIDEBAR_NAV_ID, "operator-sidebar-nav");
  assert.equal(shouldCloseDrawerOnSkip(true, true), true);
  assert.equal(shouldCloseDrawerOnSkip(true, false), false);
  assert.match(shellSrc, /onClick=\{closeDrawerFromSkip\}/);
  assert.match(shellSrc, /shouldCloseDrawerOnSkip/);
});

test("narrow overlay leaves the live-status header above the scrim", () => {
  assert.match(shellSrc, /<div className="relative flex-1 flex flex-col/);
  assert.doesNotMatch(shellSrc, /<div className="relative z-50 flex-1 flex flex-col/);
  assert.match(shellSrc, /<header className="relative z-50/);
  assert.match(shellSrc, /z-50/);
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
});

test("drawer does not install a focus trap", () => {
  assert.doesNotMatch(shellSrc, /focus-trap|focusTrap|trapFocus/);
  assert.doesNotMatch(sidebarSrc, /focus-trap|focusTrap|trapFocus/);
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
});
