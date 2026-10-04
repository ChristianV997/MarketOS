import type { SurfacePhase, SurfaceQualifier, SurfaceScope } from "../contracts/ownerResearch";
import { PHASE_COPY, QUALIFIER_COPY } from "../lib/stateCopy";

const PHASE_STYLE: Record<Exclude<SurfacePhase, "ready">, string> = {
  loading: "border-zinc-600 bg-zinc-900/60 text-zinc-200",
  error: "border-red-500/50 bg-red-500/10 text-red-100",
  unavailable: "border-amber-500/50 bg-amber-500/10 text-amber-100",
  empty: "border-zinc-600 bg-zinc-900/40 text-zinc-200",
};

const QUALIFIER_STYLE: Record<SurfaceQualifier, string> = {
  fixture: "border-violet-400/60 bg-violet-500/10 text-violet-100",
  stale: "border-orange-400/60 bg-orange-500/10 text-orange-100",
  partial: "border-sky-400/60 bg-sky-500/10 text-sky-100",
  blocked: "border-red-400/60 bg-red-500/10 text-red-100",
};

const QUALIFIER_ORDER: readonly SurfaceQualifier[] = ["fixture", "stale", "partial", "blocked"];

const MAX_REASONS_SHOWN = 20;

export const SCOPE_LABEL: Record<SurfaceScope, string> = {
  ranking: "Ranking",
  portfolio: "Portfolio",
};

/**
 * The exclusive phase of one scope (loading / error / unavailable / empty) and
 * its backend reason codes. Errors use role="alert", the rest role="status".
 * Renders nothing when the scope is ready and has no reasons to show.
 */
export function SurfaceStateBanner({
  scope,
  phase,
  reasons,
  openReasons = false,
}: {
  scope: SurfaceScope;
  phase: SurfacePhase;
  reasons: readonly string[];
  /** Expand the reason list by default (blocked gates); errors and unavailable always expand. */
  openReasons?: boolean;
}) {
  const shownReasons = reasons.slice(0, MAX_REASONS_SHOWN);
  const hiddenReasons = reasons.length - shownReasons.length;
  if (phase === "ready" && reasons.length === 0) return null;

  const phaseCopy = phase === "ready" ? null : PHASE_COPY[scope][phase];

  return (
    <section
      aria-label={`${SCOPE_LABEL[scope]} state`}
      data-surface-scope={scope}
      data-surface-phase={phase}
      className="space-y-2"
    >
      {phaseCopy ? (
        <div
          role={phase === "error" ? "alert" : "status"}
          data-state-banner={phase}
          className={`rounded-lg border p-3 text-sm ${PHASE_STYLE[phase as Exclude<SurfacePhase, "ready">]}`}
        >
          <p className="font-medium">{phaseCopy.title}</p>
          <p className="mt-1 opacity-90">{phaseCopy.body}</p>
        </div>
      ) : null}

      {reasons.length > 0 ? (
        <details
          open={phase === "error" || phase === "unavailable" || openReasons}
          className="rounded-lg border border-zinc-700 bg-zinc-900/40 px-3 text-xs text-zinc-300"
        >
          <summary className="cursor-pointer py-3.5 text-zinc-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400">
            {SCOPE_LABEL[scope]} details ({reasons.length})
          </summary>
          <ul className="list-disc space-y-1 pb-3 pl-5">
            {shownReasons.map((reason) => (
              <li key={reason} className="font-mono [overflow-wrap:anywhere]">{reason}</li>
            ))}
            {hiddenReasons > 0 ? <li data-reasons-hidden={hiddenReasons}>+{hiddenReasons} more not shown</li> : null}
          </ul>
        </details>
      ) : null}
    </section>
  );
}

/** One banner per qualifier, merged across scopes so the same warning is never shown twice. */
export function mergeQualifiers(
  scopes: ReadonlyArray<{ scope: SurfaceScope; qualifiers: readonly SurfaceQualifier[] }>,
): Array<{ qualifier: SurfaceQualifier; scopes: SurfaceScope[] }> {
  const merged: Array<{ qualifier: SurfaceQualifier; scopes: SurfaceScope[] }> = [];
  for (const qualifier of QUALIFIER_ORDER) {
    const affected = scopes.filter((entry) => entry.qualifiers.includes(qualifier)).map((entry) => entry.scope);
    if (affected.length > 0) merged.push({ qualifier, scopes: affected });
  }
  return merged;
}

/**
 * Fixture / stale / partial / blocked banners. Each qualifier has distinct copy
 * and role="status", and states which scopes it applies to.
 */
export function QualifierBanners({
  scopes,
}: {
  scopes: ReadonlyArray<{ scope: SurfaceScope; qualifiers: readonly SurfaceQualifier[] }>;
}) {
  const merged = mergeQualifiers(scopes);
  if (merged.length === 0) return null;
  return (
    <section aria-label="Evidence qualifiers" className="space-y-2">
      {merged.map(({ qualifier, scopes: affected }) => (
        <div
          key={qualifier}
          role="status"
          data-qualifier-banner={qualifier}
          data-qualifier-scopes={affected.join(" ")}
          className={`rounded-lg border p-3 text-sm ${QUALIFIER_STYLE[qualifier]}`}
        >
          <p className="font-medium">{QUALIFIER_COPY[qualifier].title}</p>
          <p className="mt-1 opacity-90">{QUALIFIER_COPY[qualifier].body}</p>
          <p className="mt-1 text-xs opacity-80">Applies to: {affected.map((scope) => SCOPE_LABEL[scope]).join(" and ")}</p>
        </div>
      ))}
    </section>
  );
}
