import { CockpitStatusBanner } from "@/features/first-phase-cockpit/components/CockpitStatusBanner";
import { ControlPlanePanel } from "@/features/first-phase-cockpit/components/ControlPlanePanel";
import { EvidencePillarsPanel } from "@/features/first-phase-cockpit/components/EvidencePillarsPanel";
import { RankedCandidatesPanel } from "@/features/first-phase-cockpit/components/RankedCandidatesPanel";
import { RunMetadataPanel } from "@/features/first-phase-cockpit/components/RunMetadataPanel";
import { useFirstPhaseEvidenceCockpit } from "@/features/first-phase-cockpit/hooks/useFirstPhaseEvidenceCockpit";

const SAFETY_BADGES = [
  ["Read-only", "border-sky-500/30 bg-sky-500/10 text-sky-300"],
  ["Advisory", "border-violet-500/30 bg-violet-500/10 text-violet-300"],
  ["No launch authority", "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"],
  ["No credentials in browser", "border-amber-500/30 bg-amber-500/10 text-amber-300"],
] as const;

export default function FirstPhaseEvidenceCockpitPage() {
  const { packet, isLoading, hasErrors } = useFirstPhaseEvidenceCockpit();

  return (
    <div className="mx-auto max-w-7xl space-y-5 p-6">
      <header className="space-y-3">
        <div>
          <h1 className="text-xl font-semibold text-zinc-100">First-phase evidence cockpit</h1>
          <p className="mt-1 text-sm text-zinc-500">
            Composes existing Phase 1 API contracts without recalculating rankings or granting external authority.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
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
      />

      {isLoading && (
        <p className="text-sm text-zinc-400">Loading first-phase evidence packet…</p>
      )}

      {hasErrors && (
        <p className="rounded border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
          One or more Phase 1 endpoints are unavailable. Partial evidence is shown with explicit unavailable markers.
        </p>
      )}

      <RankedCandidatesPanel candidates={packet.rankedCandidates} />
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
