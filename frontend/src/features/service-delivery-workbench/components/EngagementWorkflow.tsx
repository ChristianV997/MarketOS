import type { ReactNode } from "react";
import {
  PRIORITY_SERVICE_LABELS,
  type ClientSafeServiceExport,
  type EvidenceClass,
  type ServiceEngagement,
} from "../contracts/serviceEngagementProjection.ts";
import { HIGGSFIELD_CONTRACT_SOURCE } from "../lib/creativeAssetContract.ts";
import { lifecycleLabel } from "./WorkbenchChrome.tsx";

const EVIDENCE_STYLE: Record<EvidenceClass, string> = {
  observed: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  derived: "border-sky-500/30 bg-sky-500/10 text-sky-200",
  assumption: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  supplier_claimed: "border-orange-500/30 bg-orange-500/10 text-orange-200",
  supplier_documented: "border-teal-500/30 bg-teal-500/10 text-teal-200",
  fixture: "border-zinc-500/40 bg-zinc-700/20 text-zinc-300",
  manual_import: "border-indigo-500/30 bg-indigo-500/10 text-indigo-200",
  simulated: "border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-200",
  unavailable: "border-zinc-600/40 bg-zinc-800/40 text-zinc-300",
  live_validated: "border-lime-500/30 bg-lime-500/10 text-lime-200",
};

function Panel({
  title,
  children,
  headingId,
}: {
  title: string;
  headingId: string;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={headingId} className="rounded-lg border border-white/[0.06] bg-[#111113] p-4">
      <h3 id={headingId} className="text-sm font-semibold text-zinc-100">{title}</h3>
      <div className="mt-3 space-y-2 text-sm text-zinc-300">{children}</div>
    </section>
  );
}

