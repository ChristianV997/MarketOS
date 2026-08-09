import { useCreatives } from "@/lib/api";
import { cn, fmt, fmtK } from "@/lib/utils";

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

export default function Creatives() {
  const { data, isLoading } = useCreatives();
  const creatives: Record<string, unknown>[] = Array.isArray(data) ? data : data?.creatives ?? [];

  return (
    <div className="p-5 space-y-4">
      <div>
        <h1 className="text-sm font-semibold text-zinc-200">Creatives</h1>
        <p className="text-xs text-zinc-600 mt-0.5">{creatives.length} tracked · hooks &amp; angles</p>
      </div>

      <Card>
        <SectionHeader title="Active Creatives" count={creatives.length} />
        {isLoading ? (
          <p className="text-xs text-zinc-500 p-4">Loading…</p>
        ) : creatives.length === 0 ? (
          <p className="text-xs text-zinc-600 italic p-4">No creatives tracked yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="text-zinc-600 border-b border-white/[0.06] uppercase text-[10px]">
                  <th className="px-4 py-2">Product</th>
                  <th className="px-4 py-2">Hook</th>
                  <th className="px-4 py-2">Angle</th>
                  <th className="px-4 py-2">ROAS</th>
                  <th className="px-4 py-2">Spend</th>
                </tr>
              </thead>
              <tbody>
                {creatives.map((c, i) => (
                  <tr key={i} className="border-b border-white/[0.04] hover:bg-white/[0.02]">
                    <td className="px-4 py-2.5 text-zinc-200">{String(c.product ?? "—")}</td>
                    <td className="px-4 py-2.5 text-zinc-400 max-w-[220px] truncate">{String(c.hook ?? "—")}</td>
                    <td className="px-4 py-2.5 text-zinc-400">{String(c.angle ?? "—")}</td>
                    <td className="px-4 py-2.5 font-mono text-emerald-400">{fmt(Number(c.roas ?? 0))}×</td>
                    <td className="px-4 py-2.5 font-mono text-zinc-400">{fmtK(Number(c.spend ?? 0))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
