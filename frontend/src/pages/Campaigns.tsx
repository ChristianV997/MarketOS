import { useState } from "react";
import {
  useCampaigns, useGeo, useAccounts,
  useCampaignOverride, useTikTokLaunch,
} from "@/lib/api";
import { cn, fmt, fmtK } from "@/lib/utils";
import { Rocket, Globe, CreditCard, ChevronDown } from "lucide-react";

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("bg-[#111113] border border-white/[0.07] rounded-xl", className)}>{children}</div>;
}

function SectionHeader({ title, count }: { title: string; count?: number }) {
  return (
    <div className="px-4 py-3 border-b border-white/[0.06] flex items-center justify-between">
      <p className="text-[11px] text-zinc-500 uppercase tracking-widest">{title}</p>
      {count != null && <span className="text-xs text-zinc-600 font-mono">{count}</span>}
    </div>
  );
}

const STATUS_STYLE: Record<string, string> = {
  active:  "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  paused:  "bg-amber-500/10  text-amber-400  border-amber-500/20",
  killed:  "bg-red-500/10    text-red-400    border-red-500/20",
  scaling: "bg-indigo-500/10 text-indigo-400 border-indigo-500/20",
  default: "bg-zinc-700/40   text-zinc-400   border-zinc-600/30",
};

function statusStyle(s: string) {
  return STATUS_STYLE[s?.toLowerCase()] ?? STATUS_STYLE.default;
}

