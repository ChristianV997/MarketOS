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
} from "lucide-react";
import { cn } from "@/lib/utils";

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
];

export default function Sidebar() {
  return (
    <aside className="w-[200px] shrink-0 bg-[#0d0d0f] border-r border-white/[0.06] flex flex-col">
      {/* Logo */}
      <div className="h-12 px-4 flex items-center border-b border-white/[0.06]">
        <span className="text-sm font-semibold tracking-tight text-zinc-100">
          Market<span className="text-indigo-400">OS</span>
        </span>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-3 space-y-0.5 px-2">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-sm transition-colors",
                isActive
                  ? "bg-indigo-500/10 text-indigo-300"
                  : "text-zinc-500 hover:text-zinc-200 hover:bg-white/[0.04]"
              )
            }
          >
            <Icon size={15} strokeWidth={1.75} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="p-3 border-t border-white/[0.06]">
        <p className="text-[10px] text-zinc-600 text-center">v2.0 — autonomous</p>
      </div>
    </aside>
  );
}
