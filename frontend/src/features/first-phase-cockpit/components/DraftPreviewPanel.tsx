import type { RankedCandidateRow, RunFingerprint } from "../contracts/firstPhaseEvidencePacket";
import { LIVE_PROOF_EVIDENCE_CLASSES } from "../contracts/firstPhaseEvidencePacket";
import type { SupplierCsvPreviewResult } from "@/lib/supplierCsvParser";

interface DraftPreviewPanelProps {
  candidate: RankedCandidateRow | null;
  fingerprint: RunFingerprint;
  onExport?: () => void;
  exportDisabled?: boolean;
  supplierCsvPreview?: SupplierCsvPreviewResult | null;
}

export function DraftPreviewPanel({
  candidate,
  fingerprint,
  onExport,
  exportDisabled = false,
  supplierCsvPreview,
}: DraftPreviewPanelProps) {
  const activeMode = candidate?.evidenceMode ?? fingerprint.evidenceMode ?? "unknown";
  const isScreeningOnly = activeMode === "fixture_only" || activeMode === "manual";
  const isSimulated = activeMode === "simulated";
  const isLiveReadonly = activeMode === "live_readonly";

  const supplierClass = candidate?.supplierEvidenceClass ?? "unavailable";
  const consumerClass = candidate?.consumerEvidenceClass ?? "unavailable";
  const overallClass = candidate?.evidenceClass ?? "unavailable";

  const hasLiveProofClaim =
    LIVE_PROOF_EVIDENCE_CLASSES.has(supplierClass)
    || LIVE_PROOF_EVIDENCE_CLASSES.has(consumerClass)
    || LIVE_PROOF_EVIDENCE_CLASSES.has(overallClass);

  const matchedCsvRow =
    candidate && supplierCsvPreview
      ? supplierCsvPreview.rows.find((r) => r.candidateId === candidate.candidateId) ?? null
      : null;

  return (
    <section
      id="draft-preview-panel"
      className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-4 space-y-5"
      aria-label="Draft preview and operator governance panel"
    >
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-zinc-800 pb-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-zinc-100">Draft output preview & governance gate</h3>
            <span className="rounded border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 text-[10px] font-medium text-sky-300">
              Read-only blueprints
            </span>
          </div>
          <p className="mt-1 text-xs text-zinc-400">
            Operator-facing preview of Launch and Site Draft outputs. Blocked or draft states are strictly
            non-executable planning blueprints.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {candidate ? (
            <span className="rounded border border-indigo-500/30 bg-indigo-500/10 px-2.5 py-1 text-xs font-medium text-indigo-200">
              Candidate: {candidate.candidateId} · Rank {candidate.rankIndex + 1}
            </span>
          ) : (
            <span className="rounded border border-zinc-700 bg-zinc-800 px-2.5 py-1 text-xs text-zinc-400">
              Overview (no candidate selected)
            </span>
          )}
        </div>
      </div>

      {/* 1. Input Provenance: Fixture/Manual vs Live-Observed */}
      <div className="space-y-3">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
          Input provenance & observation mode
        </h4>
        <div className="grid gap-3 sm:grid-cols-2">
          <div
            className={`rounded-lg border p-3 ${
              isScreeningOnly
                ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
                : isSimulated
                ? "border-sky-500/40 bg-sky-500/10 text-sky-200"
                : isLiveReadonly
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                : "border-zinc-700 bg-zinc-800/40 text-zinc-300"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wide">
                {isScreeningOnly
                  ? "Screening Input (Fixture / Manual)"
                  : isSimulated
                  ? "Simulated Input (Projection Only)"
                  : isLiveReadonly
                  ? "Live-Observed (Read-Only API)"
                  : "Unknown Input Mode"}
              </span>
              <span className="rounded border border-current px-1.5 py-0.5 text-[10px] font-mono">
                {activeMode}
              </span>
            </div>
            <p className="mt-2 text-xs leading-relaxed opacity-90">
              {isScreeningOnly && (
                <>
                  Inputs originate from static test fixtures or manual screening spreadsheets. Fixture and manual
                  evidence are <strong>never live commercial validation</strong>, <strong>never supplier proof</strong>,
                  and <strong>never order verification</strong>. Metrics are planning assumptions.
                </>
              )}
              {isSimulated && (
                <>
                  Inputs are derived from simulated planning models. These figures reflect synthetic projections rather
                  than real-world catalog transactions.
                </>
              )}
              {isLiveReadonly && (
                <>
                  Inputs were retrieved from read-only marketplace APIs. Read-only observation does not constitute
                  supplier contract proof or live transaction validation.
                </>
              )}
              {!isScreeningOnly && !isSimulated && !isLiveReadonly && (
                <>
                  Input provenance is unconfirmed. All outputs must be treated as unverified screening drafts.
                </>
              )}
            </p>
          </div>

          <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-3 text-xs space-y-2">
            <div className="flex justify-between border-b border-zinc-800 pb-1.5 text-zinc-400">
              <span>Evidence classification</span>
              <span className="font-mono text-[11px] text-zinc-300">Class breakdown</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Supplier evidence class:</span>
              <span className="font-mono text-zinc-200">{supplierClass.replace(/_/g, " ")}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Consumer evidence class:</span>
              <span className="font-mono text-zinc-200">{consumerClass.replace(/_/g, " ")}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Overall evidence class:</span>
              <span className="font-mono text-zinc-200">{overallClass.replace(/_/g, " ")}</span>
            </div>
            <p className="pt-1 text-[11px] text-zinc-500">
              {hasLiveProofClaim
                ? "Live proof class assigned from verified source."
                : "Screening/fixture runs never assign live proof classes (sample_verified, direct_ship_verified, live_sales_validated)."}
            </p>
          </div>
        </div>

        {/* 1b. Offline Supplier CSV Preview Evidence (if active) */}
        {supplierCsvPreview && (
          <div
            className="rounded-lg border border-amber-600/30 bg-amber-950/20 p-3 text-xs space-y-2"
            data-testid="matched-csv-evidence"
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold text-amber-300">
                Offline Manual Supplier CSV Evidence (Preview)
              </span>
              <span className="rounded border border-amber-700/50 bg-amber-900/50 px-1.5 py-0.5 text-[10px] font-mono text-amber-200">
                evidence_mode=manual_import · unverified
              </span>
            </div>
            {matchedCsvRow ? (
              <div className="space-y-1.5 text-zinc-300">
                <p className="text-zinc-200">
                  Matched candidate: <span className="font-mono font-semibold text-amber-200">{matchedCsvRow.candidateId}</span>
                  {matchedCsvRow.productName && (
                    <span className="text-zinc-400"> (display label: {matchedCsvRow.productName})</span>
                  )}
                </p>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 font-mono text-[11px]">
                  <div className="rounded border border-zinc-800 bg-zinc-900/50 p-1.5">
                    <span className="text-[10px] text-zinc-500 block">Unit Cost</span>
                    <span className="text-zinc-100">{matchedCsvRow.unitCostDisplay}</span>
                  </div>
                  <div className="rounded border border-zinc-800 bg-zinc-900/50 p-1.5">
                    <span className="text-[10px] text-zinc-500 block">Shipping</span>
                    <span className="text-zinc-100">{matchedCsvRow.shippingCostDisplay}</span>
                  </div>
                  <div className="rounded border border-zinc-800 bg-zinc-900/50 p-1.5">
                    <span className="text-[10px] text-zinc-500 block">Estimated Landed</span>
                    <span className="text-zinc-100">
                      {matchedCsvRow.estimatedLandedCost !== null
                        ? `$${matchedCsvRow.estimatedLandedCost.toFixed(2)} ${matchedCsvRow.currency}`
                        : "missing (costs unverified)"}
                    </span>
                  </div>
                  <div className="rounded border border-zinc-800 bg-zinc-900/50 p-1.5">
                    <span className="text-[10px] text-zinc-500 block">Supplier / MOQ</span>
                    <span className="text-zinc-100">{matchedCsvRow.supplier.toUpperCase()}{matchedCsvRow.moq ? ` · MOQ: ${matchedCsvRow.moq}` : ""}</span>
                  </div>
                </div>
                <p className="text-[10px] text-amber-300/80 pt-1">
                  Notice: Manual CSV preview evidence is unverified screening data only. It does not update canonical backend economics, does not constitute supplier feasibility proof, and grants zero purchasing or publishing authority.
                </p>
              </div>
            ) : (
              <p className="text-[11px] text-zinc-400">
                {candidate
                  ? `No matching row found in previewed CSV for candidate "${candidate.candidateId}". Product display names are never coerced into candidate IDs.`
                  : `Catalog CSV preview loaded (${supplierCsvPreview.validRowCount} valid rows, ${supplierCsvPreview.invalidRowCount} rows with issues). Select a candidate above to check for matching manual supplier evidence.`}
              </p>
            )}
          </div>
        )}
      </div>

      {/* 2. Candidate Identity, Assumptions & Blockers */}
      {candidate ? (
        <div className="space-y-3">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
            Candidate identity, assumptions & blockers
          </h4>
          <div className="grid gap-3 sm:grid-cols-3">
            {/* Identity & Provenance */}
            <div className="rounded border border-zinc-800 bg-zinc-950/40 p-3 text-xs space-y-1.5">
              <span className="font-semibold text-zinc-300">Identity & Replay</span>
              <div className="text-zinc-400">
                <p>
                  ID: <span className="font-mono text-zinc-200">{candidate.candidateId}</span>
                </p>
                <p>
                  SKU:{" "}
                  <span className="font-mono text-zinc-200">
                    {candidate.sku ?? "unavailable from current endpoints"}
                  </span>
                </p>
                <p>
                  Source: <span className="text-zinc-200">{candidate.sourceFamily ?? "unspecified"}</span>
                </p>
                <p>
                  Replay:{" "}
                  <span className="font-mono text-[10px] text-zinc-300">
                    {candidate.replayIdentity ?? fingerprint.replayIdentity ?? "unavailable"}
                  </span>
                </p>
              </div>
            </div>

            {/* Assumptions */}
            <div className="rounded border border-zinc-800 bg-zinc-950/40 p-3 text-xs space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-zinc-300">Active Assumptions</span>
                <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-mono text-zinc-400">
                  {candidate.assumptions.length}
                </span>
              </div>
              {candidate.assumptions.length > 0 ? (
                <ul className="list-disc pl-4 space-y-1 text-zinc-300">
                  {candidate.assumptions.map((assumption, idx) => (
                    <li key={idx} className="font-mono text-[11px]">
                      {assumption}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-zinc-500">No explicit assumptions listed.</p>
              )}
              <p className="text-[10px] text-zinc-500 pt-1">
                Assumptions require empirical verification before promotion.
              </p>
            </div>

            {/* Hard Gates & Blockers */}
            <div
              className={`rounded border p-3 text-xs space-y-1.5 ${
                candidate.hardGates.length > 0
                  ? "border-rose-500/30 bg-rose-500/5 text-rose-200"
                  : "border-zinc-800 bg-zinc-950/40 text-zinc-300"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold">Hard Gates & Blockers</span>
                <span className="rounded bg-zinc-800/80 px-1.5 py-0.5 text-[10px] font-mono">
                  {candidate.hardGates.length}
                </span>
              </div>
              {candidate.hardGates.length > 0 ? (
                <ul className="list-disc pl-4 space-y-1">
                  {candidate.hardGates.map((gate, idx) => (
                    <li key={idx} className="font-mono text-[11px]">
                      {gate}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-zinc-500">No hard gates currently active.</p>
              )}
              {candidate.missingEvidence.length > 0 && (
                <div className="pt-1 text-[11px] text-zinc-400">
                  Missing: {candidate.missingEvidence.join(", ")}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="rounded border border-dashed border-zinc-800 p-3 text-center text-xs text-zinc-500">
          Select a candidate row above to inspect candidate-specific identity, assumptions, and blockers.
        </div>
      )}

      {/* 3. Launch & Site Draft Output Previews */}
      <div className="space-y-3">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
          Launch & site draft blueprints (read-only)
        </h4>

        <div className="grid gap-3 lg:grid-cols-2">
          {/* Launch Draft Pack Preview */}
          <div className="rounded-lg border border-zinc-800 bg-zinc-950/50 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-zinc-200">Launch Draft Pack Blueprint</span>
              <span className="rounded border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-300">
                draft_only_pending_human_approval
              </span>
            </div>

            <dl className="grid gap-2 text-xs">
              <div className="rounded border border-zinc-800/60 bg-zinc-900/40 p-2">
                <dt className="text-zinc-500">Offer Stack</dt>
                <dd className="mt-0.5 font-medium text-zinc-200">
                  {candidate
                    ? `Draft offer: ${candidate.title}`
                    : "Core offer package pending candidate selection"}
                </dd>
                <dd className="mt-1 text-[11px] text-zinc-400">
                  Promise:{" "}
                  {candidate?.consumerAttentionSummary
                    ? candidate.consumerAttentionSummary
                    : "Customer-matched value proposition (pending validation)"}
                </dd>
                <dd className="mt-0.5 text-[11px] text-zinc-500">
                  Pricing summary: {candidate?.economicsLabel ?? "Pending economics validation"}
                </dd>
              </div>

              <div className="rounded border border-zinc-800/60 bg-zinc-900/40 p-2">
                <dt className="text-zinc-500">Product Listing Copy (Draft)</dt>
                <dd className="mt-0.5 font-medium text-zinc-200">
                  {candidate?.productTitle ?? candidate?.title ?? "Product Listing Headline Draft"}
                </dd>
                <dd className="mt-1 text-[11px] text-zinc-400">
                  Bullets: Verified specifications pending sample inspection · Customer problem-solution fit ·
                  Satisfaction policy draft
                </dd>
              </div>

              <div className="rounded border border-zinc-800/60 bg-zinc-900/40 p-2">
                <dt className="text-zinc-500">Landing Page Hero (Draft)</dt>
                <dd className="mt-0.5 text-zinc-300">
                  Headline: Explore {candidate?.title ?? "Product Selection"}
                </dd>
                <dd className="mt-1">
                  <span className="inline-block rounded border border-zinc-700 bg-zinc-800 px-2 py-0.5 text-[10px] text-zinc-400">
                    [Draft CTA: Shop Now · Nonfunctional Preview]
                  </span>
                </dd>
              </div>

              <div className="rounded border border-zinc-800/60 bg-zinc-900/40 p-2">
                <dt className="text-zinc-500">Platform Payload Contracts</dt>
                <dd className="mt-1 space-y-1 font-mono text-[11px] text-zinc-400">
                  <p>{'Shopify Draft: { status: "draft", published: false }'}</p>
                  <p>{'Medusa Draft: { status: "draft", published: false }'}</p>
                </dd>
              </div>
            </dl>

            <p className="text-[11px] text-zinc-500 italic">
              Launch Draft Pack / Higgsfield creative assets: deferred. No frontend display adapter until a
              cockpit-owned read-only contract exists on this page. Creative generation remains blocked until human
              policy sign-off in Approval Ledger.
            </p>
          </div>

          {/* Site Draft Pack Preview */}
          <div className="rounded-lg border border-zinc-800 bg-zinc-950/50 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-zinc-200">Site Draft Pack Blueprint</span>
              <span className="rounded border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 text-[10px] font-medium text-sky-300">
                draft_blueprint_only
              </span>
            </div>

            <dl className="grid gap-2 text-xs">
              <div className="rounded border border-zinc-800/60 bg-zinc-900/40 p-2">
                <dt className="text-zinc-500">Site Type & Strategy</dt>
                <dd className="mt-0.5 font-medium text-zinc-200">
                  ecommerce_store (platform-neutral blueprint)
                </dd>
                <dd className="mt-1 text-[11px] text-zinc-400">
                  Target lane:{" "}
                  {candidate?.marketLane
                    ? `${candidate.marketLane.origin ?? "—"} → ${candidate.marketLane.destination ?? "—"} (${candidate.marketLane.currency ?? "—"})`
                    : "Standard ecommerce single-product / catalog funnel"}
                </dd>
              </div>

              <div className="rounded border border-zinc-800/60 bg-zinc-900/40 p-2">
                <dt className="text-zinc-500">Route Manifest</dt>
                <dd className="mt-1 grid grid-cols-2 gap-1 font-mono text-[11px] text-zinc-300">
                  <span>/ (Home / Hero)</span>
                  <span>/products (Catalog)</span>
                  <span>/about (Brand story)</span>
                  <span>/contact (Inquiries)</span>
                </dd>
              </div>

              <div className="rounded border border-zinc-800/60 bg-zinc-900/40 p-2">
                <dt className="text-zinc-500">Deployment Readiness Status</dt>
                <dd className="mt-0.5 text-zinc-300 font-mono">
                  overall_status: &quot;draft_blueprint_only&quot;
                </dd>
                <dd className="mt-1 text-[11px] text-zinc-400">
                  Blockers: Human approval required · Domain & hosting unprovisioned · Zero live mutations
                </dd>
              </div>

              <div className="rounded border border-zinc-800/60 bg-zinc-900/40 p-2">
                <dt className="text-zinc-500">Platform Blueprint Payloads</dt>
                <dd className="mt-1 space-y-1 font-mono text-[11px] text-zinc-400">
                  <p>{'Shopify Theme: { status: "draft", mutated: false }'}</p>
                  <p>{'Medusa Storefront: { status: "draft", mutated: false }'}</p>
                  <p>{'Static Site: { status: "draft", mutated: false }'}</p>
                </dd>
              </div>
            </dl>

            <p className="text-[11px] text-zinc-500 italic">
              Blueprints are platform-neutral configurations. No DNS, domains, hosting providers, or storefront
              mutations are performed or authorized.
            </p>
          </div>
        </div>
      </div>

      {/* 4. Sanitized Client-Safe Export Preview */}
      <div className="space-y-3">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
          Client-safe export preview & isolation
        </h4>
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-medium text-zinc-200">
                TrustOS Client Workspace Isolation (first-phase-cockpit-client-safe-v1)
              </p>
              <p className="mt-1 text-xs text-zinc-400">
                Sanitized JSON export. Guarantees zero internal prompts, zero scoring formulas, zero heuristics, zero
                filesystem paths, and zero raw provider credentials.
              </p>
            </div>
            {onExport && (
              <button
                type="button"
                onClick={onExport}
                disabled={exportDisabled}
                className="rounded border border-indigo-500/40 bg-indigo-600/20 px-3 py-1.5 text-xs font-medium text-indigo-200 hover:bg-indigo-600/30 disabled:opacity-40 disabled:cursor-not-allowed focus-visible:ring-2 focus-visible:ring-indigo-400"
              >
                Download Client-Safe Report
              </button>
            )}
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-4 text-xs font-mono text-zinc-400">
            <div className="rounded border border-zinc-800 bg-zinc-900/50 p-2">
              <span className="text-[10px] text-zinc-500 block">read_only</span>
              <span className="text-emerald-400">true</span>
            </div>
            <div className="rounded border border-zinc-800 bg-zinc-900/50 p-2">
              <span className="text-[10px] text-zinc-500 block">network_calls</span>
              <span className="text-emerald-400">false</span>
            </div>
            <div className="rounded border border-zinc-800 bg-zinc-900/50 p-2">
              <span className="text-[10px] text-zinc-500 block">mutated</span>
              <span className="text-emerald-400">false</span>
            </div>
            <div className="rounded border border-zinc-800 bg-zinc-900/50 p-2">
              <span className="text-[10px] text-zinc-500 block">secrets_included</span>
              <span className="text-emerald-400">none (redacted)</span>
            </div>
          </div>
        </div>
      </div>

      {/* 5. Nontechnical Operator Safety Gate */}
      <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 space-y-3">
        <div className="flex items-center gap-2">
          <span className="rounded bg-red-500/20 px-2 py-0.5 text-xs font-bold text-red-200 uppercase tracking-wide">
            Governance Safety Gate
          </span>
          <h4 className="text-xs font-semibold text-red-100">
            Blocked or Draft is NEVER Authorization to Publish or Transact
          </h4>
        </div>
        <p className="text-xs text-red-200/90 leading-relaxed">
          Nontechnical operator advisory: Having a candidate marked as &quot;draft_ready&quot; or &quot;screening&quot;
          is strictly an internal research stage. It does <strong>NOT</strong> authorize publishing live websites,
          committing ad spend, transmitting purchase orders to suppliers, charging customer credit cards, or sending
          customer outreach. All external provider actions remain disabled by default.
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 pt-1 text-xs">
          <div className="rounded border border-red-500/20 bg-zinc-950/40 p-2">
            <span className="text-zinc-400 block text-[11px]">publishing_authorized</span>
            <span className="font-mono font-semibold text-rose-300">false</span>
          </div>
          <div className="rounded border border-red-500/20 bg-zinc-950/40 p-2">
            <span className="text-zinc-400 block text-[11px]">ads_launched / spend</span>
            <span className="font-mono font-semibold text-rose-300">false ($0.00)</span>
          </div>
          <div className="rounded border border-red-500/20 bg-zinc-950/40 p-2">
            <span className="text-zinc-400 block text-[11px]">orders_created</span>
            <span className="font-mono font-semibold text-rose-300">false (0 orders)</span>
          </div>
          <div className="rounded border border-red-500/20 bg-zinc-950/40 p-2">
            <span className="text-zinc-400 block text-[11px]">payments_created</span>
            <span className="font-mono font-semibold text-rose-300">false ($0.00)</span>
          </div>
          <div className="rounded border border-red-500/20 bg-zinc-950/40 p-2">
            <span className="text-zinc-400 block text-[11px]">customer_messages_sent</span>
            <span className="font-mono font-semibold text-rose-300">false (0 sent)</span>
          </div>
          <div className="rounded border border-red-500/20 bg-zinc-950/40 p-2">
            <span className="text-zinc-400 block text-[11px]">live_mutations</span>
            <span className="font-mono font-semibold text-rose-300">false (offline)</span>
          </div>
        </div>
      </div>
    </section>
  );
}
