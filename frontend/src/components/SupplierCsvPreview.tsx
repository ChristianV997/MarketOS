import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  FileText,
  AlertTriangle,
  CheckCircle2,
  AlertCircle,
  Upload,
  X,
  ShieldAlert,
  Info,
} from "lucide-react";
import {
  parseSupplierCsvText,
  MAX_SUPPLIER_CSV_BYTES,
  MAX_SUPPLIER_CSV_ROWS,
  type SupplierCsvPreviewResult,
  type SupplierCsvRowPreview,
} from "../lib/supplierCsvParser";

export interface SupplierCsvPreviewProps {
  /** Optional initial raw CSV text (for testing, controlled mode, or storybook) */
  initialCsvText?: string;
  /** Optional file passed from parent */
  file?: File | null;
  /** Callback fired whenever preview changes or is cleared. Transmits local preview data only. */
  onPreviewChange?: (preview: SupplierCsvPreviewResult | null) => void;
  /** Optional extra CSS class name */
  className?: string;
  /** Optional selected candidate ID to highlight matching rows */
  selectedCandidateId?: string | null;
  /** Optional callback when operator clicks a row with a valid candidate ID */
  onSelectCandidateId?: (candidateId: string) => void;
}

/**
 * SupplierCsvPreview
 *
 * Local-only, zero-transmission component for inspecting supplier catalog CSV files
 * before import into MarketOS.
 *
 * Invariants:
 * - Local-only: No network calls, uploads, persistence, or background transmissions.
 * - Manual/Unverified evidence: Visibly labeled as unverified manual evidence.
 * - Numeric integrity: Missing unit/shipping costs are displayed as 'missing' and never coerced to 0.
 * - Identity integrity: Never derives candidate ID from product display name.
 */