export default function Campaigns() {
  const { data: camps, isLoading: campsLoading } = useCampaigns();
  const { data: geo }                             = useGeo();
  const { data: accounts }                        = useAccounts();

  const override    = useCampaignOverride();
  const tikTokLaunch = useTikTokLaunch();

  const [overrideMenu, setOverrideMenu] = useState<string | null>(null);

  const campaigns: Record<string, unknown>[] = camps ?? [];
  const geoRows:   Record<string, unknown>[] = geo ?? [];
  const accts:     Record<string, unknown>[] = accounts ?? [];

  return (
    <div className="p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-sm font-semibold text-zinc-200">Campaigns</h1>
          <p className="text-xs text-zinc-600 mt-0.5">{campaigns.length} tracked · TikTok + AJO</p>
        </div>
        <button
          onClick={() => tikTokLaunch.mutate()}
          disabled={tikTokLaunch.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors disabled:opacity-50"
        >
          <Rocket size={12} />
          {tikTokLaunch.isPending ? "Launching…" : "Launch TikTok"}
        </button>
      </div>

      {/* Campaign table */}
      <Card>
        <SectionHeader title="Active Campaigns" count={campaigns.length} />
        <div className="overflow-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-zinc-600 border-b border-white/[0.04]">
                {["Campaign","Product","ROAS","Spend","Revenue","CTR","Status","Actions"].map((h) => (
                  <th key={h} className="text-left px-4 py-2.5 font-medium whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {campsLoading && (
                <tr><td colSpan={8} className="px-4 py-10 text-center text-zinc-600">Loading campaigns…</td></tr>
              )}
              {!campsLoading && campaigns.length === 0 && (
                <tr><td colSpan={8} className="px-4 py-10 text-center text-zinc-600">No campaigns found. Launch one above.</td></tr>
              )}
              {campaigns.map((c, i) => {
                const id = String(c.campaign_id ?? i);
                const roas = c.roas as number;
                return (
                  <tr key={id} className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">
                    <td className="px-4 py-2.5 font-mono text-zinc-400 text-[10px]">{id.slice(0, 12)}…</td>
                    <td className="px-4 py-2.5 text-zinc-200">{String(c.product ?? "—")}</td>
                    <td className={cn("px-4 py-2.5 font-mono", roas >= 1.5 ? "text-emerald-400" : roas >= 1.0 ? "text-amber-400" : "text-red-400")}>
                      {fmt(roas)}×
                    </td>
                    <td className="px-4 py-2.5 font-mono text-zinc-400">{fmtK(c.spend as number)}</td>
                    <td className="px-4 py-2.5 font-mono text-zinc-300">{fmtK(c.revenue as number)}</td>
                    <td className="px-4 py-2.5 font-mono text-zinc-500">{fmt(c.ctr as number, 3)}</td>
                    <td className="px-4 py-2.5">
                      <span className={cn("text-[10px] px-2 py-0.5 rounded border", statusStyle(String(c.status ?? "")))}>
                        {String(c.status ?? "—")}
                      </span>
                      {Boolean(c.override) && (
                        <span className="ml-1 text-[9px] text-amber-500">OVR</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="relative">
                        <button
                          onClick={() => setOverrideMenu(overrideMenu === id ? null : id)}
                          className="flex items-center gap-1 text-[11px] text-zinc-500 hover:text-zinc-300 px-2 py-1 rounded bg-white/[0.04] hover:bg-white/[0.08] transition-colors"
                        >
                          Override <ChevronDown size={10} />
                        </button>
                        {overrideMenu === id && (
                          <div className="absolute right-0 top-full mt-1 z-20 bg-[#1a1a1e] border border-white/10 rounded-lg shadow-xl overflow-hidden">
                            {["scale","pause","kill","hold"].map((action) => (
                              <button
                                key={action}
                                onClick={() => {
                                  override.mutate({ id, action });
                                  setOverrideMenu(null);
                                }}
                                className={cn(
                                  "block w-full text-left px-4 py-2 text-xs hover:bg-white/[0.06] transition-colors",
                                  action === "kill" ? "text-red-400" :
                                  action === "scale" ? "text-emerald-400" :
                                  "text-zinc-400"
                                )}
                              >
                                {action.charAt(0).toUpperCase() + action.slice(1)}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Bottom grid */}
      <div className="grid grid-cols-2 gap-4">
        {/* Geo */}
        <Card>
          <div className="px-4 py-3 border-b border-white/[0.06] flex items-center gap-2">
            <Globe size={13} className="text-zinc-600" />
            <p className="text-[11px] text-zinc-500 uppercase tracking-widest">Geo Breakdown</p>
          </div>
          <div className="overflow-auto max-h-[260px]">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-zinc-600 border-b border-white/[0.04]">
                  {["Country","ROAS","Spend","Status"].map((h) => (
                    <th key={h} className="text-left px-4 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {geoRows.map((g, i) => (
                  <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                    <td className="px-4 py-2 text-zinc-200">{String(g.country ?? "—")}</td>
                    <td className={cn("px-4 py-2 font-mono", (g.roas as number) >= 1.5 ? "text-emerald-400" : "text-zinc-400")}>
                      {fmt(g.roas as number)}×
                    </td>
                    <td className="px-4 py-2 font-mono text-zinc-500">{fmtK(g.spend as number)}</td>
                    <td className="px-4 py-2">
                      <span className={cn("text-[10px] px-1.5 py-0.5 rounded border", statusStyle(String(g.status ?? "")))}>
                        {String(g.status ?? "—")}
                      </span>
                    </td>
                  </tr>
                ))}
                {geoRows.length === 0 && (
                  <tr><td colSpan={4} className="px-4 py-8 text-center text-zinc-600">No geo data</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>

        {/* Accounts */}
        <Card>
          <div className="px-4 py-3 border-b border-white/[0.06] flex items-center gap-2">
            <CreditCard size={13} className="text-zinc-600" />
            <p className="text-[11px] text-zinc-500 uppercase tracking-widest">Account Health</p>
          </div>
          <div className="overflow-auto max-h-[260px]">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-zinc-600 border-b border-white/[0.04]">
                  {["Account","Status","Spend","Risk Flags"].map((h) => (
                    <th key={h} className="text-left px-4 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {accts.map((a, i) => (
                  <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                    <td className="px-4 py-2 text-zinc-200">
                      <div>{String(a.name ?? a.account_id ?? "—")}</div>
                      <div className="text-[10px] text-zinc-600">{String(a.account_id ?? "")}</div>
                    </td>
                    <td className="px-4 py-2">
                      <span className={cn("text-[10px] px-1.5 py-0.5 rounded border", statusStyle(String(a.status ?? "")))}>
                        {String(a.status ?? "—")}
                      </span>
                    </td>
                    <td className="px-4 py-2 font-mono text-zinc-400">{fmtK(a.spend as number)}</td>
                    <td className="px-4 py-2">
                      {((a.risk_flags as string[]) ?? []).length > 0 ? (
                        <span className="text-red-400 text-[10px]">
                          {(a.risk_flags as string[]).join(", ")}
                        </span>
                      ) : (
                        <span className="text-zinc-600 text-[10px]">none</span>
                      )}
                    </td>
                  </tr>
                ))}
                {accts.length === 0 && (
                  <tr><td colSpan={4} className="px-4 py-8 text-center text-zinc-600">No accounts</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
}
