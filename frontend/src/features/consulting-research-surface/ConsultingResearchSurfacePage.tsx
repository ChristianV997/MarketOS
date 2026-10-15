import { useId, useState, type FormEvent } from "react";
import { ConsultingResearchSurface } from "./components/ConsultingResearchSurface.tsx";
import {
  buildLiveResearchRequest,
  liveResearchBoundaryCopy,
  type LiveResearchSession,
  type LiveResearchSourceObservation,
  type LiveResearchTransportKind,
} from "./contracts/liveResearchReport.ts";
import { buildSurfaceFixture } from "./fixtures/surfaceFixture.ts";
import {
  adaptLiveResearchResponse,
  unwrapLiveResearchEnvelope,
} from "./lib/adaptLiveResearchResponse.ts";
import {
  fetchLiveResearchReport,
} from "./lib/liveResearchReportApi.ts";
import {
  loadLocalResearchReportFile,
  localReportRejectionMessage,
} from "./lib/loadLocalResearchReport.ts";

export type OperatorSurfaceMode = "live" | "demo";

export interface ConsultingResearchSurfacePageProps {
  /**
   * Optional host-injected session. Production mounts currently pass nothing;
   * live requests then stay `auth_required` without network calls.
   */
  session?: LiveResearchSession | null;
  /** Injectable fetch for contract tests only. */
  fetchImpl?: typeof fetch;
  /** Test-only base URL override. */
  apiBaseUrl?: string;
}

/**
 * Mountable operator page at `/operator/consulting-research`.
 *
 * Operational path: authenticated same-origin live research (contract handoff).
 * Demo/fixture path: explicit opt-in only — never a silent fallback for live failures.
 */
