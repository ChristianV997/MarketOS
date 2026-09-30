import { Outlet, Link } from "react-router-dom";
import { ArrowLeft, Building2, Shield } from "lucide-react";

/**
 * Dedicated layout for the client CRM workspace.
 * Kept strictly isolated from the operator Shell and Sidebar:
 * - Does not subscribe to operator WebSocket or runtime metrics
 * - Supplies its own landmark container
 * - Explicitly demarcates tenant client view
 */
export default function ClientShell() {
  return (
    <div className="min-h-screen bg-[#0a0a0b] text-zinc-100 flex flex-col">
      <header className="h-12 shrink-0 flex items-center justify-between px-5 border-b border-white/[0.06] bg-[#0d0d0f]">
        <div className="flex items-center gap-3">
          <Link
            to="/"
            className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-200 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500 rounded px-1.5 py-1"
            aria-label="Return to operator dashboard"
          >
            <ArrowLeft size={14} />
            <span>Operator</span>
          </Link>
          <span className="text-zinc-700">|</span>
          <div className="flex items-center gap-2">
            <Building2 size={15} className="text-violet-400" />
            <span className="text-sm font-semibold tracking-tight text-zinc-100">
              Client <span className="text-violet-400">Workspace</span>
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3 text-xs text-zinc-400">
          <div className="flex items-center gap-1.5">
            <Shield size={13} className="text-emerald-400" />
            <span className="text-[11px] text-zinc-400">Isolated Client Context</span>
          </div>
          <span className="inline-block w-2 h-2 rounded-full bg-violet-400/80" />
        </div>
      </header>

      <main className="flex-1 overflow-auto p-4 md:p-6">
        <Outlet />
      </main>
    </div>
  );
}
