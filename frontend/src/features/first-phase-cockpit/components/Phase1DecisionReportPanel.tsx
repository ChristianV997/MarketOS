import type { EvidenceAuthorityKind, Phase1DecisionReportView } from "../contracts/phase1DecisionReport";

const AUTHORITY_STYLES: Record<EvidenceAuthorityKind, string> = {
  live_supplier_proof: "border-lime-500/40 bg-lime-500/10 text-lime-200",
  structural_ready: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
  fixture_or_manual: "border-amber-500/40 bg-amber-500/10 text-amber-200",
  partial_or_degraded: "border-sky-500/40 bg-sky-500/10 text-sky-200",
  unavailable: "border-zinc-600 bg-zinc-900/50 text-zinc-400",
  blocked: "border-rose-500/40 bg-rose-500/10 text-rose-200",
};

const AUTHORITY_LABELS: Record<EvidenceAuthorityKind, string> = {
  live_supplier_proof: "Live supplier proof",
  structural_ready: "Structural ready (not supplier proof)",
  fixture_or_manual: "Fixture / manual (not live proof)",
  partial_or_degraded: "Partial / derived context",
  unavailable: "Unavailable",
  blocked: "Blocked",
};

function humanize(value: string): string {
  return value.replace(/_/g, " ");
}