function JsonPreview({
  value,
  label,
  maxHeightClass = "max-h-40",
}: {
  value: unknown;
  label: string;
  maxHeightClass?: string;
}) {
  return (
    <pre
      role="region"
      tabIndex={0}
      aria-label={label}
      className={`mt-2 ${maxHeightClass} overflow-auto whitespace-pre-wrap break-all rounded bg-black/40 p-2 text-[11px] text-zinc-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-400`}
    >
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function EvidencePill({ value }: { value: EvidenceClass }) {
  return (
    <span className={`inline-flex rounded border px-1.5 py-0.5 text-[11px] ${EVIDENCE_STYLE[value]}`}>
      {value}
    </span>
  );
}

export function EngagementWorkflow({
  engagement,
  exportPreview,
}: {
  engagement: ServiceEngagement;
  exportPreview: ClientSafeServiceExport | null;
}) {
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <Panel title="Client intake" headingId="intake-heading">
        <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div><dt className="text-[11px] uppercase text-zinc-400">Client</dt><dd>{engagement.intake.display_name}</dd></div>
          <div><dt className="text-[11px] uppercase text-zinc-400">Workspace</dt><dd>{engagement.intake.workspace_id}</dd></div>
          <div><dt className="text-[11px] uppercase text-zinc-400">Service</dt><dd>{PRIORITY_SERVICE_LABELS[engagement.service_id]}</dd></div>
          <div><dt className="text-[11px] uppercase text-zinc-400">Lifecycle</dt><dd>{lifecycleLabel(engagement.lifecycle_state)}</dd></div>
        </dl>
        <table className="mt-2 min-w-full text-left text-xs">
          <thead className="text-zinc-400">
            <tr><th scope="col" className="py-1">Field</th><th scope="col">Status</th><th scope="col">Client must provide</th></tr>
          </thead>
          <tbody>
            {engagement.intake.fields.map((field) => (
              <tr key={field.field_id} className="border-t border-white/[0.04]">
                <th scope="row" className="py-1 pr-2 font-medium text-zinc-200">{field.label}</th>
                <td className="pr-2">{field.status}</td>
                <td>{field.client_must_provide}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel title="Eligibility and data-quality" headingId="eligibility-heading">
        {engagement.eligibility.data_inadequate ? (
          <div className="rounded-md border border-orange-500/40 bg-orange-500/10 p-3 text-orange-100">
            <p className="font-medium">data_inadequate — not a generic warning</p>
            <p className="mt-1 text-xs">
              Analysis, contribution copies, and client-safe export stay blocked until the client supplies the records below.
            </p>
            <ol className="mt-2 list-decimal space-y-2 pl-5 text-xs">
              {engagement.eligibility.required_from_client.map((item) => (
                <li key={item.field}>
                  <strong>{item.field}.</strong> {item.why} How: {item.how_to_provide}
                </li>
              ))}
            </ol>
          </div>
        ) : (
          <ul className="list-disc space-y-1 pl-5 text-xs">
            {engagement.eligibility.reasons.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
        )}
      </Panel>

      <Panel title="Evidence register" headingId="evidence-heading">
        <p className="text-xs text-zinc-400">
          Classes are displayed separately and never upgraded. live_validated is shown only when the projection already carries that class.
        </p>
        <ul className="mt-2 space-y-2">
          {engagement.evidence.map((item) => (
            <li key={item.evidence_id} className="rounded-md border border-white/[0.05] p-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium text-zinc-100">{item.title}</span>
                <EvidencePill value={item.evidence_class} />
              </div>
              <p className="mt-1 text-xs text-zinc-400">{item.summary}</p>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="Financial-analysis readiness" headingId="finance-heading">
        <p>{engagement.financial_readiness.ready ? "Ready for display of sanitized copies." : "Not ready."}</p>
        <p className="text-xs text-zinc-400">{engagement.financial_readiness.note}</p>
        {engagement.financial_readiness.missing.length > 0 && (
          <ul className="list-disc pl-5 text-xs">
            {engagement.financial_readiness.missing.map((item) => <li key={item}>{item}</li>)}
          </ul>
        )}
      </Panel>

      <Panel title="Package and scope review" headingId="scope-heading">
        <p className="text-xs text-zinc-400">
          Package identity is mapped from the #261 package_id / workbench service_id. Scope text is a display copy.
        </p>
        <p className="font-medium text-zinc-100">{PRIORITY_SERVICE_LABELS[engagement.service_id]}</p>
        <ul className="list-disc pl-5 text-xs">
          {engagement.assumptions.map((item) => <li key={item}>{item}</li>)}
        </ul>
        <p className="text-[11px] text-zinc-400">Draft-ready is not commercially validated.</p>
      </Panel>

      <Panel title="Deliverable acceptance criteria" headingId="acceptance-heading">
        <ul className="space-y-2">
          {engagement.deliverables.map((item) => (
            <li key={item.deliverable_id} className="rounded-md border border-white/[0.05] p-2 text-xs">
              <p className="font-medium text-zinc-100">{item.name}</p>
              <p className="text-zinc-400">Acceptance: status {item.status}. Blocked reason: {item.blocked_reason ?? "none"}.</p>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="Client review / revision / approval / delivery" headingId="lifecycle-review-heading">
        <p className="text-xs">
          Current state: <strong>{lifecycleLabel(engagement.lifecycle_state)}</strong>.
          This panel does not transition CompanyOS states.
        </p>
        {engagement.lifecycle_state === "client_review" && (
          <p className="text-sky-200">Client review: wait for the client. Do not publish or charge.</p>
        )}
        {engagement.lifecycle_state === "revision_requested" && (
          <p className="text-amber-200">Revision requested: inspect missing evidence and assumptions; do not treat the draft as accepted.</p>
        )}
        {engagement.lifecycle_state === "approved" && (
          <p className="text-emerald-200">Approved is a backend-copied label, not live delivery or payment authority.</p>
        )}
        {engagement.lifecycle_state === "delivered" && (
          <p className="text-emerald-200">Delivered is a planning label. Confirm the client-safe packet, not a live storefront.</p>
        )}
        {(engagement.lifecycle_state === "renewal_candidate" || engagement.lifecycle_state === "upsell_candidate") && (
          <p className="text-indigo-200">
            Renewal/upsell candidate is advisory only. The workbench cannot create a new engagement or send outreach.
            Copied renewal_state={engagement.renewal_state ?? "unavailable"}; approval_state={engagement.approval_state ?? "unavailable"}; delivery_state={engagement.delivery_state ?? "unavailable"}.
          </p>
        )}
        {engagement.lifecycle_state === "unavailable" && (
          <p>Lifecycle unavailable. Treat every field as missing until a canonical projection arrives.</p>
        )}
        {engagement.lifecycle_state === "screening" && (
          <p>Screening: data-quality blockers still apply. Do not skip to draft-ready.</p>
        )}
      </Panel>

      <Panel title="Draft report preview" headingId="draft-report-heading">
        <p className="text-xs text-zinc-400">
          Preview reuses the client-safe export. data_inadequate engagements cannot be exported as complete deliverables.
        </p>
        {exportPreview?.accepted ? (
          <JsonPreview
            value={exportPreview.payload}
            label="Draft report JSON preview"
            maxHeightClass="max-h-40"
          />
        ) : (
          <p className="text-red-200 text-xs">{exportPreview?.rejection_reason ?? "No draft report."}</p>
        )}
      </Panel>

      <Panel title="Deliverable checklist" headingId="deliverable-heading">
        <ul className="space-y-2">
          {engagement.deliverables.map((item) => (
            <li key={item.deliverable_id} className="flex flex-col gap-1 rounded-md border border-white/[0.05] p-2 sm:flex-row sm:items-center sm:justify-between">
              <span>{item.name}</span>
              <span className="text-xs text-zinc-400">{item.status}{item.blocked_reason ? ` — ${item.blocked_reason}` : ""}</span>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="Client-safe export preview" headingId="export-heading">
        {!exportPreview && <p>No export preview.</p>}
        {exportPreview?.accepted ? (
          <div>
            <p className="text-emerald-300">Accepted client-safe preview. Internal prompts, formulas, heuristics, credentials, and cross-client data are omitted.</p>
            <JsonPreview
              value={exportPreview.payload}
              label="Client-safe export JSON preview"
              maxHeightClass="max-h-64"
            />
          </div>
        ) : (
          <div className="rounded-md border border-red-500/30 bg-red-500/10 p-3 text-red-100">
            <p className="font-medium">Export rejected</p>
            <p className="mt-1 text-xs">{exportPreview?.rejection_reason}</p>
            {exportPreview?.payload && (
              <JsonPreview
                value={exportPreview.payload}
                label="Rejected export JSON preview"
                maxHeightClass="max-h-40"
              />
            )}
          </div>
        )}
      </Panel>

      <Panel title="Assumptions and missing data" headingId="assumptions-heading">
        <p className="text-[11px] uppercase text-zinc-400">Assumptions</p>
        <ul className="list-disc pl-5 text-xs">
          {engagement.assumptions.map((item) => <li key={item}>{item}</li>)}
        </ul>
        <p className="pt-2 text-[11px] uppercase text-zinc-400">Missing data</p>
        {engagement.missing_data.length ? (
          <ul className="list-disc pl-5 text-xs">
            {engagement.missing_data.map((item) => <li key={item}>{item}</li>)}
          </ul>
        ) : (
          <p className="text-xs text-zinc-400">No missing-data rows on this engagement.</p>
        )}
      </Panel>

      <Panel title="Service economics summary" headingId="economics-heading">
        <p className="text-xs text-amber-200">{engagement.economics.planning_assumption_note}</p>
        <dl className="grid grid-cols-2 gap-2 text-xs">
          <div>
            <dt className="text-zinc-400">Fee copy</dt>
            <dd>
              {engagement.economics.fee
                ? `${engagement.economics.fee.amount_label} ${engagement.economics.fee.currency}`
                : "unavailable"}
              {engagement.economics.fee && (
                <EvidencePill value={engagement.economics.fee.evidence_class} />
              )}
            </dd>
          </div>
          <div>
            <dt className="text-zinc-400">Contribution copy</dt>
            <dd>
              {engagement.economics.contribution
                ? `${engagement.economics.contribution.amount_label} ${engagement.economics.contribution.currency}`
                : engagement.economics.contribution_unavailable_reason}
            </dd>
          </div>
        </dl>
        <p className="text-[11px] text-zinc-400">frontend_calculates={String(engagement.economics.frontend_calculates)}</p>
      </Panel>

      <Panel title="Capacity warning" headingId="capacity-heading">
        <p className="font-medium capitalize">{engagement.capacity.state}</p>
        <p className="text-xs">{engagement.capacity.message}</p>
        {engagement.capacity.concurrent_label && (
          <p className="text-xs text-zinc-400">{engagement.capacity.concurrent_label}</p>
        )}
      </Panel>

      <Panel title="Decision and next-best action" headingId="nba-heading">
        <p className="text-zinc-100">{engagement.next_best_action.action}</p>
        <p className="text-xs text-zinc-400">
          Owner: {engagement.next_best_action.owner}. Live execution: never.
        </p>
        <p className="text-xs">{engagement.next_best_action.rationale}</p>
      </Panel>

      <Panel title="Creative asset requests (draft / unavailable)" headingId="creative-heading">
        <p className="text-xs text-zinc-400">
          Inspected {HIGGSFIELD_CONTRACT_SOURCE}. No Higgsfield SDK, key, MCP, upload, generation, or publish.
        </p>
        <ul className="space-y-2">
          {engagement.creative_assets.map((item) => (
            <li key={item.skill_id} className="rounded-md border border-dashed border-white/[0.08] p-2 text-xs">
              <p className="font-medium text-zinc-200">{item.skill_id} · {item.status}</p>
              <p className="text-zinc-400">{item.note}</p>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}
