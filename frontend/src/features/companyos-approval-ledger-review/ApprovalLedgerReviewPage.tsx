import { useCallback, useId, useRef, useState } from "react";
import { ApprovalLedgerReview } from "./components/ApprovalLedgerReview.tsx";
import { buildApprovalLedgerFixture } from "./fixtures/ledgerFixture.ts";
import { adaptApprovalLedger } from "./lib/adaptApprovalLedger.ts";
import {
  MAX_APPROVAL_LEDGER_REPORT_BYTES,
  readLocalApprovalLedgerFile,
  type LocalReportSource,
} from "./lib/loadLocalApprovalLedgerReport.ts";
import { safeDisplayText } from "./lib/safeText.ts";

type PageMode = "review" | "loading" | "invalid";

/**
 * Mountable page for offline Approval Ledger review.
 * Registered at `/operator/approval-ledger` via `frontend/src/main.tsx` under Shell.
 * Sidebar/nav ownership stays with the shell lane; this page is review-only.
 *
 * Operators may load a local `companyos-approval-ledger-v1` JSON produced by
 * `scripts/run_companyos_approval_ledger.py`. The file stays in browser memory only.
 */
export function ApprovalLedgerReviewPage() {
  const fileInputId = useId();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [source, setSource] = useState<LocalReportSource>("demo_fixture");
  const [packet, setPacket] = useState<unknown>(() => buildApprovalLedgerFixture());
  const [mode, setMode] = useState<PageMode>("review");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [fileLabel, setFileLabel] = useState<string | null>(null);

  const useDemoFixture = useCallback(() => {
    setSource("demo_fixture");
    setPacket(buildApprovalLedgerFixture());
    setMode("review");
    setErrorMessage(null);
    setFileLabel(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, []);

  const onFileChosen = useCallback(async (file: File | undefined) => {
    if (!file) return;
    setMode("loading");
    setErrorMessage(null);
    setFileLabel(safeDisplayText(file.name, 120) || "local-report.json");

    const loaded = await readLocalApprovalLedgerFile(file);
    if (!loaded.ok) {
      setSource("local_file");
      setPacket(null);
      setMode("invalid");
      setErrorMessage(loaded.message);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }

    const adapted = adaptApprovalLedger(loaded.packet, { source: "local_file" });
    if (adapted.rejected) {
      setSource("local_file");
      setPacket(null);
      setMode("invalid");
      // Generic operator message — never echo rejected payload contents.
      setErrorMessage(
        adapted.reason === "prohibited_field"
          ? "Local report rejected: prohibited or secret-shaped content."
          : adapted.reason === "unsafe_safety_summary"
            ? "Local report rejected: safety summary claimed live or mutating capability."
            : "Local report rejected after sanitizer checks. No decisions were invented.",
      );
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }

    setSource("local_file");
    setPacket(loaded.packet);
    setFileLabel(loaded.fileName);
    setMode("review");
    setErrorMessage(null);
  }, []);

  const loading = mode === "loading";
  const reviewPacket = mode === "invalid" ? null : packet;
  const reviewError = mode === "invalid" ? errorMessage : null;

  return (
    <div className="min-w-0 space-y-4" data-testid="companyos-approval-ledger-page">
      <section
        aria-labelledby="approval-ledger-local-source-heading"
        className="space-y-3 border-b border-zinc-800 p-3 sm:p-4 text-zinc-100"
      >
        <h2 id="approval-ledger-local-source-heading" className="text-lg font-medium">
          Local report source
        </h2>
        <p className="text-sm text-zinc-300">
          Choose an offline JSON artifact from{" "}
          <code className="text-zinc-200">scripts/run_companyos_approval_ledger.py</code>
          {" "}(<code className="text-zinc-200">companyos-approval-ledger-v1</code>).
          The file is read in this browser only — no upload, network request, or local persistence.
          Max size {MAX_APPROVAL_LEDGER_REPORT_BYTES.toLocaleString()} bytes.
        </p>

        <div
          role="status"
          aria-live="polite"
          className="rounded border border-zinc-700 bg-zinc-950/60 p-3 text-sm"
          data-testid="approval-ledger-source-banner"
          data-source={source}
        >
          {source === "demo_fixture" ? (
            <p>
              Showing the <strong className="font-semibold">built-in demo fixture</strong>.
              This is not an operator-selected report.
            </p>
          ) : (
            <p>
              Showing an <strong className="font-semibold">operator-selected local report</strong>
              {fileLabel ? (
                <>
                  {" "}
                  (<span className="font-mono text-zinc-200">{safeDisplayText(fileLabel, 120)}</span>)
                </>
              ) : null}
              . Held in memory only.
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <label htmlFor={fileInputId} className="sr-only">
            Select local Approval Ledger JSON report
          </label>
          <input
            id={fileInputId}
            ref={fileInputRef}
            type="file"
            accept=".json,application/json"
            className="block max-w-full text-sm text-zinc-200 file:mr-3 file:rounded file:border file:border-zinc-600 file:bg-zinc-900 file:px-3 file:py-1.5 file:text-zinc-100"
            data-testid="approval-ledger-file-input"
            disabled={loading}
            onChange={(event) => {
              const next = event.target.files?.[0];
              void onFileChosen(next);
            }}
          />
          <button
            type="button"
            className="rounded border border-zinc-600 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400 disabled:opacity-50"
            data-testid="approval-ledger-use-demo"
            disabled={loading}
            onClick={useDemoFixture}
          >
            Use demo fixture
          </button>
        </div>
      </section>

      <ApprovalLedgerReview
        packet={reviewPacket}
        loading={loading}
        errorMessage={reviewError}
        source={source}
        fileLabel={fileLabel}
        adaptSource={source}
      />
    </div>
  );
}
