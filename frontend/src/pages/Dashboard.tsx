import {
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";
import { useWsStore } from "@/store/ws";
import { useMetricsData, usePlaybook, useTriggerCycle, usePauseRunner, useResumeRunner } from "@/lib/api";
import { cn, fmt, fmtK, fmtTs } from "@/lib/utils";
import { TrendingUp, Zap, Target, Activity, Play, Pause, RefreshCw, type LucideIcon } from "lucide-react";

const PHASE_COLORS: Record<string, string> = {
  RESEARCH: "text-blue-400",
  EXPLORE:  "text-amber-400",
  VALIDATE: "text-orange-400",
  SCALE:    "text-emerald-400",
};

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("bg-[#111113] border border-white/[0.07] rounded-xl", className)}>
      {children}
    </div>
  );
}

function KpiCard({ label, value, sub, icon: Icon, accent }: {
  label: string; value: string; sub?: string;
  icon: LucideIcon;
  accent?: string;
}) {
  return (
    <Card className="p-4 flex items-start justify-between">
      <div>
        <p className="text-[11px] text-zinc-500 uppercase tracking-widest mb-1">{label}</p>
        <p className={cn("text-2xl font-mono font-semibold", accent ?? "text-zinc-100")}>{value}</p>
        {sub && <p className="text-xs text-zinc-600 mt-0.5">{sub}</p>}
      </div>
      <div className="p-2 rounded-lg bg-white/[0.04]">
        <Icon size={16} strokeWidth={1.75} />
      </div>
    </Card>
  );
}

const LABEL_STYLES: Record<string, string> = {
  WINNER:  "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  LOSER:   "bg-red-500/10 text-red-400 border-red-500/20",
  NEUTRAL: "bg-zinc-700/40 text-zinc-400 border-zinc-600/30",
};

const CUSTOM_TOOLTIP = ({ active, payload }: { active?: boolean; payload?: { value: number; name: string }[] }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#1a1a1e] border border-white/10 rounded-lg px-3 py-2 text-xs">
      {payload.map((p) => (
        <div key={p.name} className="flex gap-2">
          <span className="text-zinc-500">{p.name}</span>
          <span className="text-zinc-100 font-mono">{typeof p.value === "number" ? p.value.toFixed(4) : p.value}</span>
        </div>
      ))}
    </div>
  );
};