export function Phase1DecisionReportPanel({ report }: { report: Phase1DecisionReportView }) {
  return (
    <section
      id="phase1-decision-report"
      aria-labelledby="phase1-decision-report-heading"
      className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/40 p-4"
      data-testid="phase1-decision-report"
      data-state={report.state}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-zinc-800 pb-3">
        <div>
          <h2 id="phase1-decision-report-heading" className="text-sm font-semibold text-zinc-100">
            Phase 1 decision report
          </h2>
          <p className="mt-1 text-xs text-zinc-500">
            Read-only view of <code className="text-zinc-400">GET /api/phase1/readiness</code>.
            Rankings are not recalculated. No spend, publish, order, or messaging authority.
          </p>
        </div>
        <span
          className="rounded border border-indigo-500/30 bg-indigo-500/10 px-2 py-1 text-[11px] text-indigo-200"
          aria-label={`Decision report state ${report.state}`}
        >
          {report.state}
        </span>
      </div>

      {report.state === "loading" && (
        <p className="text-sm text-zinc-400" role="status" aria-live="polite">
          Loading Phase 1 readiness decision report…
        </p>
      )}

      {report.state === "empty" && (
        <p className="rounded border border-zinc-700 bg-zinc-950/50 p-3 text-sm text-zinc-400" role="status">
          {report.emptyMessage}
        </p>
      )}

      {report.state === "error" && (
        <p
          className="rounded border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200"
          role="alert"
        >
          {report.errorMessage}
        </p>
      )}

      {report.state === "success" && (
        <div className="space-y-4" data-testid="phase1-decision-report-success">
          {report.errorMessage && (
            <p className="rounded border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-200" role="status">
              {report.errorMessage}
            </p>
          )}

          <div className="grid gap-2 text-xs text-zinc-300 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
              <p className="text-zinc-500">Overall status</p>
              <p className="mt-1 font-medium text-zinc-100">
                {report.overallStatus ? humanize(report.overallStatus) : "unavailable"}
              </p>
            </div>
            <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
              <p className="text-zinc-500">Score</p>
              <p className="mt-1 font-medium text-zinc-100">
                {report.overallScore != null ? `${report.overallScore}/100` : "unavailable"}
              </p>
            </div>
            <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
              <p className="text-zinc-500">Supplier proof</p>
              <p className={`mt-1 font-medium ${report.supplierIsLiveProof ? "text-lime-200" : "text-amber-200"}`}>
                {report.supplierIsLiveProof ? "Live observed" : "Not live supplier proof"}
              </p>
            </div>
            <div className="rounded border border-zinc-800 bg-zinc-950/40 p-2">
              <p className="text-zinc-500">Competition context</p>
              <p className="mt-1 font-medium text-zinc-100">
                {report.competitionIsLiveObserved
                  ? "Live observed (not supplier proof)"
                  : "Fixture / partial / missing"}
              </p>
            </div>
          </div>

          <div className="rounded border border-indigo-500/30 bg-indigo-500/5 p-3">
            <h3 className="text-xs font-medium text-indigo-100">Next action</h3>
            <p className="mt-1 text-sm text-zinc-100">
              {report.nextBestAction ? humanize(report.nextBestAction) : "unavailable"}
            </p>
            {report.nextBestPromptHint && (
              <p className="mt-2 text-xs text-zinc-400">{report.nextBestPromptHint}</p>
            )}
            <p className="mt-2 text-[11px] text-zinc-500">
              Flags: read-only {report.readOnly ? "yes" : "no"} · network_calls{" "}
              {report.networkCalls ? "yes" : "no"} · mutated {report.mutated ? "yes" : "no"}
            </p>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <div>
              <h3 className="text-xs font-medium text-zinc-300">Blocking gates</h3>
              {report.blockingGates.length === 0 ? (
                <p className="mt-1 text-xs text-zinc-500">None listed.</p>
              ) : (
                <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-rose-200" aria-label="Blocking gates">
                  {report.blockingGates.map((gate) => (
                    <li key={gate}>{humanize(gate)}</li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <h3 className="text-xs font-medium text-zinc-300">Advisory warnings</h3>
              {report.advisoryWarnings.length === 0 ? (
                <p className="mt-1 text-xs text-zinc-500">None listed.</p>
              ) : (
                <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-amber-200" aria-label="Advisory warnings">
                  {report.advisoryWarnings.map((warning) => (
                    <li key={warning}>{humanize(warning)}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div>
            <h3 className="text-xs font-medium text-zinc-300">Assumptions</h3>
            <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-zinc-400" aria-label="Planning assumptions">
              {report.assumptionLabels.map((label) => (
                <li key={label}>{label}</li>
              ))}
            </ul>
          </div>

          <div>
            <h3 className="text-xs font-medium text-zinc-300">Evidence provenance</h3>
            {report.provenanceLines.length === 0 ? (
              <p className="mt-1 text-xs text-zinc-500">Provenance unavailable on this report.</p>
            ) : (
              <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-zinc-400" aria-label="Evidence provenance">
                {report.provenanceLines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
            {report.evidenceSummaryLines.length > 0 && (
              <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-zinc-400" aria-label="Evidence summary">
                {report.evidenceSummaryLines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <h3 className="text-xs font-medium text-zinc-300">Category readiness</h3>
            <ul className="mt-2 space-y-2" aria-label="Category readiness">
              {report.categories.map((category) => (
                <li
                  key={category.key}
                  className="rounded border border-zinc-800 bg-zinc-950/40 p-2 text-xs text-zinc-300"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium text-zinc-100">{category.label}</span>
                    <span className={`rounded border px-1.5 py-0.5 text-[10px] ${AUTHORITY_STYLES[category.authority]}`}>
                      {AUTHORITY_LABELS[category.authority]}
                    </span>
                  </div>
                  <p className="mt-1">
                    Status: <span className="text-zinc-100">{category.status}</span>
                    {category.points != null && category.weight != null
                      ? ` · ${category.points.toFixed(2)} pts / weight ${category.weight}`
                      : ""}
                  </p>
                  <p className="mt-0.5 text-zinc-500">{category.detail}</p>
                </li>
              ))}
            </ul>
          </div>

          <div className="grid gap-3 text-xs text-zinc-400 sm:grid-cols-2">
            <div>
              <h3 className="font-medium text-zinc-300">Allowed next phases</h3>
              <p className="mt-1">
                {report.allowedNextPhases.length
                  ? report.allowedNextPhases.map(humanize).join(" · ")
                  : "none listed"}
              </p>
            </div>
            <div>
              <h3 className="font-medium text-zinc-300">Forbidden next phases</h3>
              <p className="mt-1">
                {report.forbiddenNextPhases.length
                  ? report.forbiddenNextPhases.map(humanize).join(" · ")
                  : "none listed"}
              </p>
            </div>
          </div>

          <p className="text-[11px] text-zinc-500">
            Fixture and manual signals remain screening evidence. Only supplier status{" "}
            <code className="text-zinc-400">live_observed</code> is treated as authenticated supplier proof
            in this panel. Competition live context never grants launch authority.
          </p>
        </div>
      )}
    </section>
  );
}
