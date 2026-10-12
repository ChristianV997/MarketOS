import { useEffect, useMemo, useState } from "react";
import { adaptApprovalLedger } from "../lib/adaptApprovalLedger.ts";
import { composeApprovalLedgerView, moveSelection, requestIds } from "../lib/composeApprovalLedgerView.ts";
import { humanizeToken, safeDisplayText } from "../lib/safeText.ts";

function bucketLabel(bucket: string): string {
  if (bucket === "blocked") return "Blocked by policy";
  if (bucket === "pending") return "Pending review";
  if (bucket === "simulated") return "Simulated only";
  if (bucket === "draft") return "Draft";
  if (bucket === "approved_record") return "Approved record (not live)";
  if (bucket === "closed") return "Closed";
  return humanizeToken(bucket);
}

export function ApprovalLedgerReview({
  packet,
  loading = false,
  errorMessage = null,
  source = "demo_fixture",
  fileLabel = null,
  adaptSource = "demo_fixture",
}: {
  packet: unknown;
  loading?: boolean;
  errorMessage?: string | null;
  source?: "demo_fixture" | "local_file";
  fileLabel?: string | null;
  adaptSource?: "demo_fixture" | "local_file";
}) {
  const adapted = useMemo(
    () => adaptApprovalLedger(packet, { source: adaptSource }),
    [adaptSource, packet],
  );
  const [selected, setSelected] = useState<string | null>(null);
  // Drop prior selection when the operator swaps demo ↔ local report (or loads another file).
  useEffect(() => {
    setSelected(null);
  }, [adaptSource, packet]);
  const view = useMemo(() => composeApprovalLedgerView({
    loading,
    errorMessage,
    model: adapted.model,
    rejected: adapted.rejected,
    selectedApprovalId: selected,
  }), [adapted, errorMessage, loading, selected]);

  const ids = requestIds(view.model);
  const sourceLabel = source === "local_file"
    ? (fileLabel
      ? `local import · ${safeDisplayText(fileLabel, 80)}`
      : "local import")
    : "demo fixture planning record";

  return (
    <section
      aria-labelledby="approval-ledger-heading"
      className="min-w-0 space-y-4 p-3 sm:p-4 text-zinc-100"
      data-testid="companyos-approval-ledger-review"
      data-report-source={source}
      data-availability={view.model.availability}
    >
      <a
        href="#approval-ledger-requests"
        className="sr-only focus:not-sr-only focus:rounded focus:bg-zinc-900 focus:px-3 focus:py-2"
      >
        Skip to approval requests
      </a>

      <header className="space-y-2">
        <h1 id="approval-ledger-heading" tabIndex={-1} className="text-xl font-semibold outline-none">
          CompanyOS Approval Ledger
        </h1>
        <p className="text-sm text-zinc-300">
          Offline policy and decision review · {safeDisplayText(view.model.report_version, 64)} · {sourceLabel}
        </p>
        <p className="rounded border border-amber-700/60 bg-amber-950/40 p-3 text-sm text-amber-100" role="note">
          {view.authorityNote}
        </p>
      </header>

      <div
        role="status"
        aria-live="polite"
        className="rounded border border-zinc-700 p-3 text-sm"
        data-state={view.state}
      >
        {humanizeToken(view.state)} — {view.message}
      </div>

      {view.state === "success" ? (
        <>
          <section aria-labelledby="ledger-queue-heading" className="space-y-2">
            <h2 id="ledger-queue-heading" className="text-lg font-medium">Queue summary</h2>
            <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 text-sm">
              <li>Blocked: {view.model.queue_summary.blocked}</li>
              <li>Pending review: {view.model.queue_summary.pending}</li>
              <li>Draft or simulated: {view.model.queue_summary.draft_or_simulated}</li>
              <li>Approved records: {view.model.queue_summary.approved} (not live authority)</li>
              <li>Denied: {view.model.queue_summary.denied}</li>
              <li>Missing conditions: {view.model.queue_summary.missing_conditions}</li>
            </ul>
          </section>

          <section aria-labelledby="ledger-safety-heading" className="space-y-2">
            <h2 id="ledger-safety-heading" className="text-lg font-medium">Safety summary</h2>
            <p className="text-sm text-zinc-300">{safeDisplayText(view.model.safety_summary.summary, 400)}</p>
            <ul className="text-sm text-zinc-300">
              <li>Read only: {String(view.model.safety_summary.read_only)}</li>
              <li>Network calls: {String(view.model.safety_summary.network_calls)}</li>
              <li>External action performed: {String(view.model.safety_summary.external_action_performed)}</li>
              <li>Live capabilities enabled: {String(view.model.safety_summary.live_capabilities_enabled)}</li>
              <li>Execution authorized on this page: {String(view.model.execution_authorized)}</li>
            </ul>
          </section>

          <section aria-labelledby="ledger-policies-heading" className="space-y-2">
            <h2 id="ledger-policies-heading" className="text-lg font-medium">Policy state</h2>
            <div className="overflow-x-auto" tabIndex={0} aria-label="Scrollable approval policies">
              <table className="min-w-[40rem] text-left text-sm">
                <thead>
                  <tr>
                    <th scope="col">Request type</th>
                    <th scope="col">Decision class</th>
                    <th scope="col">Risk</th>
                    <th scope="col">Current mode</th>
                    <th scope="col">Approver role</th>
                  </tr>
                </thead>
                <tbody>
                  {view.model.policies.map((policy) => (
                    <tr key={policy.policy_id}>
                      <th scope="row">{humanizeToken(policy.request_type)}</th>
                      <td>{humanizeToken(policy.decision_class)}</td>
                      <td>{humanizeToken(policy.default_risk)}</td>
                      <td>{policy.blocked_in_current_mode ? "Blocked in current mode" : "Draft-safe / reviewable later"}</td>
                      <td>{humanizeToken(policy.required_approver_role)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-sm text-zinc-400">
              Blocked policies: {view.blockedPolicies.length}. Reviewable later: {view.reviewablePolicies.length}.
            </p>
          </section>

          <section aria-labelledby="ledger-requests-heading" className="space-y-2">
            <h2 id="ledger-requests-heading" className="text-lg font-medium">Requests and evidence</h2>
            <div className="overflow-x-auto" tabIndex={0} aria-label="Scrollable approval requests">
              <table id="approval-ledger-requests" className="min-w-[42rem] text-left text-sm">
                <thead>
                  <tr>
                    <th scope="col">Request</th>
                    <th scope="col">Status</th>
                    <th scope="col">Risk</th>
                    <th scope="col">Evidence refs</th>
                    <th scope="col">Distinction</th>
                  </tr>
                </thead>
                <tbody>
                  {view.model.requests.map((request) => (
                    <tr key={request.approval_id}>
                      <th scope="row">
                        <button
                          type="button"
                          aria-pressed={request.approval_id === view.selectedApprovalId}
                          className="motion-reduce:transition-none rounded px-2 py-1 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400"
                          onClick={() => setSelected(request.approval_id)}
                          onKeyDown={(event) => {
                            if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
                            event.preventDefault();
                            setSelected(moveSelection(ids, view.selectedApprovalId, event.key));
                          }}
                        >
                          {safeDisplayText(request.request_title, 160)}
                          <span className="block text-xs text-zinc-400">{safeDisplayText(request.approval_id, 80)}</span>
                        </button>
                      </th>
                      <td>{humanizeToken(request.status)}</td>
                      <td>{humanizeToken(request.risk_level)}</td>
                      <td>{request.evidence.length}</td>
                      <td>{bucketLabel(request.status_bucket)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {view.selectedRequest ? (
              <article
                aria-label={`Details for ${view.selectedRequest.approval_id}`}
                className="rounded border border-zinc-700 p-3 space-y-2 text-sm"
              >
                <h3 className="font-medium">{safeDisplayText(view.selectedRequest.request_title, 200)}</h3>
                <p>
                  Type: {humanizeToken(view.selectedRequest.request_type)} · Status:{" "}
                  {humanizeToken(view.selectedRequest.status)} · Approver:{" "}
                  {humanizeToken(view.selectedRequest.required_approver_role)}
                </p>
                <p className="text-zinc-300">
                  Distinction: {bucketLabel(view.selectedRequest.status_bucket)}. This is not an execute control.
                </p>
                <h4 className="font-medium">Evidence references</h4>
                {view.selectedRequest.evidence.length === 0 ? (
                  <p>No sanitized evidence references on this request.</p>
                ) : (
                  <ul>
                    {view.selectedRequest.evidence.map((item) => (
                      <li key={item.ref_id}>
                        {safeDisplayText(item.ref_id, 80)} · {humanizeToken(item.evidence_type)} ·{" "}
                        {safeDisplayText(item.source, 120)} — {safeDisplayText(item.summary, 240)}
                      </li>
                    ))}
                  </ul>
                )}
                <h4 className="font-medium">Conditions</h4>
                {view.selectedRequest.conditions.length === 0 ? (
                  <p>No conditions listed.</p>
                ) : (
                  <ul>
                    {view.selectedRequest.conditions.map((item) => (
                      <li key={item.condition_id}>
                        {safeDisplayText(item.description, 240) || humanizeToken(item.condition_id)} —{" "}
                        {item.satisfied ? "satisfied" : "missing"}
                        {item.required ? " (required)" : ""}
                      </li>
                    ))}
                  </ul>
                )}
              </article>
            ) : null}
          </section>

          <section aria-labelledby="ledger-simulations-heading" className="space-y-2">
            <h2 id="ledger-simulations-heading" className="text-lg font-medium">Simulations</h2>
            {view.model.simulations.length === 0 ? (
              <p className="text-sm">No action simulation in this report.</p>
            ) : (
              <ul className="space-y-2 text-sm">
                {view.model.simulations.map((item) => (
                  <li key={item.simulation_id} className="rounded border border-zinc-800 p-2">
                    <p>
                      <code>{safeDisplayText(item.action, 80)}</code>
                      {" → "}
                      {humanizeToken(item.result)}
                    </p>
                    <p>
                      Can be approved now (simulation flag only): {String(item.can_be_approved_now)}. Not live authority.
                    </p>
                    <p>Missing: {item.missing_conditions.map(humanizeToken).join("; ") || "none"}</p>
                    <p>Blockers: {item.blocking_reasons.map(humanizeToken).join("; ") || "none"}</p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-label="Limitations and next action" className="space-y-1 text-sm text-zinc-300">
            <p>Next action (display only): {safeDisplayText(view.model.next_best_action, 400)}</p>
            <ul>
              {view.model.limitations.map((item) => (
                <li key={item}>{safeDisplayText(item, 400)}</li>
              ))}
            </ul>
          </section>
        </>
      ) : null}

      {/* Explicit absence of mutation controls */}
      <p className="sr-only">
        This page has no approve, deny, publish, spend, order, payment, messaging, or provider action controls.
      </p>
    </section>
  );
}