export default function Dashboard() {
  const snap           = useWsStore((s) => s.snapshot);
  const capitalHistory = useWsStore((s) => s.capitalHistory);
  const roasHistory    = useWsStore((s) => s.roasHistory);
  const lastWorker     = useWsStore((s) => s.lastWorker);

  const { data: metrics } = useMetricsData();
  const { data: pb }      = usePlaybook();

  const triggerCycle = useTriggerCycle();
  const pauseRunner  = usePauseRunner();
  const resumeRunner = useResumeRunner();

  const capital   = snap?.capital ?? metrics?.capital ?? 0;
  const avgRoas   = snap?.avg_roas ?? metrics?.avg_roas ?? 0;
  const winRate   = metrics?.win_rate ?? 0;
  const signals   = snap?.signals_ingested ?? 0;
  const phase     = snap?.phase ?? "—";
  const regime    = snap?.detected_regime ?? "—";
  const cycles    = snap?.total_cycles ?? 0;

  const capData  = capitalHistory.map(([ts, v]) => ({ t: fmtTs(ts), v }));
  const roasData = roasHistory.map(([ts, v]) => ({ t: fmtTs(ts), v }));

  const decisions = snap?.recent_decisions ?? [];
  const signals_  = snap?.top_signals ?? [];
  const playbooks = pb?.playbooks ?? snap?.top_playbooks ?? [];
  const patterns  = pb?.patterns ?? snap?.patterns ?? {};
  const topHooks  = patterns?.top_hooks ?? [];
  const hookScores: Record<string, number> = patterns?.hook_scores ?? {};

  const hookData = topHooks
    .slice(0, 6)
    .map((h: string) => ({ hook: h.slice(0, 30), score: hookScores[h] ?? 0 }));

  return (
    <div className="p-5 space-y-4">
      {/* Action bar */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-sm font-semibold text-zinc-200">Command Center</h1>
          <p className="text-xs text-zinc-600 mt-0.5">
            {regime !== "—" && <span>Regime: <span className="text-zinc-400">{regime}</span> · </span>}
            {lastWorker && <span>Last: <span className="text-zinc-400">{lastWorker}</span></span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => triggerCycle.mutate()}
            disabled={triggerCycle.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw size={12} />
            Cycle
          </button>
          <button
            onClick={() => pauseRunner.mutate()}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white/[0.06] hover:bg-white/[0.10] text-zinc-300 rounded-lg transition-colors"
          >
            <Pause size={12} />
            Pause
          </button>
          <button
            onClick={() => resumeRunner.mutate()}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white/[0.06] hover:bg-white/[0.10] text-zinc-300 rounded-lg transition-colors"
          >
            <Play size={12} />
            Resume
          </button>
        </div>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard label="Capital" value={fmtK(capital)} icon={TrendingUp}
          accent={capital > 0 ? "text-emerald-400" : "text-red-400"} />
        <KpiCard label="Avg ROAS" value={`${fmt(avgRoas)}×`} icon={Zap}
          accent={avgRoas >= 1.2 ? "text-emerald-400" : "text-red-400"} />
        <KpiCard label="Win Rate" value={`${(winRate * 100).toFixed(1)}%`} icon={Target}
          sub={`${cycles.toLocaleString()} cycles`} />
        <KpiCard label="Signals" value={signals.toLocaleString()} icon={Activity}
          accent={PHASE_COLORS[phase] ?? "text-zinc-100"} sub={phase} />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-2 gap-3">
        <Card className="p-4">
          <p className="text-[11px] text-zinc-500 uppercase tracking-widest mb-3">Capital Curve</p>
          <ResponsiveContainer width="100%" height={140}>
            <AreaChart data={capData}>
              <defs>
                <linearGradient id="capGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10b981" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
              <XAxis dataKey="t" hide />
              <YAxis hide domain={["auto", "auto"]} />
              <Tooltip content={<CUSTOM_TOOLTIP />} />
              <Area type="monotone" dataKey="v" name="capital" stroke="#10b981" strokeWidth={1.5}
                fill="url(#capGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </Card>

        <Card className="p-4">
          <p className="text-[11px] text-zinc-500 uppercase tracking-widest mb-3">ROAS Trend</p>
          <ResponsiveContainer width="100%" height={140}>
            <AreaChart data={roasData}>
              <defs>
                <linearGradient id="roasGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#818cf8" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#818cf8" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
              <XAxis dataKey="t" hide />
              <YAxis hide domain={["auto", "auto"]} />
              <Tooltip content={<CUSTOM_TOOLTIP />} />
              <Area type="monotone" dataKey="v" name="roas" stroke="#818cf8" strokeWidth={1.5}
                fill="url(#roasGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </Card>
      </div>

      {/* Middle row */}
      <div className="grid grid-cols-3 gap-3">
        {/* Decision log */}
        <Card className="col-span-2 overflow-hidden">
          <div className="px-4 py-3 border-b border-white/[0.06]">
            <p className="text-[11px] text-zinc-500 uppercase tracking-widest">Decision Log</p>
          </div>
          <div className="overflow-auto max-h-[280px]">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-zinc-600 border-b border-white/[0.04]">
                  {["Variant","ROAS","CTR","CVR","Regime","Label"].map((h) => (
                    <th key={h} className="text-left px-4 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {decisions.slice(0, 15).map((d: Record<string, unknown>, i: number) => (
                  <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">
                    <td className="px-4 py-2 font-mono text-zinc-300">{String(d.variant ?? d.action ?? "—").slice(0, 18)}</td>
                    <td className={cn("px-4 py-2 font-mono", (d.roas as number) >= 1.2 ? "text-emerald-400" : "text-red-400")}>
                      {fmt(d.roas as number)}
                    </td>
                    <td className="px-4 py-2 font-mono text-zinc-400">{fmt(d.ctr as number, 3)}</td>
                    <td className="px-4 py-2 font-mono text-zinc-400">{fmt(d.cvr as number, 3)}</td>
                    <td className="px-4 py-2 text-zinc-500">{String(d.env_regime ?? "—")}</td>
                    <td className="px-4 py-2">
                      <span className={cn(
                        "text-[10px] px-2 py-0.5 rounded border",
                        LABEL_STYLES[String(d.label ?? "NEUTRAL")] ?? LABEL_STYLES.NEUTRAL
                      )}>
                        {String(d.label ?? "—")}
                      </span>
                    </td>
                  </tr>
                ))}
                {decisions.length === 0 && (
                  <tr><td colSpan={6} className="px-4 py-8 text-center text-zinc-600 text-xs">Awaiting decisions…</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>

        {/* Signals feed */}
        <Card className="overflow-hidden">
          <div className="px-4 py-3 border-b border-white/[0.06]">
            <p className="text-[11px] text-zinc-500 uppercase tracking-widest">Signal Feed</p>
          </div>
          <div className="overflow-auto max-h-[280px] divide-y divide-white/[0.04]">
            {signals_.slice(0, 12).map((s: Record<string, unknown>, i: number) => (
              <div key={i} className="px-4 py-2.5 flex items-center justify-between hover:bg-white/[0.02]">
                <div className="min-w-0">
                  <p className="text-xs text-zinc-200 truncate">{String(s.product ?? "—")}</p>
                  <p className="text-[10px] text-zinc-600 truncate">{String(s.source ?? "")}</p>
                </div>
                <span className="text-xs font-mono text-indigo-400 shrink-0 ml-2">
                  {fmt(s.score as number)}
                </span>
              </div>
            ))}
            {signals_.length === 0 && (
              <div className="px-4 py-8 text-center text-zinc-600 text-xs">No signals yet</div>
            )}
          </div>
        </Card>
      </div>

      {/* Bottom row */}
      <div className="grid grid-cols-3 gap-3">
        {/* Playbooks */}
        <Card className="col-span-2 overflow-hidden">
          <div className="px-4 py-3 border-b border-white/[0.06]">
            <p className="text-[11px] text-zinc-500 uppercase tracking-widest">Active Playbooks</p>
          </div>
          <div className="overflow-auto max-h-[220px]">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-zinc-600 border-b border-white/[0.04]">
                  {["Product","Phase","Est. ROAS","Confidence","Evidence"].map((h) => (
                    <th key={h} className="text-left px-4 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {playbooks.slice(0, 8).map((p: Record<string, unknown>, i: number) => (
                  <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                    <td className="px-4 py-2 text-zinc-200">{String(p.product ?? "—")}</td>
                    <td className="px-4 py-2">
                      <span className={cn("text-[10px] px-1.5 py-0.5 rounded", {
                        "bg-emerald-500/10 text-emerald-400": p.phase === "SCALE",
                        "bg-amber-500/10  text-amber-400":   p.phase === "EXPLORE",
                        "bg-blue-500/10   text-blue-400":    p.phase === "RESEARCH",
                        "bg-orange-500/10 text-orange-400":  p.phase === "VALIDATE",
                      })}>
                        {String(p.phase ?? "—")}
                      </span>
                    </td>
                    <td className={cn("px-4 py-2 font-mono", (p.estimated_roas as number) >= 1.5 ? "text-emerald-400" : "text-zinc-400")}>
                      {fmt(p.estimated_roas as number)}×
                    </td>
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                          <div
                            className="h-full bg-indigo-500 rounded-full"
                            style={{ width: `${((p.confidence as number) ?? 0) * 100}%` }}
                          />
                        </div>
                        <span className="text-zinc-500 font-mono text-[10px]">
                          {(((p.confidence as number) ?? 0) * 100).toFixed(0)}%
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-2 font-mono text-zinc-500">{String(p.evidence_count ?? "—")}</td>
                  </tr>
                ))}
                {playbooks.length === 0 && (
                  <tr><td colSpan={5} className="px-4 py-8 text-center text-zinc-600 text-xs">No playbooks yet</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>

        {/* Hook scores */}
        <Card className="p-4">
          <p className="text-[11px] text-zinc-500 uppercase tracking-widest mb-3">Top Hooks</p>
          {hookData.length > 0 ? (
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={hookData} layout="vertical" margin={{ left: 0, right: 8 }}>
                <XAxis type="number" hide domain={[0, 1]} />
                <YAxis type="category" dataKey="hook" width={100} tick={{ fontSize: 10, fill: "#71717a" }} />
                <Tooltip content={<CUSTOM_TOOLTIP />} />
                <Bar dataKey="score" name="score" fill="#6366f1" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[180px] flex items-center justify-center text-xs text-zinc-600">
              No pattern data yet
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