export function ConsultingResearchSurfacePage(props: ConsultingResearchSurfacePageProps = {}) {
  const inputId = useId();
  const demoToggleId = useId();
  const [mode, setMode] = useState<OperatorSurfaceMode>("live");

  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [geography, setGeography] = useState("");
  const [language, setLanguage] = useState("");
  const [buyerContext, setBuyerContext] = useState("");

  const [liveKind, setLiveKind] = useState<LiveResearchTransportKind>("auth_required");
  const [liveReason, setLiveReason] = useState<string | null>("session_provider_unavailable");
  const [liveSources, setLiveSources] = useState<LiveResearchSourceObservation[]>([]);
  const [liveEvidenceLabel, setLiveEvidenceLabel] = useState<string | null>(null);

  const [packet, setPacket] = useState<unknown | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [sourceLabel, setSourceLabel] = useState("no packet loaded — awaiting authenticated live report");
  const [demoEnabled, setDemoEnabled] = useState(false);

  const boundary = liveResearchBoundaryCopy(liveKind, liveReason);

  function resetLiveOperational() {
    setLiveKind("auth_required");
    setLiveReason("session_provider_unavailable");
    setLiveSources([]);
    setLiveEvidenceLabel(null);
    setPacket(null);
    setErrorMessage(null);
    setLoading(false);
    setSourceLabel("no packet loaded — awaiting authenticated live report");
  }

  async function onLiveSubmit(event: FormEvent) {
    event.preventDefault();
    setMode("live");
    setLoading(true);
    setErrorMessage(null);
    setLiveKind("loading");
    setLiveReason(null);
    setLiveSources([]);
    setLiveEvidenceLabel(null);
    // Deliberately do NOT load fixture on failure.
    setPacket(null);
    setSourceLabel("live request in flight — no fixture fallback");

    const request = buildLiveResearchRequest({
      query,
      category,
      geography,
      language,
      buyer_context: buyerContext,
    });

    try {
      const result = await fetchLiveResearchReport({
        request,
        session: props.session ?? null,
        fetchImpl: props.fetchImpl,
        baseUrl: props.apiBaseUrl,
      });

      if (result.kind !== "ok") {
        setLiveKind(result.kind);
        setLiveReason(result.reason);
        setErrorMessage(liveResearchBoundaryCopy(result.kind, result.reason).body);
        setSourceLabel(`live transport · ${result.kind} · ${result.reason}`);
        return;
      }

      const adapted = adaptLiveResearchResponse(unwrapLiveResearchEnvelope(result.payload));
      if (!adapted.ok) {
        setLiveKind("error");
        setLiveReason(adapted.reason);
        setErrorMessage(liveResearchBoundaryCopy("error", adapted.reason).body);
        setSourceLabel(`live transport · rejected · ${adapted.reason}`);
        return;
      }

      setLiveKind("ok");
      setLiveReason(null);
      setLiveSources(adapted.sources);
      setLiveEvidenceLabel(adapted.evidenceLabel);
      setPacket(adapted.packet);
      setSourceLabel(`live transport packet · ${adapted.evidenceLabel} · not source verification · memory only`);
    } catch {
      setLiveKind("error");
      setLiveReason("unexpected_failure");
      setErrorMessage(liveResearchBoundaryCopy("error", "unexpected_failure").body);
      setSourceLabel("live transport · error · unexpected_failure");
    } finally {
      setLoading(false);
    }
  }

  async function onDemoFileChosen(fileList: FileList | null) {
    if (!demoEnabled || mode !== "demo") return;
    const file = fileList?.[0];
    if (!file) return;
    setLoading(true);
    setErrorMessage(null);
    try {
      const result = await loadLocalResearchReportFile(file);
      if (!result.ok) {
        setErrorMessage(localReportRejectionMessage(result.reason));
        return;
      }
      setPacket(result.packet);
      setSourceLabel(`Demo/fixture — not live evidence · ${result.source} · ${file.name}`);
    } catch {
      setErrorMessage("Selected report could not be read. Payload not shown.");
    } finally {
      setLoading(false);
    }
  }

  function enterDemoMode() {
    setDemoEnabled(true);
    setMode("demo");
    setLiveKind("idle");
    setLiveReason(null);
    setLiveSources([]);
    setLiveEvidenceLabel(null);
    setPacket(buildSurfaceFixture());
    setErrorMessage(null);
    setSourceLabel("Demo/fixture — not live evidence · fixture demo packet");
  }

  function resetDemoFixture() {
    if (!demoEnabled || mode !== "demo") return;
    setPacket(buildSurfaceFixture());
    setErrorMessage(null);
    setSourceLabel("Demo/fixture — not live evidence · fixture demo packet");
  }

  function leaveDemoForLive() {
    setMode("live");
    setDemoEnabled(false);
    resetLiveOperational();
  }

  return (
    <div className="min-w-0 space-y-3 p-3 sm:p-4">
      <section
        aria-labelledby="consulting-research-live-heading"
        className="rounded border border-zinc-700 bg-zinc-950/40 p-3 text-sm text-zinc-200"
      >
        <h2 id="consulting-research-live-heading" className="text-base font-semibold text-zinc-100">
          Live research (authenticated)
        </h2>
        <p className="mt-1 text-zinc-400">
          Operational path uses the same-origin API client and a verified session.
          Workspace authority is resolved by the server — this form does not accept a
          workspace id. No provider credentials are collected in the browser.
        </p>
        <div
          role="status"
          aria-live="polite"
          className="mt-3 rounded border border-amber-700/60 bg-amber-950/30 p-3 text-amber-50"
        >
          <p className="font-medium">{boundary.title}</p>
          <p className="mt-1 text-sm text-amber-100/90">{boundary.body}</p>
          {liveReason ? (
            <p className="mt-1 text-xs text-amber-200/80">Transport reason: {liveReason}</p>
          ) : null}
        </div>

        <form className="mt-3 grid gap-2 sm:grid-cols-2" onSubmit={onLiveSubmit}>
          <label className="block sm:col-span-2">
            <span className="text-xs text-zinc-400">Candidate / product query</span>
            <input
              required
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="mt-1 w-full rounded border border-zinc-600 bg-zinc-900 px-2 py-1.5 text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400"
              autoComplete="off"
            />
          </label>
          <label className="block">
            <span className="text-xs text-zinc-400">Category</span>
            <input
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              className="mt-1 w-full rounded border border-zinc-600 bg-zinc-900 px-2 py-1.5 text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400"
              autoComplete="off"
            />
          </label>
          <label className="block">
            <span className="text-xs text-zinc-400">Geography</span>
            <input
              value={geography}
              onChange={(event) => setGeography(event.target.value)}
              className="mt-1 w-full rounded border border-zinc-600 bg-zinc-900 px-2 py-1.5 text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400"
              autoComplete="off"
            />
          </label>
          <label className="block">
            <span className="text-xs text-zinc-400">Language</span>
            <input
              value={language}
              onChange={(event) => setLanguage(event.target.value)}
              className="mt-1 w-full rounded border border-zinc-600 bg-zinc-900 px-2 py-1.5 text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400"
              autoComplete="off"
            />
          </label>
          <label className="block sm:col-span-2">
            <span className="text-xs text-zinc-400">Buyer context</span>
            <textarea
              value={buyerContext}
              onChange={(event) => setBuyerContext(event.target.value)}
              rows={2}
              className="mt-1 w-full rounded border border-zinc-600 bg-zinc-900 px-2 py-1.5 text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400"
            />
          </label>
          <div className="flex flex-wrap gap-2 sm:col-span-2">
            <button
              type="submit"
              className="rounded border border-zinc-500 bg-zinc-800 px-3 py-1.5 text-sm text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400"
            >
              Request live report
            </button>
            <button
              type="button"
              className="rounded border border-zinc-600 px-3 py-1.5 text-sm text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400"
              onClick={() => {
                setMode("live");
                resetLiveOperational();
              }}
            >
              Reset live request
            </button>
          </div>
        </form>

        {liveSources.length > 0 ? (
          <div className="mt-3 overflow-x-auto" aria-label="Per-source live research status">
            <p className="mb-1 text-xs text-zinc-400">
              Per-source status{liveEvidenceLabel ? ` · evidence: ${liveEvidenceLabel}` : ""}
            </p>
            <table className="min-w-[32rem] text-left text-xs">
              <thead>
                <tr className="text-zinc-400">
                  <th scope="col">Source</th>
                  <th scope="col">Status</th>
                  <th scope="col">Observed at</th>
                  <th scope="col">Provenance</th>
                  <th scope="col">Detail</th>
                </tr>
              </thead>
              <tbody>
                {liveSources.map((source) => (
                  <tr key={source.source_id} className="border-t border-zinc-800">
                    <th scope="row" className="py-1 pr-2 font-medium text-zinc-200">{source.label}</th>
                    <td className="py-1 pr-2">{source.status}</td>
                    <td className="py-1 pr-2">{source.observed_at ?? "not reported"}</td>
                    <td className="py-1 pr-2">{source.provenance ?? "not reported"}</td>
                    <td className="py-1">{source.detail ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section
        aria-labelledby="consulting-research-demo-heading"
        className="rounded border border-dashed border-zinc-600 bg-zinc-950/20 p-3 text-sm text-zinc-300"
      >
        <h2 id="consulting-research-demo-heading" className="text-base font-semibold text-zinc-100">
          Demo/fixture — not live evidence
        </h2>
        <p className="mt-1 text-xs text-amber-100/90" role="note">
          Deliberate development path only. Fixture, manual, and local JSON are never live
          validation or launch authority. Failed live requests never fall back here automatically.
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <label htmlFor={demoToggleId} className="flex items-center gap-2 text-sm">
            <input
              id={demoToggleId}
              type="checkbox"
              checked={demoEnabled && mode === "demo"}
              onChange={(event) => {
                if (event.target.checked) enterDemoMode();
                else leaveDemoForLive();
              }}
            />
            Enable demo/fixture path
          </label>
          {mode === "demo" && demoEnabled ? (
            <>
              <label htmlFor={inputId} className="sr-only">
                Select local research report JSON file (demo only)
              </label>
              <input
                id={inputId}
                type="file"
                accept="application/json,.json"
                className="max-w-full text-sm file:mr-3 file:rounded file:border-0 file:bg-zinc-800 file:px-3 file:py-1.5 file:text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400"
                onChange={(event) => {
                  void onDemoFileChosen(event.target.files);
                  event.target.value = "";
                }}
              />
              <button
                type="button"
                className="rounded border border-zinc-600 px-3 py-1.5 text-sm text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400"
                onClick={resetDemoFixture}
              >
                Reset demo fixture
              </button>
            </>
          ) : null}
        </div>
      </section>

      <p className="text-xs text-zinc-500">Active source: {sourceLabel}</p>
      <p className="text-xs text-zinc-500">Operator mode: {mode === "demo" ? "Demo/fixture — not live evidence" : "Live (authenticated boundary)"}</p>

      {packet != null ? (
        <ConsultingResearchSurface
          packet={packet}
          loading={loading}
          errorMessage={errorMessage}
        />
      ) : (
        <section
          aria-labelledby="consulting-research-empty-heading"
          className="rounded border border-zinc-800 p-4 text-sm text-zinc-300"
        >
          <h2 id="consulting-research-empty-heading" className="text-base font-semibold text-zinc-100">
            No research packet loaded
          </h2>
          <p className="mt-1">
            {loading
              ? "Live request in progress…"
              : errorMessage ??
                "Authenticate and use a server-backed report, or deliberately enable the demo/fixture path. No approve, spend, publish, or launch controls are offered here."}
          </p>
        </section>
      )}
    </div>
  );
}
