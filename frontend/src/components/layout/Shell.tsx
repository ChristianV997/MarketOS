import { useCallback } from "react";
import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useWsStore } from "@/store/ws";
import { useRuntimeStore } from "@/runtimeStore";
import { useSnapshot } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { WsEvent } from "@/types";

const PHASE_COLORS: Record<string, string> = {
  RESEARCH: "bg-blue-500/10 text-blue-300 border-blue-500/20",
  EXPLORE:  "bg-amber-500/10 text-amber-300 border-amber-500/20",
  VALIDATE: "bg-orange-500/10 text-orange-300 border-orange-500/20",
  SCALE:    "bg-emerald-500/10 text-emerald-300 border-emerald-500/20",
};

export default function Shell() {
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

  return (
    <div className="flex h-screen bg-[#0a0a0b] text-zinc-100 overflow-hidden">
      <Sidebar />

      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        {/* Top bar */}
        <header className="h-12 shrink-0 flex items-center justify-between px-5 border-b border-white/[0.06] bg-[#0d0d0f]">
          <div className="flex items-center gap-3">
            {/* Phase badge */}
            <span
              className={cn(
                "text-[11px] font-medium px-2 py-0.5 rounded border",
                PHASE_COLORS[phase] ?? "bg-zinc-800 text-zinc-400 border-zinc-700"
              )}
            >
              {phase}
            </span>
            <span className="text-xs text-zinc-500 font-mono">
              cycle <span className="text-zinc-300">{cycles.toLocaleString()}</span>
            </span>
            <span className="text-xs text-zinc-500 font-mono">
              ROAS <span className={roas >= 1.2 ? "text-emerald-400" : "text-red-400"}>{roas.toFixed(2)}×</span>
            </span>
          </div>

          {/* Connection */}
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "inline-block w-2 h-2 rounded-full",
                connected ? "bg-emerald-400 animate-pulse-slow" : "bg-red-500"
              )}
            />
            <span className="text-[11px] text-zinc-500">
              {connected ? "live" : "reconnecting"}
            </span>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
