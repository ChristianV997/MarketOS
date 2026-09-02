import type { EvidencePillar } from "../contracts/firstPhaseEvidencePacket";

const STATUS_STYLE: Record<EvidencePillar["status"], string> = {
  available: "border-emerald-500/30 text-emerald-300",
  partial: "border-amber-500/30 text-amber-300",
  unavailable: "border-zinc-600/30 text-zinc-500",
  blocked: "border-red-500/30 text-red-300",
};

export function EvidencePillarsPanel({ pillars }: { pillars: EvidencePillar[] }) {
  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4" aria-label="Evidence pillars">
      <h3 className="text-sm font-medium text-zinc-100">Evidence pillars</h3>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        {pillars.map((pillar) => (
          <article key={pillar.id} className="rounded border border-zinc-800 bg-zinc-950/40 p-3">
            <div className="flex items-center justify-between gap-2">
              <h4 className="text-xs font-medium text-zinc-200">{pillar.label}</h4>
              <span className={`rounded border px-1.5 py-0.5 text-[10px] ${STATUS_STYLE[pillar.status]}`}>
                {pillar.status}
              </span>
            </div>
            <p className="mt-2 text-xs text-zinc-400">{pillar.summary}</p>
            {pillar.provenance && (
              <p className="mt-1 text-[11px] text-zinc-500">Provenance: {pillar.provenance.replace(/_/g, " ")}</p>
            )}
            {pillar.freshness && (
              <p className="mt-1 text-[11px] text-zinc-500">Freshness: {pillar.freshness}</p>
            )}
            {pillar.blockedReasons.length > 0 && (
              <p className="mt-2 text-[11px] text-amber-200">
                {pillar.blockedReasons.map((reason) => reason.replace(/_/g, " ")).join(" · ")}
              </p>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
