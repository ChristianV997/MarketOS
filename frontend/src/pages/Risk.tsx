import { useRisk, useRiskStatus } from "@/lib/api";
import { cn, fmt } from "@/lib/utils";

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("bg-[#111113] border border-white/[0.07] rounded-xl p-4", className)}>{children}</div>;
}

function StatCard({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <Card>
      <p className="text-[11px] text-zinc-500 uppercase tracking-widest mb-1">{label}</p>
      <p className={cn("text-2xl font-mono font-semibold", accent ?? "text-zinc-100")}>{value}</p>
    </Card>
  );
}

export default function Risk() {
  const { data: status, isLoading } = useRiskStatus();
  const { data: risk } = useRisk();

  const drawdown = Number(status?.current_drawdown_pct ?? risk?.drawdown_pct ?? 0);
  const allowed = status?.allowed ?? risk?.allowed;
  const ceiling = Number(status?.daily_spend_ceiling ?? risk?.daily_spend_ceiling ?? 0);
  const spent = Number(status?.spent_today ?? risk?.spent_today ?? 0);

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-4">
      <h1 className="text-lg font-semibold text-zinc-100">Risk</h1>
      {isLoading ? (
        <p className="text-sm text-zinc-500">Loading…</p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard
            label="Spend gate"
            value={allowed === undefined ? "—" : allowed ? "OPEN" : "BLOCKED"}
            accent={allowed === false ? "text-red-400" : "text-emerald-400"}
          />
          <StatCard label="Drawdown" value={`${fmt(drawdown, 1)}%`} accent={drawdown > 15 ? "text-red-400" : "text-zinc-100"} />
          <StatCard label="Spent today" value={`$${fmt(spent)}`} />
          <StatCard label="Daily ceiling" value={`$${fmt(ceiling)}`} />
        </div>
      )}
    </div>
  );
}
