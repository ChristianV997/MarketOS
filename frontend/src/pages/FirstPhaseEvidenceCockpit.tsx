import { useDeferredValue, useEffect, useMemo, useState, useTransition } from "react";
import { CandidateDetailPanel } from "@/features/first-phase-cockpit/components/CandidateDetailPanel";
import { CockpitStatusBanner } from "@/features/first-phase-cockpit/components/CockpitStatusBanner";
import { CockpitToolbar } from "@/features/first-phase-cockpit/components/CockpitToolbar";
import { ControlPlanePanel } from "@/features/first-phase-cockpit/components/ControlPlanePanel";
import { EvidencePillarsPanel } from "@/features/first-phase-cockpit/components/EvidencePillarsPanel";
import { RankedCandidatesPanel } from "@/features/first-phase-cockpit/components/RankedCandidatesPanel";
import { RunMetadataPanel } from "@/features/first-phase-cockpit/components/RunMetadataPanel";
import { useFirstPhaseEvidenceCockpit } from "@/features/first-phase-cockpit/hooks/useFirstPhaseEvidenceCockpit";
import type { CandidateFilterState } from "@/features/first-phase-cockpit/contracts/firstPhaseEvidencePacket";
import { filterCandidates } from "@/features/first-phase-cockpit/lib/filterCandidates";
import { serializeClientSafeExport } from "@/features/first-phase-cockpit/lib/exportClientSafeReport";
import {
  initialFilter,
  serializeFilterSearch,
  writeStoredFilter,
} from "@/features/first-phase-cockpit/lib/persistFilters";

const SAFETY_BADGES = [
  ["Read-only", "border-sky-500/30 bg-sky-500/10 text-sky-300"],
  ["Not live validated", "border-rose-500/30 bg-rose-500/10 text-rose-200"],
  ["No network mutations", "border-zinc-500/30 bg-zinc-800 text-zinc-300"],
  ["Advisory", "border-violet-500/30 bg-violet-500/10 text-violet-300"],
  ["No launch authority", "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"],
  ["No credentials in browser", "border-amber-500/30 bg-amber-500/10 text-amber-300"],
] as const;

export default function FirstPhaseEvidenceCockpitPage() {
  const { packet, isLoading, hasErrors } = useFirstPhaseEvidenceCockpit();
  const [filter, setFilter] = useState<CandidateFilterState>(() =>
    initialFilter(typeof window === "undefined" ? "" : window.location.search),
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [windowStart, setWindowStart] = useState(0);
  const [exportMessage, setExportMessage] = useState<string | null>(null);
  const [, startFilterTransition] = useTransition();
  const deferredFilter = useDeferredValue(filter);

  const filteredCandidates = useMemo(
    () => filterCandidates(packet.rankedCandidates, deferredFilter),
    [packet.rankedCandidates, deferredFilter],
  );

  useEffect(() => {
    setWindowStart(0);
  }, [deferredFilter.query, deferredFilter.risk, deferredFilter.decision, deferredFilter.topOnly, deferredFilter.topN]);

  useEffect(() => {
    writeStoredFilter(deferredFilter);
    const nextSearch = serializeFilterSearch(deferredFilter);
    if (typeof window === "undefined") return;
    const url = `${window.location.pathname}${nextSearch}${window.location.hash}`;
    window.history.replaceState(null, "", url);
  }, [deferredFilter]);

  const selectedCandidate =
    filteredCandidates.find((candidate) => candidate.candidateId === selectedId)
    ?? packet.rankedCandidates.find((candidate) => candidate.candidateId === selectedId)
    ?? null;

  function handleFilterChange(next: CandidateFilterState) {
    startFilterTransition(() => {
      setFilter(next);
    });
  }

  function handleExport() {
    try {
      const exportedAt = new Date().toISOString();
      const body = serializeClientSafeExport(packet, exportedAt);
      const blob = new Blob([body], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `first-phase-cockpit-client-safe-${exportedAt.replace(/[:.]/g, "-")}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      setExportMessage("Downloaded client-safe JSON report (no secrets, no raw payloads).");
    } catch (error) {
      setExportMessage(
        error instanceof Error ? error.message : "client_safe_export_rejected",
      );
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-5 overflow-x-hidden p-4 sm:p-6">
      {/* Launch Draft Pack / Higgsfield creative assets: deferred. No frontend display adapter until a cockpit-owned read-only contract exists on this page. */}
      <a
        href="#ranked-candidates-table"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-zinc-900 focus:px-3 focus:py-2 focus:text-sm focus:text-zinc-100"
      >
        Skip to ranked candidates
      </a>

      <header className="space-y-3">
        <div>
          <h1 className="text-xl font-semibold text-zinc-100">First-phase evidence cockpit</h1>
          <p className="mt-1 text-sm text-zinc-500">
            Composes existing Phase 1 API contracts without recalculating rankings or granting external authority.
          </p>
        </div>
        <div className="flex flex-wrap gap-2" aria-label="Safety guarantees">
          {SAFETY_BADGES.map(([label, style]) => (
            <span key={label} className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${style}`}>
              {label}
            </span>
          ))}
        </div>
      </header>

      <CockpitStatusBanner
        state={packet.state}
        overallStatus={packet.fingerprint.overallStatus}
        nextBestAction={packet.fingerprint.nextBestAction}
        evidenceMode={packet.fingerprint.evidenceMode}
        projectionWarning={packet.fingerprint.projectionWarning}
        unmatchedServerCount={packet.fingerprint.unmatchedServerIds.length}
        unmatchedProjectionCount={packet.fingerprint.unmatchedProjectionIds.length}
      />

      {isLoading && (
        <p className="text-sm text-zinc-400" role="status">
          Loading first-phase evidence packet…
        </p>
      )}

      {hasErrors && (
        <p
          className="rounded border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200"
          role="alert"
        >
          One or more Phase 1 endpoints are unavailable. Partial evidence is shown with explicit unavailable markers.
        </p>
      )}

      <CockpitToolbar
        filter={filter}
        candidates={packet.rankedCandidates}
        filteredCount={filteredCandidates.length}
        onFilterChange={handleFilterChange}
        onExport={handleExport}
        exportDisabled={
          packet.state === "loading"
          || packet.rankedCandidates.length === 0
          || packet.state === "unavailable"
        }
      />

      {exportMessage && (
        <p className="text-xs text-zinc-400" role="status" aria-live="polite">
          {exportMessage}
        </p>
      )}

      <RankedCandidatesPanel
        candidates={filteredCandidates}
        selectedId={selectedId}
        onSelect={setSelectedId}
        windowStart={windowStart}
        onWindowStartChange={setWindowStart}
      />
      <CandidateDetailPanel candidate={selectedCandidate} onClear={() => setSelectedId(null)} />
      <EvidencePillarsPanel pillars={packet.pillars} />
      <ControlPlanePanel slots={packet.controlPlanes} />
      <RunMetadataPanel
        fingerprint={packet.fingerprint}
        warnings={packet.warnings}
        blockedReasons={packet.blockedReasons}
        unavailableReasons={packet.unavailableReasons}
      />
    </div>
  );
}
