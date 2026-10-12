import { useId, useState } from "react";
import { ConsultingResearchSurface } from "./components/ConsultingResearchSurface.tsx";
import { buildSurfaceFixture } from "./fixtures/surfaceFixture.ts";
import {
  loadLocalResearchReportFile,
  localReportRejectionMessage,
} from "./lib/loadLocalResearchReport.ts";

/**
 * Mountable operator page at `/operator/consulting-research`.
 * Loads a locally selected Market Research / surface JSON in memory only.
 * No upload, browser persistence, provider calls, or network requests.
 */
export function ConsultingResearchSurfacePage() {
  const inputId = useId();
  const [packet, setPacket] = useState<unknown>(() => buildSurfaceFixture());
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [sourceLabel, setSourceLabel] = useState("fixture demo packet");

  async function onFileChosen(fileList: FileList | null) {
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
      setSourceLabel(`${result.source} · memory only · ${file.name}`);
    } catch {
      setErrorMessage("Selected report could not be read. Payload not shown.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-w-0 space-y-3 p-3 sm:p-4">
      <section
        aria-labelledby="consulting-research-load-heading"
        className="rounded border border-zinc-700 bg-zinc-950/40 p-3 text-sm text-zinc-200"
      >
        <h2 id="consulting-research-load-heading" className="text-base font-semibold text-zinc-100">
          Load local Market Research JSON
        </h2>
        <p className="mt-1 text-zinc-400">
          Choose an offline JSON report from <code>scripts/market_research_report.py</code>
          {" "}(<code>market-research-service-v1</code>) or a
          {" "}<code>consulting-research-surface-v1</code> packet. Parsing stays in browser memory.
          No upload, local storage, provider call, or external request.
        </p>
        <p className="mt-2 text-xs text-amber-100/90" role="note">
          Fixture, manual, assumed, and sanitized copies are never live validation or launch authority.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <label htmlFor={inputId} className="sr-only">
            Select local research report JSON file
          </label>
          <input
            id={inputId}
            type="file"
            accept="application/json,.json"
            className="max-w-full text-sm file:mr-3 file:rounded file:border-0 file:bg-zinc-800 file:px-3 file:py-1.5 file:text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400"
            onChange={(event) => {
              void onFileChosen(event.target.files);
              event.target.value = "";
            }}
          />
          <button
            type="button"
            className="rounded border border-zinc-600 px-3 py-1.5 text-sm text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400"
            onClick={() => {
              setPacket(buildSurfaceFixture());
              setErrorMessage(null);
              setSourceLabel("fixture demo packet");
            }}
          >
            Reset to fixture
          </button>
        </div>
        <p className="mt-2 text-xs text-zinc-500">Active source: {sourceLabel}</p>
      </section>

      <ConsultingResearchSurface
        packet={packet}
        loading={loading}
        errorMessage={errorMessage}
      />
    </div>
  );
}