export function SupplierCsvPreview({
  initialCsvText,
  file,
  onPreviewChange,
  className = "",
  selectedCandidateId,
  onSelectCandidateId,
}: SupplierCsvPreviewProps) {
  const [csvText, setCsvText] = useState<string>(initialCsvText || "");
  const [fileName, setFileName] = useState<string>(file?.name || "");
  const [preview, setPreview] = useState<SupplierCsvPreviewResult | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Parse whenever csvText changes
  useEffect(() => {
    if (!csvText.trim()) {
      setPreview(null);
      onPreviewChange?.(null);
      return;
    }
    const result = parseSupplierCsvText(csvText, fileName);
    setPreview(result);
    onPreviewChange?.(result);
  }, [csvText, fileName, onPreviewChange]);

  // Handle external file prop changes
  useEffect(() => {
    if (file) {
      setParseError(null);
      setFileName(file.name);
      if (file.size > MAX_SUPPLIER_CSV_BYTES) {
        setCsvText("");
        setParseError("File exceeds maximum size of 256 KB.");
        return;
      }
      file.text().then((text) => {
        setCsvText(text);
      }).catch(() => {
        setCsvText("");
        setParseError("Failed to read file.");
      });
    }
  }, [file]);

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (!selected) return;
    setParseError(null);
    if (selected.size > MAX_SUPPLIER_CSV_BYTES) {
      setParseError("File exceeds maximum size of 256 KB.");
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }
    setFileName(selected.name);
    selected.text().then((text) => {
      setCsvText(text);
    }).catch(() => {
      setCsvText("");
      setParseError("Failed to read file.");
    });
  }, []);

  const handleDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    const droppedFile = e.dataTransfer.files?.[0];
    if (!droppedFile) return;
    setParseError(null);
    if (!droppedFile.name.endsWith(".csv")) {
      setParseError("Only .csv files are supported.");
      return;
    }
    if (droppedFile.size > MAX_SUPPLIER_CSV_BYTES) {
      setParseError("File exceeds maximum size of 256 KB.");
      return;
    }
    setFileName(droppedFile.name);
    droppedFile.text().then((text) => {
      setCsvText(text);
    }).catch(() => {
      setCsvText("");
      setParseError("Failed to read file.");
    });
  }, []);

  const handleClear = useCallback(() => {
    setCsvText("");
    setFileName("");
    setPreview(null);
    setParseError(null);
    onPreviewChange?.(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }, [onPreviewChange]);

  return (
    <div
      className={`space-y-4 rounded-lg border border-gray-800 bg-gray-900 p-5 text-gray-100 ${className}`}
      data-testid="supplier-csv-preview"
    >
      {/* Prominent Manual / Unverified Evidence Banner */}
      <div
        role="status"
        aria-live="polite"
        className="flex items-start gap-3 rounded-md border border-amber-600/50 bg-amber-950/40 p-3 text-amber-200"
        data-testid="manual-evidence-banner"
      >
        <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" aria-hidden="true" />
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="font-semibold tracking-wide uppercase text-xs text-amber-300">
              Manual / Unverified Evidence
            </span>
            <span className="rounded bg-amber-900/60 px-1.5 py-0.5 text-[10px] font-mono text-amber-300 border border-amber-700/50">
              evidence_mode=manual_import
            </span>
          </div>
          <p className="text-xs text-amber-200/90 leading-relaxed">
            Local preview only. Imported catalog rows are offline manual evidence and do not constitute
            live supplier proof, validated inventory, or purchase authority.
          </p>
        </div>
      </div>

      {/* File dropzone / upload area */}
      {!preview ? (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors cursor-pointer ${
            isDragging
              ? "border-blue-500 bg-blue-950/20 text-blue-200"
              : "border-gray-700 bg-gray-950/50 hover:border-gray-600 text-gray-400"
          }`}
          role="button"
          tabIndex={0}
          aria-label="Upload supplier CSV file"
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              fileInputRef.current?.click();
            }
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={handleFileChange}
            aria-hidden="true"
          />
          <Upload className="mb-2 h-8 w-8 text-gray-400" aria-hidden="true" />
          <p className="text-sm font-medium text-gray-200">
            Select or drag & drop a supplier catalog CSV
          </p>
          <p className="text-xs text-gray-500 mt-1">
            Local browser preview only — no files are transmitted or persisted.
          </p>
          {parseError && (
            <div className="mt-4 flex items-center gap-2 rounded bg-red-950/40 px-3 py-2 text-sm text-red-400 border border-red-800/50">
              <AlertTriangle className="h-4 w-4" />
              <span>{parseError}</span>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          {/* Header Bar with Filename and Clear Action */}
          <div className="flex items-center justify-between border-b border-gray-800 pb-3">
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-blue-400" aria-hidden="true" />
              <span className="text-sm font-medium text-gray-200">
                {preview.fileName || "supplier-catalog.csv"}
              </span>
              <span className="text-xs text-gray-500">
                ({preview.totalRows} {preview.totalRows === 1 ? "row" : "rows"})
              </span>
            </div>
            <button
              type="button"
              onClick={handleClear}
              className="flex items-center gap-1 rounded px-2 py-1 text-xs text-gray-400 hover:bg-gray-800 hover:text-gray-200"
              aria-label="Clear CSV preview"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Clear</span>
            </button>
          </div>

          {/* Validation Metrics & Header Summary */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {/* Row validation stats */}
            <div className="rounded border border-gray-800 bg-gray-950/60 p-3 space-y-1">
              <div className="text-xs text-gray-400">Row Validation</div>
              <div className="flex items-baseline gap-2">
                <span className="text-xl font-bold text-gray-100 font-mono">
                  {preview.validRowCount}
                </span>
                <span className="text-xs text-green-400">valid</span>
                {preview.invalidRowCount > 0 && (
                  <>
                    <span className="text-gray-600">/</span>
                    <span className="text-xl font-bold text-red-400 font-mono">
                      {preview.invalidRowCount}
                    </span>
                    <span className="text-xs text-red-400">with issues</span>
                  </>
                )}
              </div>
            </div>

            {/* Recognized headers */}
            <div className="rounded border border-gray-800 bg-gray-950/60 p-3 space-y-1 md:col-span-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">Recognized Headers</span>
                <span className="text-[11px] font-mono text-gray-500">
                  {preview.recognizedHeaders.length} mapped / {preview.rawHeaders.length} total
                </span>
              </div>
              <div className="flex flex-wrap gap-1 pt-1">
                {preview.recognizedHeaders.length > 0 ? (
                  preview.recognizedHeaders.map((header) => (
                    <span
                      key={header}
                      className="rounded bg-blue-950/70 border border-blue-800/60 px-1.5 py-0.5 text-[11px] font-mono text-blue-300"
                    >
                      {header}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-red-400 flex items-center gap-1">
                    <AlertCircle className="h-3 w-3" /> No recognized headers found
                  </span>
                )}
                {preview.unrecognizedHeaders.map((header) => (
                  <span
                    key={header}
                    className="rounded bg-gray-800/80 border border-gray-700 px-1.5 py-0.5 text-[11px] font-mono text-gray-400"
                    title="Unrecognized column header"
                  >
                    {header} (unknown)
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* Missing Candidate ID Column Alert */}
          {preview.missingCandidateIdColumn && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded border border-red-800/70 bg-red-950/40 p-3 text-red-200 text-xs"
              data-testid="missing-candidate-id-alert"
            >
              <AlertTriangle className="h-4 w-4 shrink-0 text-red-400 mt-0.5" aria-hidden="true" />
              <div>
                <span className="font-semibold text-red-300">Missing Candidate ID column: </span>
                CSV contains no candidate ID or product ID alias. Candidate IDs are never derived from product display names.
              </div>
            </div>
          )}

          {/* File Size Exceeded Alert */}
          {preview.fileLevelIssues.includes("file_size_exceeds_limit") && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded border border-red-800/70 bg-red-950/40 p-3 text-red-200 text-xs"
              data-testid="file-size-exceeded-alert"
            >
              <AlertTriangle className="h-4 w-4 shrink-0 text-red-400 mt-0.5" aria-hidden="true" />
              <div>
                <span className="font-semibold text-red-300">File size limit exceeded: </span>
                File exceeds maximum supported size of 256 KB.
              </div>
            </div>
          )}

          {/* Malformed Encoding Alert */}
          {preview.fileLevelIssues.includes("malformed_encoding") && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded border border-amber-800/70 bg-amber-950/40 p-3 text-amber-200 text-xs"
              data-testid="malformed-encoding-alert"
            >
              <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400 mt-0.5" aria-hidden="true" />
              <div>
                <span className="font-semibold text-amber-300">Encoding warning: </span>
                File contains null bytes or replacement characters indicating malformed encoding.
              </div>
            </div>
          )}

          {/* Row Limit Truncated Warning */}
          {preview.fileLevelIssues.includes("preview_rows_truncated") && (
            <div
              role="status"
              className="flex items-start gap-2 rounded border border-amber-800/70 bg-amber-950/40 p-3 text-amber-200 text-xs"
              data-testid="preview-rows-truncated-notice"
            >
              <AlertCircle className="h-4 w-4 shrink-0 text-amber-400 mt-0.5" aria-hidden="true" />
              <div>
                <span className="font-semibold text-amber-300">Row limit reached: </span>
                Showing first 100 rows for preview inspection (limit: 100 rows).
              </div>
            </div>
          )}

          {/* Rows Preview Table or Empty Notice */}
          {preview.totalRows === 0 ? (
            <div
              role="status"
              className="flex items-center justify-center gap-2 rounded border border-gray-800 bg-gray-950/60 p-6 text-sm text-gray-400"
              data-testid="empty-csv-notice"
            >
              <Info className="h-4 w-4 text-gray-500" aria-hidden="true" />
              <span>No data rows found in CSV. Ensure the file contains headers and at least one data row.</span>
            </div>
          ) : (
            <div className="overflow-x-auto rounded border border-gray-800">
              <table
                className="w-full text-left text-xs"
                aria-label="Supplier Catalog CSV Preview"
              >
                <thead className="border-b border-gray-800 bg-gray-950 font-medium text-gray-400">
                  <tr>
                    <th scope="col" className="px-3 py-2 w-12 text-center">#</th>
                    <th scope="col" className="px-3 py-2 w-16">Status</th>
                    <th scope="col" className="px-3 py-2">Candidate ID</th>
                    <th scope="col" className="px-3 py-2">Product Name</th>
                    <th scope="col" className="px-3 py-2 w-20">Supplier</th>
                    <th scope="col" className="px-3 py-2 text-right">Unit Cost</th>
                    <th scope="col" className="px-3 py-2 text-right">Shipping</th>
                    <th scope="col" className="px-3 py-2 text-right">Landed Cost</th>
                    <th scope="col" className="px-3 py-2">Issues</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800/60 font-mono">
                  {preview.rows.map((row) => {
                    const isSelected = Boolean(
                      selectedCandidateId && row.candidateId && row.candidateId === selectedCandidateId
                    );
                    const isSelectable = Boolean(row.candidateId && row.isValid && onSelectCandidateId);
                    return (
                      <tr
                        key={row.rowIndex}
                        role={isSelectable ? "button" : undefined}
                        tabIndex={isSelectable ? 0 : undefined}
                        aria-selected={isSelected}
                        onClick={() => {
                          if (row.candidateId && row.isValid) {
                            onSelectCandidateId?.(row.candidateId);
                          }
                        }}
                        onKeyDown={(e) => {
                          if (isSelectable && (e.key === "Enter" || e.key === " ")) {
                            e.preventDefault();
                            if (row.candidateId && row.isValid) {
                              onSelectCandidateId?.(row.candidateId);
                            }
                          }
                        }}
                        className={`hover:bg-gray-800/40 focus:outline-none ${
                          !row.isValid ? "bg-red-950/10" : ""
                        } ${
                          isSelected ? "bg-indigo-950/50 ring-1 ring-inset ring-indigo-500/50" : ""
                        } ${
                          isSelectable ? "cursor-pointer focus:ring-2 focus:ring-inset focus:ring-indigo-400" : ""
                        }`}
                        title={
                          isSelectable
                            ? `Select candidate "${row.candidateId}" in cockpit (Press Enter or Space)`
                            : undefined
                        }
                      >
                      <td className="px-3 py-2 text-center text-gray-500 font-sans">
                        {row.rowIndex}
                      </td>
                      <td className="px-3 py-2">
                        {row.isValid ? (
                          <span className="inline-flex items-center text-green-400" title="Valid">
                            <CheckCircle2 className="h-3.5 w-3.5" aria-label="Valid row" />
                          </span>
                        ) : (
                          <span className="inline-flex items-center text-red-400" title="Has issues">
                            <AlertTriangle className="h-3.5 w-3.5" aria-label="Row with issues" />
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 font-medium">
                        {row.candidateId ? (
                          <span className="text-gray-200 flex items-center gap-1.5">
                            <span>{row.candidateId}</span>
                            {isSelected && (
                              <span className="rounded bg-indigo-500/20 px-1 py-0.2 text-[9px] text-indigo-300 font-sans uppercase">
                                Selected
                              </span>
                            )}
                          </span>
                        ) : (
                          <span className="text-red-400 italic font-sans text-[11px]">
                            [missing ID]
                          </span>
                        )}
                      </td>
                    <td className="px-3 py-2 text-gray-400 max-w-xs truncate font-sans">
                      {row.productName || "–"}
                    </td>
                    <td className="px-3 py-2 text-gray-300 uppercase text-[11px]">
                      {row.supplier}
                    </td>
                    {/* Unit Cost */}
                    <td className="px-3 py-2 text-right">
                      {row.isUnitCostMissing ? (
                        <span className="text-gray-500 italic font-sans text-[11px]">
                          missing
                        </span>
                      ) : row.isUnitCostExplicitZero ? (
                        <span className="text-blue-300 font-bold" title="Explicit Zero Cost">
                          {row.unitCostDisplay}
                        </span>
                      ) : (
                        <span className="text-gray-200">{row.unitCostDisplay}</span>
                      )}
                    </td>
                    {/* Shipping Cost */}
                    <td className="px-3 py-2 text-right">
                      {row.isShippingCostMissing ? (
                        <span className="text-gray-500 italic font-sans text-[11px]">
                          missing
                        </span>
                      ) : row.isShippingCostExplicitZero ? (
                        <span className="text-blue-300 font-bold" title="Explicit Zero Shipping">
                          {row.shippingCostDisplay}
                        </span>
                      ) : (
                        <span className="text-gray-200">{row.shippingCostDisplay}</span>
                      )}
                    </td>
                    {/* Landed Cost */}
                    <td className="px-3 py-2 text-right">
                      {row.estimatedLandedCost !== null ? (
                        <span className="text-gray-100 font-semibold">
                          {row.estimatedLandedCost.toFixed(2)} {row.currency}
                        </span>
                      ) : (
                        <span className="text-gray-600 italic font-sans text-[11px]">
                          –
                        </span>
                      )}
                    </td>
                    {/* Issues pill */}
                    <td className="px-3 py-2 font-sans">
                      {row.validationIssues.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {row.validationIssues.map((issue) => (
                            <span
                              key={issue}
                              className="rounded bg-red-950/80 border border-red-800/80 px-1 py-0.2 text-[10px] text-red-300"
                            >
                              {issue}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-green-500 text-[11px]">none</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            </table>
          </div>
        )}
      </div>
    )}
  </div>
);
}
