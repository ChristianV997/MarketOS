// Thin adapter: feeds contract cases to the REAL browser parser and prints its
// normalised projection as JSON. It contains no parsing logic of its own.
// Usage: node --experimental-strip-types supplier_csv_frontend_runner.mjs <repo-root> < payload.json
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { join } from "node:path";

const root = process.argv[2];
const { parseSupplierCsvText } = await import(
  pathToFileURL(join(root, "frontend", "src", "lib", "supplierCsvParser.ts")).href
);
const { cases, rejectsRow, rejectsFile } = JSON.parse(readFileSync(0, "utf8"));

const token = (value) => {
  if (value === null || value === undefined) return null;
  if (Number.isNaN(value)) return "nan";
  if (value === Infinity) return "inf";
  if (value === -Infinity) return "-inf";
  return value;
};

const out = {};
for (const { id, csv } of cases) {
  const result = parseSupplierCsvText(csv, `${id}.csv`);
  const rows = result.rows
    .filter((row) => row.candidateId !== null && !row.validationIssues.some((issue) => rejectsRow.includes(issue)))
    .map((row) => ({
      candidate_id: row.candidateId,
      unit_cost: token(row.unitCost),
      shipping_cost: token(row.shippingCost),
      landed_cost: token(row.estimatedLandedCost),
      moq: row.moq,
      preview: { valid: row.isValid, issues: [...row.validationIssues] },
    }))
    .sort((a, b) => (a.candidate_id < b.candidate_id ? -1 : a.candidate_id > b.candidate_id ? 1 : 0));
  const fileRejected = result.fileLevelIssues.some((issue) => rejectsFile.includes(issue));
  out[id] = { file_rejected: fileRejected, evidence_mode: result.evidenceMode, rows: fileRejected ? [] : rows };
}
process.stdout.write(JSON.stringify(out));
