import type { EvidenceClass, EvidencePillar } from "../contracts/firstPhaseEvidencePacket";

const STATUS_STYLE: Record<EvidencePillar["status"], string> = {
  available: "border-emerald-500/30 text-emerald-300",
  partial: "border-amber-500/30 text-amber-300",
  unavailable: "border-zinc-600/30 text-zinc-400",
  blocked: "border-red-500/30 text-red-300",
};

const SLOT_LABEL: Record<EvidencePillar["status"], string> = {
  available: "slot present (read-only)",
  partial: "slot present",
  unavailable: "slot missing",
  blocked: "blocked",
};

function classChipStyle(evidenceClass: EvidenceClass): string {
  if (
    evidenceClass === "live_sales_validated"
    || evidenceClass === "live_order_verified"
    || evidenceClass === "direct_ship_verified"
    || evidenceClass === "sample_verified"
  ) {
    return "border-lime-500/30 text-lime-300";
  }
  return "border-zinc-600/40 text-zinc-300";
}

export function EvidencePillarsPanel({ pillars }: { pillars: EvidencePillar[] }) {
  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4" aria-label="Evidence pillars">
      <h3 className="text-sm font-medium text-zinc-100" id="evidence-pillars-heading">
        Evidence pillars
      </h3>
      <p className="mt-1 text-[11px] text-zinc-400">
        Slot presence is not commercial validation. Fixture, manual, assumed, and derived classes never authorize launch.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3" role="list">
        {pillars.map((pillar) => (
          <article
            key={pillar.id}
            role="listitem"
            className="rounded border border-zinc-800 bg-zinc-950/40 p-3"
            aria-label={`${pillar.label} ${SLOT_LABEL[pillar.status]} evidence class ${pillar.evidenceClass.replace(/_/g, " ")}`}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-xs font-medium text-zinc-200">{pillar.label}</h4>
              <span className="flex flex-wrap gap-1">
                <span className={`rounded border px-1.5 py-0.5 text-[10px] ${STATUS_STYLE[pillar.status]}`}>
                  {SLOT_LABEL[pillar.status]}
                </span>
                <span className={`rounded border px-1.5 py-0.5 text-[10px] ${classChipStyle(pillar.evidenceClass)}`}>
                  {pillar.evidenceClass.replace(/_/g, " ")}
                </span>
              </span>
            </div>
            <p className="mt-2 text-xs text-zinc-400">{pillar.summary}</p>
            {pillar.provenance && (
              <p className="mt-1 text-[11px] text-zinc-400">
                Provenance: {pillar.provenance.replace(/_/g, " ")}
              </p>
            )}
            {pillar.freshness && (
              <p className="mt-1 text-[11px] text-zinc-400">Freshness: {pillar.freshness}</p>
            )}
            {pillar.sourceFamily && (
              <p className="mt-1 text-[11px] text-zinc-400">
                Source family: {pillar.sourceFamily.replace(/_/g, " ")}
              </p>
            )}
            {pillar.evidenceMode && (
              <p className="mt-1 text-[11px] text-zinc-400">
                Evidence mode: {pillar.evidenceMode.replace(/_/g, " ")}
              </p>
            )}
            <p className="mt-1 text-[11px] text-zinc-400">
              Authorization: not launch authorized
            </p>
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
