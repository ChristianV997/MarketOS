import type { ControlPlaneSlot } from "../contracts/firstPhaseEvidencePacket";

export function ControlPlanePanel({ slots }: { slots: ControlPlaneSlot[] }) {
  return (
    <section className="rounded-lg border border-violet-500/20 bg-violet-500/5 p-4" aria-label="Control planes">
      <h3 className="text-sm font-medium text-zinc-100">TrustOS, Governor, and Approval Ledger</h3>
      <p className="mt-1 text-xs text-zinc-500">
        Read-only slots. No launch, ads, orders, payment, publishing, or messaging authority is granted in the browser.
      </p>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        {slots.map((slot) => (
          <article key={slot.id} className="rounded border border-zinc-800 bg-zinc-950/40 p-3">
            <div className="flex items-center justify-between gap-2">
              <h4 className="text-xs font-medium text-zinc-200">{slot.label}</h4>
              <span className="rounded border border-zinc-700 px-1.5 py-0.5 text-[10px] text-zinc-400">
                {slot.status}
              </span>
            </div>
            {slot.outcome && (
              <p className="mt-2 text-xs text-violet-200">{slot.outcome.replace(/_/g, " ")}</p>
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
