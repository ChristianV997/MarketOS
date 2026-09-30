import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { PerformanceModel, PerformanceSeries } from "../contracts/ownerDashboard";
import { NOT_AVAILABLE } from "../lib/decimal";
import { buildChartRows } from "../lib/performance";
import { Chip } from "./Chips";

function valueText(series: PerformanceSeries, value: number | null): string {
  if (value === null) return NOT_AVAILABLE;
  const digits = new Intl.NumberFormat("en-US", { maximumFractionDigits: series.unit === "count" ? 0 : 2 }).format(value);
  return series.unit === "currency" && series.currency ? `${series.currency} ${digits}` : digits;
}

export function PerformancePanel({ performance }: { performance: PerformanceModel }) {
  return (
    <section aria-labelledby="owner-performance-heading" className="space-y-3">
      <h2 id="owner-performance-heading" className="text-sm font-semibold text-zinc-100">
        Performance
      </h2>
      {performance.status === "unavailable" ? (
        <p className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 text-sm text-zinc-300">
          <strong className="font-semibold">{NOT_AVAILABLE}.</strong> {performance.reason} Performance is shown only when
          actual records exist, and is never estimated or filled in with zeros.
        </p>
      ) : (
        <div className="space-y-4 rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
          {performance.status === "fixture_demo" ? (
            <p
              role="status"
              data-performance-provenance="fixture"
              className="flex flex-wrap items-center gap-2 text-sm text-amber-200"
            >
              <Chip tone="caution">Demo fixture data</Chip>
              These values are invented to show the layout. They are not observed performance.
            </p>
          ) : (
            <p className="text-sm text-zinc-300">
              <Chip tone="positive">Observed records</Chip>
            </p>
          )}
          {performance.series.map((series) => (
            <figure key={series.id} className="space-y-3">
              <figcaption className="text-xs font-medium text-zinc-300">{series.label}</figcaption>
              <div aria-hidden="true" className="h-56 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={buildChartRows([series])} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                    <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                    <XAxis dataKey="period" stroke="#71717a" tick={{ fontSize: 11 }} />
                    <YAxis stroke="#71717a" tick={{ fontSize: 11 }} allowDecimals={false} width={36} />
                    <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", fontSize: 12 }} />
                    <Line
                      type="monotone"
                      dataKey={series.id}
                      stroke="#818cf8"
                      strokeWidth={2}
                      strokeDasharray={series.provenance === "fixture" ? "5 4" : undefined}
                      connectNulls={false}
                      isAnimationActive={false}
                      dot={{ r: 3 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div role="region" aria-label={`${series.label} values`} tabIndex={0} className="overflow-x-auto rounded-lg border border-white/[0.06]">
                <table className="w-full min-w-[20rem] text-sm">
                  <caption className="sr-only">{series.label}: value for each period</caption>
                  <thead className="border-b border-white/[0.06]">
                    <tr>
                      <th scope="col" className="px-3 py-1.5 text-left text-[11px] font-medium uppercase tracking-wide text-zinc-400">Period</th>
                      <th scope="col" className="px-3 py-1.5 text-right text-[11px] font-medium uppercase tracking-wide text-zinc-400">Value</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04]">
                    {series.points.map((point) => (
                      <tr key={point.periodLabel}>
                        <th scope="row" className="px-3 py-1 text-left font-normal text-zinc-300">{point.periodLabel}</th>
                        <td className="px-3 py-1 text-right tabular-nums text-zinc-100">{valueText(series, point.value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </figure>
          ))}
          {performance.missingPoints > 0 ? (
            <p className="text-xs text-zinc-400">
              {performance.missingPoints} {performance.missingPoints === 1 ? "period has" : "periods have"} no data and{" "}
              {performance.missingPoints === 1 ? "is" : "are"} shown as {performance.missingPoints === 1 ? "a gap" : "gaps"}, not as zero.
            </p>
          ) : null}
        </div>
      )}
    </section>
  );
}
