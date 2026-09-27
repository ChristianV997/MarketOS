import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  BarChart3,
  Package,
  Layers,
  Activity,
  Server,
  ShieldAlert,
  History,
  Wrench,
  ListChecks,
  ClipboardList,
  Telescope,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { SIDEBAR_NAV_ID, sidebarIsInert } from "./sidebarDrawer";

const NAV = [
  { to: "/",          icon: LayoutDashboard, label: "Dashboard"  },
  { to: "/campaigns", icon: BarChart3,        label: "Campaigns"  },
  { to: "/products",  icon: Package,          label: "Products"   },
  { to: "/creatives", icon: Layers,           label: "Creatives"  },
  { to: "/signals",   icon: Activity,         label: "Signals"    },
  { to: "/runtime",   icon: Server,           label: "Runtime"    },
  { to: "/risk",      icon: ShieldAlert,      label: "Risk"       },
  { to: "/replay",    icon: History,          label: "Replay"     },
  { to: "/services",  icon: Wrench,           label: "Services"   },
  { to: "/operator/events", icon: ListChecks, label: "Operator Events" },
  { to: "/operator/services", icon: ClipboardList, label: "Service Workbench" },
  { to: "/operator/first-phase", icon: Telescope, label: "First-phase cockpit" },
];

export default function Sidebar({
  drawerMode = false,
  open = false,
  onNavigate,
}: {
  drawerMode?: boolean;
  open?: boolean;
  onNavigate?: () => void;
}) {
  const inert = sidebarIsInert(drawerMode, open);

  return (
    <aside
      id="operator-sidebar"
      aria-hidden={inert || undefined}
      {...(inert ? { inert: "" } : {})}
      className={cn(
        "w-[200px] shrink-0 bg-[#0d0d0f] border-r border-white/[0.06] flex flex-col",
        "max-md:fixed max-md:top-12 max-md:bottom-0 max-md:left-0 max-md:z-40",
        "max-md:transition-transform max-md:duration-200",
        open ? "max-md:translate-x-0" : "max-md:-translate-x-full",
        "md:static md:z-auto md:translate-x-0",
      )}
    >
      <div className="h-12 px-4 flex items-center border-b border-white/[0.06] max-md:hidden">
        <span className="text-sm font-semibold tracking-tight text-zinc-100">
          Market<span className="text-indigo-400">OS</span>
        </span>
      </div>

      <nav id={SIDEBAR_NAV_ID} className="flex-1 py-3 space-y-0.5 px-2 overflow-y-auto" aria-label="Operator">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            tabIndex={inert ? -1 : undefined}
            onClick={() => onNavigate?.()}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-sm transition-colors",
                "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400",
                isActive
                  ? "bg-indigo-500/10 text-indigo-300"
                  : "text-zinc-500 hover:text-zinc-200 hover:bg-white/[0.04]"
              )
            }
          >
            <Icon size={15} strokeWidth={1.75} aria-hidden="true" />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="p-3 border-t border-white/[0.06]">
        <p className="text-[10px] text-zinc-600 text-center">v2.0 — autonomous</p>
      </div>
    </aside>
  );
}
