import type { OwnerDashboardViewModel } from "../contracts/ownerDashboard";
import { humanizeCode } from "../lib/labels";

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
      <dt className="text-xs text-zinc-400">{label}</dt>
      <dd className="mt-1 break-words text-xl font-semibold text-zinc-100">{value}</dd>
      {note ? <dd className="mt-0.5 text-[11px] text-zinc-400">{note}</dd> : null}
    </div>
  );
}

export function ReadinessSummaryPanel({
  summary,
  run,
}: {
  summary: NonNullable<OwnerDashboardViewModel["summary"]>;
  run: NonNullable<OwnerDashboardViewModel["run"]>;
}) {
  return (
    <section aria-labelledby="owner-summary-heading" className="space-y-3">
      <h2 id="owner-summary-heading" className="text-sm font-semibold text-zinc-100">
        Portfolio readiness
      </h2>
      <dl className="grid grid-cols-[repeat(auto-fit,minmax(min(9.5rem,100%),1fr))] gap-3">
        <Tile label="Ranked by provider" value={String(summary.rankedCount)} note={`of ${summary.total} candidates`} />
        <Tile label="Research-ready" value={String(summary.researchReadyCount)} note="evidence checks passed for review" />
        <Tile label="Needs evidence" value={String(summary.needsEvidenceCount)} />
        <Tile label="Blocked" value={String(summary.blockedCount)} />
        <Tile label="Launch authorization" value="Not authorized" note="this page cannot grant it" />
      </dl>
      <p className="text-xs text-zinc-400">
        <strong className="font-medium text-zinc-300">Research-ready is not launch authorization.</strong> It means the
        offline evidence checks passed for human review. Launching is a separate human decision that happens in Shopify;
        MarketOS only recommends and explains.
      </p>
      <p className="text-xs text-zinc-400">
        Provider run status: <span className="text-zinc-300">{run.providerStatus ? humanizeCode(run.providerStatus) : "Not provided"}</span>
        {run.nextBestAction ? (
          <>
            {" "}
            · Next best action: <span className="text-zinc-300">{run.nextBestAction}</span>
          </>
        ) : null}
        {run.fingerprintShort ? (
          <>
            {" "}
            · Run fingerprint <code className="text-zinc-400">{run.fingerprintShort}</code>
          </>
        ) : null}
      </p>
    </section>
  );
}
