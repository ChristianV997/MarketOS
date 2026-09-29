import type { EvidenceMode, SurfacePhase, SurfaceQualifier, SurfaceScope } from "../contracts/ownerResearch";

/** User-facing copy for every state. Each phase and qualifier reads differently on purpose. */

export const PHASE_COPY: Record<SurfaceScope, Record<Exclude<SurfacePhase, "ready">, { title: string; body: string }>> = {
  ranking: {
    loading: {
      title: "Loading ranked opportunities",
      body: "Reading the canonical ranking read model. Nothing is shown until it responds.",
    },
    error: {
      title: "Ranking could not be loaded",
      body: "A read failed or returned an invalid payload. No scores or ranks are shown.",
    },
    unavailable: {
      title: "Ranking read model unavailable",
      body: "The backend has not provided a ranking for this view. This is not an empty result and no scores are implied.",
    },
    empty: {
      title: "No ranked candidates",
      body: "The ranking read model responded with zero candidates. Order is never invented on the client.",
    },
  },
  portfolio: {
    loading: {
      title: "Loading curated portfolio",
      body: "Reading the portfolio read model. The count is unknown until it responds.",
    },
    error: {
      title: "Portfolio could not be loaded",
      body: "The request failed or returned an invalid payload. The count is unknown, not zero.",
    },
    unavailable: {
      title: "Portfolio read model unavailable",
      body: "No portfolio contract is being served for this workspace (or no workspace is selected). The count is unknown, not zero.",
    },
    empty: {
      title: "No active curated candidates",
      body: "The portfolio responded with zero distinct active candidates.",
    },
  },
};

export const QUALIFIER_COPY: Record<SurfaceQualifier, { title: string; body: string }> = {
  fixture: {
    title: "Fixture / simulation data",
    body: "These values are offline fixtures or simulations. They are not live results, not live supplier proof, and cannot enable draft research.",
  },
  stale: {
    title: "Stale evidence",
    body: "Freshness has expired or the backend reports degraded evidence. Treat this as dated and advisory.",
  },
  partial: {
    title: "Partial evidence",
    body: "Some sources, pillars or entries are missing, unavailable or were ignored as invalid. Missing values read \"Not reported\", never zero.",
  },
  blocked: {
    title: "Blocked by backend gates",
    body: "Readiness gates are blocking advancement. Review the reasons listed with this banner.",
  },
};

export const MODE_COPY: Record<EvidenceMode, { label: string; body: string }> = {
  fixture_only: { label: "Fixture only", body: "Offline screening fixture. Not live validated." },
  simulated: { label: "Simulated", body: "Derived planning values. Not observed live results." },
  manual: { label: "Manual import", body: "Operator-supplied screening evidence. Not live validated." },
  live_readonly: { label: "Live read-only", body: "The backend reports a read-only live path. This page still cannot change anything." },
  unknown: { label: "Mode not reported", body: "Provenance is not reported. Treat every value as unverified." },
};

export const SAFETY_NOTE =
  "Advisory research view. It never publishes, spends, orders, calls providers or changes data. Nothing here is live validated unless a value is labelled Live read-only.";
