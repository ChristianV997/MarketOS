/**
 * In-memory local JSON report loader for CompanyOS Approval Ledger review.
 *
 * Reads only an operator-selected File via the browser File API. No upload,
 * network, persistence, or arbitrary filesystem access.
 */

import { APPROVAL_LEDGER_REPORT_VERSION } from "../contracts/approvalLedger.ts";
import { safeDisplayText } from "./safeText.ts";

/** Hard cap for a single offline ledger JSON artifact (512 KiB). */
export const MAX_APPROVAL_LEDGER_REPORT_BYTES = 512 * 1024;

export type LocalReportSource = "demo_fixture" | "local_file";

export type LocalReportRejectCode =
  | "too_large"
  | "empty_file"
  | "read_failed"
  | "not_json"
  | "not_object"
  | "unsupported_version";

export type LocalReportLoadResult =
  | {
      ok: true;
      packet: Record<string, unknown>;
      fileName: string;
      byteLength: number;
    }
  | {
      ok: false;
      code: LocalReportRejectCode;
      /** Operator-safe message: never echoes file contents. */
      message: string;
      fileName: string | null;
    };

const GENERIC_INVALID =
  "Local report rejected. Choose a companyos-approval-ledger-v1 JSON artifact from scripts/run_companyos_approval_ledger.py.";

function utf8ByteLength(text: string): number {
  if (typeof TextEncoder !== "undefined") {
    return new TextEncoder().encode(text).length;
  }
  return text.length;
}

/**
 * Validate size, JSON object shape, and report_version.
 * Does not run the secret/safety adapter — callers must pass through adaptApprovalLedger.
 */
export function validateAndParseApprovalLedgerJson(
  text: string,
  options: { byteLength?: number; fileName?: string } = {},
): LocalReportLoadResult {
  const fileName = safeDisplayText(options.fileName ?? "", 120) || null;
  const byteLength = typeof options.byteLength === "number" && Number.isFinite(options.byteLength)
    ? options.byteLength
    : utf8ByteLength(text);

  if (byteLength <= 0 || text.trim() === "") {
    return {
      ok: false,
      code: "empty_file",
      message: "Selected file is empty.",
      fileName,
    };
  }
  if (byteLength > MAX_APPROVAL_LEDGER_REPORT_BYTES) {
    return {
      ok: false,
      code: "too_large",
      message: `Report exceeds the ${MAX_APPROVAL_LEDGER_REPORT_BYTES} byte limit.`,
      fileName,
    };
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return {
      ok: false,
      code: "not_json",
      message: GENERIC_INVALID,
      fileName,
    };
  }

  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return {
      ok: false,
      code: "not_object",
      message: GENERIC_INVALID,
      fileName,
    };
  }

  const packet = parsed as Record<string, unknown>;
  if (String(packet.report_version ?? "") !== APPROVAL_LEDGER_REPORT_VERSION) {
    return {
      ok: false,
      code: "unsupported_version",
      message: GENERIC_INVALID,
      fileName,
    };
  }

  return {
    ok: true,
    packet,
    fileName: fileName || "local-report.json",
    byteLength,
  };
}

/** Read a browser File into memory and validate it as an Approval Ledger report. */
export async function readLocalApprovalLedgerFile(file: File): Promise<LocalReportLoadResult> {
  const fileName = safeDisplayText(file.name, 120) || "local-report.json";
  if (file.size > MAX_APPROVAL_LEDGER_REPORT_BYTES) {
    return {
      ok: false,
      code: "too_large",
      message: `Report exceeds the ${MAX_APPROVAL_LEDGER_REPORT_BYTES} byte limit.`,
      fileName,
    };
  }
  if (file.size <= 0) {
    return {
      ok: false,
      code: "empty_file",
      message: "Selected file is empty.",
      fileName,
    };
  }

  let text: string;
  try {
    text = await file.text();
  } catch {
    return {
      ok: false,
      code: "read_failed",
      message: "Could not read the selected file in this browser.",
      fileName,
    };
  }

  return validateAndParseApprovalLedgerJson(text, {
    byteLength: file.size,
    fileName,
  });
}
