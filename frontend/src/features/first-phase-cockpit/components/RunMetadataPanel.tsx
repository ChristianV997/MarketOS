import type { RunFingerprint } from "../contracts/firstPhaseEvidencePacket";

export function RunMetadataPanel({
  fingerprint,
  warnings,
  blockedReasons,
  unavailableReasons,
}: {
  fingerprint: RunFingerprint;
  warnings: string[];
  blockedReasons: string[];
  unavailableReasons: string[];
}) {
  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4" aria-label="Run metadata">
      <h3 className="text-sm font-medium text-zinc-100">Deterministic run metadata</h3>
      <div className="mt-3 grid gap-2 text-xs text-zinc-300 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        <span className="rounded bg-zinc-950/50 p-2">
          Evidence mode: <b>{fingerprint.evidenceMode.replace(/_/g, " ")}</b>
        </span>
        <span className="rounded bg-zinc-950/50 p-2">
          Read-only: <b>{fingerprint.readOnly ? "yes" : "no"}</b>
        </span>
        <span className="rounded bg-zinc-950/50 p-2">
          Network calls: <b>{fingerprint.networkCalls ? "reported" : "none"}</b>
        </span>
        <span className="rounded bg-zinc-950/50 p-2">
          Sources: <b>{fingerprint.sourceLabels.join(", ") || "none"}</b>
        </span>
        <span className="rounded bg-zinc-950/50 p-2">
          Source families: <b>{fingerprint.sourceFamilies.join(", ") || "none"}</b>
        </span>
        <span className="rounded bg-zinc-950/50 p-2">
          Report version: <b>{fingerprint.reportVersion ?? "composed-live"}</b>
        </span>
        <span className="rounded bg-zinc-950/50 p-2">
          Generated at: <b>{fingerprint.generatedAt ?? "not provided"}</b>
        </span>
        <span className="rounded bg-zinc-950/50 p-2">
          Next action: <b>{fingerprint.nextBestAction?.replace(/_/g, " ") ?? "none"}</b>
        </span>
      </div>
      {warnings.length > 0 && (
        <p className="mt-3 text-xs text-amber-200">Warnings: {warnings.join(" · ")}</p>
      )}
      {blockedReasons.length > 0 && (
        <p className="mt-2 text-xs text-red-300">
          Blocked: {blockedReasons.map((reason) => reason.replace(/_/g, " ")).join(" · ")}
        </p>
      )}
      {unavailableReasons.length > 0 && (
        <p className="mt-2 text-xs text-zinc-500">
          Unavailable: {unavailableReasons.map((reason) => reason.replace(/_/g, " ")).join(" · ")}
        </p>
      )}
    </section>
  );
}
