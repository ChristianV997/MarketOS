import type { ControlPlaneSlot } from "../contracts/firstPhaseEvidencePacket";

const STATUS_STYLE: Record<ControlPlaneSlot["status"], string> = {
  unavailable: "border-zinc-600/40 text-zinc-500",
  fixture: "border-amber-500/30 text-amber-200",
  simulated: "border-sky-500/30 text-sky-200",
  stale: "border-orange-500/30 text-orange-200",
  live_readonly: "border-emerald-500/30 text-emerald-200",
  blocked: "border-red-500/30 text-red-200",
};

export function ControlPlanePanel({ slots }: { slots: ControlPlaneSlot[] }) {
  return (
    <section className="rounded-lg border border-violet-500/20 bg-violet-500/5 p-4" aria-label="Control planes">
      <h3 className="text-sm font-medium text-zinc-100">TrustOS, Governor, and Approval Ledger</h3>
      <p className="mt-1 text-xs text-zinc-500">
        Read-only slots. No launch, ads, orders, payment, publishing, or messaging authority is granted in the browser.
      </p>
      <div className="mt-3 grid gap-3 md:grid-cols-3" role="list">
        {slots.map((slot) => (
          <article
            key={slot.id}
            role="listitem"
            className="rounded border border-zinc-800 bg-zinc-950/40 p-3"
            aria-label={`${slot.label} ${slot.status}`}
          >
            <div className="flex items-center justify-between gap-2">
              <h4 className="text-xs font-medium text-zinc-200">{slot.label}</h4>
              <span className={`rounded border px-1.5 py-0.5 text-[10px] ${STATUS_STYLE[slot.status]}`}>
                {slot.status.replace(/_/g, " ")}
              </span>
            </div>
            {slot.outcome && (
              <p className="mt-2 text-xs text-violet-200">{slot.outcome.replace(/_/g, " ")}</p>
            )}
            {slot.nextBestAction && (
              <p className="mt-1 text-[11px] text-zinc-400">
                Next: {slot.nextBestAction.replace(/_/g, " ")}
              </p>
            )}
            {slot.blockedReasons.length > 0 && (
              <p className="mt-2 text-[11px] text-amber-200">
                {slot.blockedReasons.map((reason) => reason.replace(/_/g, " ")).join(" · ")}
              </p>
            )}
            {slot.notes.map((note) => (
              <p key={note} className="mt-1 text-[11px] text-zinc-500">{note}</p>
            ))}
          </article>
        ))}
      </div>
    </section>
  );
}
