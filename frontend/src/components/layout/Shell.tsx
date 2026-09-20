import { useCallback, useEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Menu, X } from "lucide-react";
import Sidebar from "./Sidebar";
import {
  DRAWER_MEDIA_QUERY,
  NAV_SCRIM_ID,
  NAV_TOGGLE_ID,
  OPERATOR_MAIN_ID,
  SIDEBAR_NAV_ID,
  isDrawerMode,
  navigationToggleLabel,
  shouldCloseDrawerOnKey,
} from "./sidebarDrawer";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useWsStore } from "@/store/ws";
import { useRuntimeStore } from "@/runtimeStore";
import { useSnapshot } from "@/lib/api";
import { cn } from "@/lib/utils";
import { capturePageview } from "@/lib/posthog";
import type { WsEvent } from "@/types";

const PHASE_COLORS: Record<string, string> = {
  RESEARCH: "bg-blue-500/10 text-blue-300 border-blue-500/20",
  EXPLORE:  "bg-amber-500/10 text-amber-300 border-amber-500/20",
  VALIDATE: "bg-orange-500/10 text-orange-300 border-orange-500/20",
  SCALE:    "bg-emerald-500/10 text-emerald-300 border-emerald-500/20",
};

function readDrawerMode(): boolean {
  if (typeof window === "undefined") return false;
  return isDrawerMode(window.innerWidth);
}

export default function Shell() {
  const location = useLocation();
  useEffect(() => {
    capturePageview(location.pathname); // no-op unless VITE_POSTHOG_KEY is set
  }, [location.pathname]);

  const handleMessage = useWsStore((s) => s.handleMessage);
  const appendRuntimeEvent = useRuntimeStore((s) => s.append);
  const onMessage = useCallback(
    (ev: WsEvent) => {
      handleMessage(ev);
      // ReplayInspector (the /replay page) reads from useRuntimeStore, the
      // same store the legacy tab-based app's useMetrics hook feeds — keep
      // both stores populated from this one websocket connection rather
      // than opening a second one.
      appendRuntimeEvent(ev as any);
    },
    [handleMessage, appendRuntimeEvent]
  );
  useWebSocket(onMessage);

  const connected = useWsStore((s) => s.connected);
  const wsSnap    = useWsStore((s) => s.snapshot);
  const { data: restSnap } = useSnapshot();

  const snap   = wsSnap ?? restSnap;
  const phase  = snap?.phase ?? "—";
  const cycles = snap?.total_cycles ?? 0;
  const roas   = snap?.avg_roas ?? 0;

  const [drawerMode, setDrawerMode] = useState(readDrawerMode);
  const [navOpen, setNavOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const media = window.matchMedia(DRAWER_MEDIA_QUERY);
    const sync = () => {
      const next = media.matches;
      setDrawerMode(next);
      if (!next) setNavOpen(false);
    };
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    setNavOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!navOpen || !drawerMode) return;
    const first = document.querySelector<HTMLElement>(`#${SIDEBAR_NAV_ID} a`);
    first?.focus();
  }, [navOpen, drawerMode]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!shouldCloseDrawerOnKey(event.key, { open: navOpen, drawerMode })) return;
      event.preventDefault();
      setNavOpen(false);
      toggleRef.current?.focus();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [navOpen, drawerMode]);

  const toggleLabel = navigationToggleLabel(navOpen);

  return (
    <div className="flex h-screen bg-[#0a0a0b] text-zinc-100 overflow-hidden">
      <a
        href={`#${OPERATOR_MAIN_ID}`}
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[60] focus:rounded focus:bg-zinc-900 focus:px-3 focus:py-2 focus:text-sm focus:text-zinc-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
      >
        Skip to main content
      </a>

      <Sidebar
        drawerMode={drawerMode}
        open={!drawerMode || navOpen}
        onNavigate={() => {
          if (drawerMode) setNavOpen(false);
        }}
      />

      {drawerMode && navOpen ? (
        <button
          id={NAV_SCRIM_ID}
          type="button"
          aria-label="Dismiss navigation"
          className="fixed top-12 inset-x-0 bottom-0 z-30 bg-black/50 md:hidden"
          onClick={() => {
            setNavOpen(false);
            toggleRef.current?.focus();
          }}
        />
      ) : null}

      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        <header className="relative z-50 h-12 shrink-0 flex items-center justify-between gap-2 px-3 md:px-5 border-b border-white/[0.06] bg-[#0d0d0f]">
          <div className="flex items-center gap-2 md:gap-3 min-w-0">
            <button
              ref={toggleRef}
              id={NAV_TOGGLE_ID}
              type="button"
              className="md:hidden inline-flex h-8 w-8 items-center justify-center rounded-md border border-white/[0.08] text-zinc-200 hover:bg-white/[0.04] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400"
              aria-controls={SIDEBAR_NAV_ID}
              aria-expanded={drawerMode ? navOpen : undefined}
              aria-label={toggleLabel}
              onClick={() => setNavOpen((value) => !value)}
            >
              {navOpen ? <X size={16} aria-hidden="true" /> : <Menu size={16} aria-hidden="true" />}
            </button>
            <span className="text-sm font-semibold tracking-tight text-zinc-100 md:hidden">
              Market<span className="text-indigo-400">OS</span>
            </span>
            <span
              className={cn(
                "text-[11px] font-medium px-2 py-0.5 rounded border shrink-0",
                PHASE_COLORS[phase] ?? "bg-zinc-800 text-zinc-400 border-zinc-700"
              )}
            >
              {phase}
            </span>
            <span className="hidden sm:inline text-xs text-zinc-400 font-mono">
              cycle <span className="text-zinc-300">{cycles.toLocaleString()}</span>
            </span>
            <span className="text-xs text-zinc-400 font-mono shrink-0">
              ROAS <span className={roas >= 1.2 ? "text-emerald-400" : "text-red-400"}>{roas.toFixed(2)}×</span>
            </span>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <span
              className={cn(
                "inline-block w-2 h-2 rounded-full",
                connected ? "bg-emerald-400 animate-pulse-slow" : "bg-red-500"
              )}
            />
            <span className="text-[11px] text-zinc-400">
              {connected ? "live" : "reconnecting"}
            </span>
          </div>
        </header>

        <main
          id={OPERATOR_MAIN_ID}
          tabIndex={-1}
          className="flex-1 overflow-auto outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
}
