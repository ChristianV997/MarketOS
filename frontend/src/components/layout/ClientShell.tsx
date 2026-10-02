import { useEffect, useRef } from "react";
import { Outlet, Link, useLocation } from "react-router-dom";
import { ArrowLeft, Building2 } from "lucide-react";

const CLIENT_TITLE = "Client workspace · MarketOS";

/**
 * Dedicated layout for the client CRM workspace.
 * Kept strictly separate from the operator Shell and Sidebar:
 * - Does not subscribe to operator WebSocket or runtime metrics
 * - Supplies its own landmark container
 * - Labels the view as the client view; it makes no claim about data isolation,
 *   because isolation is enforced by the server, not by this layout.
 *
 * Route changes inside the client area move focus to the <main> landmark and
 * keep a client-specific document title, so a keyboard or screen-reader user
 * is told that the page changed.
 */
export default function ClientShell() {
  const { pathname } = useLocation();
  const main = useRef<HTMLElement>(null);
  const firstRender = useRef(true);

  useEffect(() => {
    const previous = document.title;
    document.title = CLIENT_TITLE;
    return () => {
      document.title = previous;
    };
  }, []);

  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    main.current?.focus();
  }, [pathname]);

  return (
    <div className="min-h-screen bg-[#0a0a0b] text-zinc-100 flex flex-col">
      <header className="shrink-0 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-3 sm:px-5 py-1 min-h-12 border-b border-white/[0.06] bg-[#0d0d0f]">
        <div className="flex min-w-0 items-center gap-2 sm:gap-3">
          <nav aria-label="Switch view">
            <Link
              to="/"
              className="flex min-h-[44px] min-w-[44px] items-center gap-1.5 rounded px-2 text-xs text-zinc-300 hover:text-zinc-100 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500"
              aria-label="Return to operator dashboard"
            >
              <ArrowLeft size={14} aria-hidden="true" />
              <span>Operator</span>
            </Link>
          </nav>
          <span aria-hidden="true" className="text-zinc-700">|</span>
          <div className="flex min-w-0 items-center gap-2">
            <Building2 size={15} aria-hidden="true" className="shrink-0 text-violet-400" />
            <span className="truncate text-sm font-semibold tracking-tight text-zinc-100">
              Client <span className="text-violet-400">Workspace</span>
            </span>
          </div>
        </div>
      </header>

      <main
        ref={main}
        id="client-main"
        tabIndex={-1}
        aria-label="Client workspace"
        className="flex-1 overflow-auto focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400"
      >
        <Outlet />
      </main>
    </div>
  );
}
