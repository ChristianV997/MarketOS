import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import {
  parseSupplierCsvText,
  parseNumericCost,
  formatCostDisplay,
  parseRawCsvLines,
  MAX_SUPPLIER_CSV_BYTES,
  MAX_SUPPLIER_CSV_ROWS,
  RECOGNIZED_HEADER_ALIASES,
  RECOGNIZED_SUPPLIERS,
} from "../src/lib/supplierCsvParser.ts";

test("supplier CSV parser: valid rows parsed with recognized headers", () => {
  const csv = `candidate_id,supplier_title,supplier,unit_cost,shipping_cost,currency,inventory_quantity,moq,delivery_window
mini-thermal-printer,Mini Thermal Printer,cj,9.25,3.50,USD,300,1,8-15 days
portable-blender,Portable Blender,alibaba,12.00,5.00,USD,90,2,18-28 days`;

  const result = parseSupplierCsvText(csv, "test-catalog.csv");

  assert.equal(result.fileName, "test-catalog.csv");
  assert.equal(result.totalRows, 2);
  assert.equal(result.validRowCount, 2);
  assert.equal(result.invalidRowCount, 0);
  assert.equal(result.evidenceMode, "manual_import");
  assert.equal(result.evidenceLabel, "Manual / Unverified Evidence");
  assert.equal(result.missingCandidateIdColumn, false);
  assert.equal(result.unrecognizedHeaders.length, 0);

  // Check row 1
  const row1 = result.rows[0];
  assert.equal(row1.candidateId, "mini-thermal-printer");
  assert.equal(row1.productName, "Mini Thermal Printer");
  assert.equal(row1.supplier, "cj");
  assert.equal(row1.unitCost, 9.25);
  assert.equal(row1.shippingCost, 3.5);
  assert.equal(row1.estimatedLandedCost, 12.75);
  assert.equal(row1.currency, "USD");
  assert.equal(row1.inventoryQuantity, 300);
  assert.equal(row1.moq, 1);
  assert.equal(row1.deliveryWindow, "8-15 days");
  assert.equal(row1.isValid, true);
  assert.equal(row1.validationIssues.length, 0);

  // Check row 2
  const row2 = result.rows[1];
  assert.equal(row2.candidateId, "portable-blender");
  assert.equal(row2.estimatedLandedCost, 17.0);
  assert.equal(row2.isValid, true);
});

test("supplier CSV parser: preserves missing cost versus explicit zero", () => {
  const csv = `candidate_id,product,unit_cost,shipping_cost
prod-zero,Zero Cost Product,0,0.00
prod-missing-ship,Free Shipping Test,14.50,
prod-missing-unit,Missing Unit Cost,,3.20
prod-both-missing,Both Missing,,
prod-explicit-zero-unit,Explicit Zero Unit,0.0,4.50`;

  const result = parseSupplierCsvText(csv);
  assert.equal(result.totalRows, 5);

  // Row 1: Explicit zeros
  const r1 = result.rows[0];
  assert.equal(r1.unitCost, 0);
  assert.equal(r1.isUnitCostExplicitZero, true);
  assert.equal(r1.isUnitCostMissing, false);
  assert.equal(r1.shippingCost, 0);
  assert.equal(r1.isShippingCostExplicitZero, true);
  assert.equal(r1.isShippingCostMissing, false);
  assert.equal(r1.estimatedLandedCost, 0); // 0 + 0 = 0
  assert.match(r1.unitCostDisplay, /0\.00/);

  // Row 2: Missing shipping cost (must NOT be coerced to 0)
  const r2 = result.rows[1];
  assert.equal(r2.unitCost, 14.5);
  assert.equal(r2.shippingCost, null);
  assert.equal(r2.isShippingCostMissing, true);
  assert.equal(r2.isShippingCostExplicitZero, false);
  assert.equal(r2.shippingCostDisplay, "missing");
  assert.equal(r2.estimatedLandedCost, null, "Landed cost must remain null if shipping is missing");
  assert.ok(r2.validationIssues.includes("missing_shipping_cost"));

  // Row 3: Missing unit cost (must NOT be coerced to 0)
  const r3 = result.rows[2];
  assert.equal(r3.unitCost, null);
  assert.equal(r3.isUnitCostMissing, true);
  assert.equal(r3.isUnitCostExplicitZero, false);
  assert.equal(r3.unitCostDisplay, "missing");
  assert.equal(r3.shippingCost, 3.2);
  assert.equal(r3.estimatedLandedCost, null, "Landed cost must remain null if unit cost is missing");
  assert.ok(r3.validationIssues.includes("missing_unit_cost"));

  // Row 4: Both missing
  const r4 = result.rows[3];
  assert.equal(r4.unitCost, null);
  assert.equal(r4.shippingCost, null);
  assert.equal(r4.estimatedLandedCost, null);
  assert.ok(r4.validationIssues.includes("missing_unit_cost"));
  assert.ok(r4.validationIssues.includes("missing_shipping_cost"));

  // Row 5: Explicit 0.0 unit cost + 4.50 shipping
  const r5 = result.rows[4];
  assert.equal(r5.unitCost, 0);
  assert.equal(r5.isUnitCostExplicitZero, true);
  assert.equal(r5.shippingCost, 4.5);
  assert.equal(r5.estimatedLandedCost, 4.5); // 0 + 4.50 = 4.50
});

test("supplier CSV parser: numeric cost parser helper handles strings, symbols, zeros, and missing", () => {
  // Missing
  assert.deepEqual(parseNumericCost(null), { value: null, isExplicitZero: false, isMissing: true, isInvalid: false, rawText: "" });
  assert.deepEqual(parseNumericCost(""), { value: null, isExplicitZero: false, isMissing: true, isInvalid: false, rawText: "" });
  assert.deepEqual(parseNumericCost("   "), { value: null, isExplicitZero: false, isMissing: true, isInvalid: false, rawText: "   " });

  // Explicit zero
  assert.deepEqual(parseNumericCost("0"), { value: 0, isExplicitZero: true, isMissing: false, isInvalid: false, rawText: "0" });
  assert.deepEqual(parseNumericCost("0.00"), { value: 0, isExplicitZero: true, isMissing: false, isInvalid: false, rawText: "0.00" });
  assert.deepEqual(parseNumericCost("$0.00"), { value: 0, isExplicitZero: true, isMissing: false, isInvalid: false, rawText: "$0.00" });
  assert.deepEqual(parseNumericCost("USD 0"), { value: 0, isExplicitZero: true, isMissing: false, isInvalid: false, rawText: "USD 0" });

  // Normal numbers
  assert.equal(parseNumericCost("12.50").value, 12.5);
  assert.equal(parseNumericCost("$1,200.50").value, 1200.5);
  assert.equal(parseNumericCost("€9.99").value, 9.99);

  // Invalid non-numbers
  assert.equal(parseNumericCost("not-a-number").isInvalid, true);
  assert.equal(parseNumericCost("N/A").isInvalid, true);
});

test("supplier CSV parser: NEVER derives candidate ID from product display name", () => {
  const csv = `product,unit_cost,shipping_cost
Portable Neck Massager,15.00,3.00
Mini Thermal Printer,9.00,2.50`;

  const result = parseSupplierCsvText(csv);

  assert.equal(result.missingCandidateIdColumn, true);
  assert.ok(result.fileLevelIssues.includes("missing_candidate_id_column"));

  // Check that candidate IDs are strictly null and NOT slugified from product name
  for (const row of result.rows) {
    assert.equal(row.candidateId, null, "Candidate ID must never be derived from product title");
    assert.notEqual(row.candidateId, "portable-neck-massager");
    assert.notEqual(row.candidateId, "Portable Neck Massager");
    assert.notEqual(row.candidateId, "mini-thermal-printer");
    assert.ok(row.productName !== null, "Product display name should be preserved for UI display");
    assert.ok(row.validationIssues.includes("missing_candidate_id"));
    assert.equal(row.isValid, false);
  }
});

test("supplier CSV parser: identifies invalid and unrecognized headers", () => {
  const csv = `some_custom_col,product,foo_bar,unit_cost,supplier_rating
custom_val,My Item,test_val,10.00,4.5`;

  const result = parseSupplierCsvText(csv);

  assert.ok(result.unrecognizedHeaders.includes("some_custom_col"));
  assert.ok(result.unrecognizedHeaders.includes("foo_bar"));
  assert.ok(result.recognizedHeaders.includes("supplier_title")); // from "product"
  assert.ok(result.recognizedHeaders.includes("unit_cost"));
  assert.ok(result.recognizedHeaders.includes("supplier_rating"));
  assert.equal(result.missingCandidateIdColumn, true);
});

test("supplier CSV parser: flags row-level validation issues (malformed costs, duplicates, unknown suppliers, column mismatch)", () => {
  const csv = `candidate_id,product,supplier,unit_cost,shipping_cost
dup-id,Item One,cj,10.00,2.00
dup-id,Item Duplicate,cj,12.00,2.00
bad-cost,Item Three,unknown_supplier,not-a-cost,bad-ship
short-row,Short Item,alibaba
ok-row,Item Five,spocket,8.00,1.50`;

  const result = parseSupplierCsvText(csv);

  assert.equal(result.totalRows, 5);
  assert.equal(result.validRowCount, 2); // dup-id first occurrence and ok-row
  assert.equal(result.invalidRowCount, 3);

  // Duplicate candidate ID
  const r2 = result.rows[1];
  assert.ok(r2.validationIssues.includes("duplicate_candidate_id"));

  // Malformed costs and unknown supplier
  const r3 = result.rows[2];
  assert.ok(r3.validationIssues.includes("malformed_unit_cost"));
  assert.ok(r3.validationIssues.includes("malformed_shipping_cost"));
  assert.ok(r3.validationIssues.includes("unsupported_supplier"));

  // Short row (column count mismatch)
  const r4 = result.rows[3];
  assert.ok(r4.validationIssues.includes("malformed_column_count"));
  assert.ok(r4.validationIssues.includes("missing_unit_cost"));
  assert.ok(r4.validationIssues.includes("missing_shipping_cost"));

  // Valid row
  const r5 = result.rows[4];
  assert.equal(r5.isValid, true);
  assert.equal(r5.supplier, "spocket");
});

test("supplier CSV parser: handles RFC 4180 quotes, commas in fields, and escaped quotes", () => {
  const csv = `candidate_id,supplier_title,unit_cost,shipping_cost
"item,comma","Product with ""escaped"" quotes, and comma",10.50,2.50
"simple-id","Normal Product",15.00,3.00`;

  const result = parseSupplierCsvText(csv);

  assert.equal(result.totalRows, 2);
  const r1 = result.rows[0];
  assert.equal(r1.candidateId, "item,comma");
  assert.equal(r1.productName, 'Product with "escaped" quotes, and comma');
  assert.equal(r1.unitCost, 10.5);
  assert.equal(r1.shippingCost, 2.5);
  assert.equal(r1.estimatedLandedCost, 13.0);
  assert.equal(r1.isValid, true);
});

test("supplier CSV parser: handles empty and whitespace-only files", () => {
  const resultEmpty = parseSupplierCsvText("");
  assert.equal(resultEmpty.totalRows, 0);
  assert.equal(resultEmpty.validRowCount, 0);
  assert.ok(resultEmpty.fileLevelIssues.includes("empty_csv_file"));

  const resultWhitespace = parseSupplierCsvText("   \n\n  \r\n");
  assert.equal(resultWhitespace.totalRows, 0);
  assert.ok(resultWhitespace.fileLevelIssues.includes("empty_csv_file"));
});

test("react component contract: exports, accessibility attributes, and unverified evidence banner", async () => {
  const componentSrc = await readFile(
    new URL("../src/components/SupplierCsvPreview.tsx", import.meta.url),
    "utf8",
  );

  // Must export SupplierCsvPreview component
  assert.match(componentSrc, /export function SupplierCsvPreview/);

  // Must include prominent Manual / Unverified Evidence label
  assert.match(componentSrc, /Manual \/ Unverified Evidence/);
  assert.match(componentSrc, /evidence_mode=manual_import/);

  // Accessibility contracts
  assert.match(componentSrc, /role="status"/);
  assert.match(componentSrc, /aria-live="polite"/);
  assert.match(componentSrc, /aria-label="Supplier Catalog CSV Preview"/);
  assert.match(componentSrc, /<table/);
  assert.match(componentSrc, /<thead/);
  assert.match(componentSrc, /<th scope="col"/);
  assert.match(componentSrc, /<tbody/);
  assert.match(componentSrc, /tabIndex=\{isSelectable \? 0 : undefined\}/, "Selectable rows must have tabIndex=0 for keyboard accessibility");
  assert.match(componentSrc, /role=\{isSelectable \? "button" : undefined\}/, "Selectable rows must declare role='button'");
  assert.match(componentSrc, /aria-selected=\{isSelected\}/, "Rows must declare aria-selected");
  assert.match(componentSrc, /onKeyDown/, "Selectable rows must support onKeyDown for Enter/Space selection");
  assert.match(componentSrc, /empty-csv-notice/, "Component must display empty notice when CSV contains 0 rows");

  // Local-only / no transmission guarantee
  assert.match(componentSrc, /Local browser preview only/);
  assert.doesNotMatch(componentSrc, /fetch\(/, "Must not perform fetch/network calls");
  assert.doesNotMatch(componentSrc, /axios/, "Must not use axios");
  assert.doesNotMatch(componentSrc, /XMLHttpRequest/, "Must not use XMLHttpRequest");
  assert.doesNotMatch(componentSrc, /WebSocket/, "Must not use WebSocket");

  // Explicit bounds and error alert contracts
  assert.match(componentSrc, /MAX_SUPPLIER_CSV_BYTES/, "Component must reference MAX_SUPPLIER_CSV_BYTES");
  assert.match(componentSrc, /file-size-exceeded-alert/, "Component must render file-size-exceeded-alert");
  assert.match(componentSrc, /malformed-encoding-alert/, "Component must render malformed-encoding-alert");
  assert.match(componentSrc, /preview-rows-truncated-notice/, "Component must render preview-rows-truncated-notice");
});

test("formatCostDisplay does not leak sensitive strings or raw text when cost is invalid", () => {
  const secretString = "sk_live_very_secret_api_key_123456789";
  const parsed = parseNumericCost(secretString);
  assert.equal(parsed.isInvalid, true);

  const display = formatCostDisplay(parsed, "USD");
  assert.equal(display, "invalid cost");
  assert.doesNotMatch(display, /sk_live/);
  assert.doesNotMatch(display, /secret/);
});

test("parseNumericCost disallows negative costs", () => {
  const negativeCost = parseNumericCost("-15.00");
  assert.equal(negativeCost.isInvalid, true);
  assert.equal(negativeCost.value, null);
  assert.equal(negativeCost.isMissing, false);

  const negativeZero = parseNumericCost("-0.00");
  assert.equal(negativeZero.value, 0);
  assert.equal(negativeZero.isExplicitZero, true);
});

test("supplier CSV parser flags sensitive cell contents and script injection without leaking values", () => {
  const csvWithSecret = `candidate_id,supplier_title,unit_cost,shipping_cost
cand-sec,Product with Secret,sk-live-mock-api-key-test,2.00`;
  const resultSecret = parseSupplierCsvText(csvWithSecret);
  assert.equal(resultSecret.totalRows, 1);
  const row = resultSecret.rows[0];
  assert.equal(row.isValid, false);
  assert.ok(row.validationIssues.includes("sensitive_or_malformed_cell_content"));
  assert.ok(row.validationIssues.includes("malformed_unit_cost"));
  assert.equal(row.unitCostDisplay, "invalid cost");

  const csvWithScript = `candidate_id,supplier_title,unit_cost,shipping_cost
cand-xss,<script>alert('xss')</script>,5.00,2.00`;
  const resultScript = parseSupplierCsvText(csvWithScript);
  assert.equal(resultScript.totalRows, 1);
  assert.equal(resultScript.rows[0].isValid, false);
  assert.ok(resultScript.rows[0].validationIssues.includes("sensitive_or_malformed_cell_content"));
});

test("supplier CSV parser recognizes 'id' as candidate_id alias", () => {
  const csv = `id,supplier_title,unit_cost,shipping_cost
cand-id-col,Widget From ID,10.00,2.00`;
  const result = parseSupplierCsvText(csv);
  assert.equal(result.totalRows, 1);
  assert.equal(result.missingCandidateIdColumn, false);
  assert.equal(result.rows[0].candidateId, "cand-id-col");
});

test("supplier CSV parser: byte size boundary tests (just-under, at limit, and over limit)", () => {
  // Helper to construct exact byte length CSV
  function makeByteCsv(targetBytes) {
    const base = "candidate_id,supplier_title,supplier,unit_cost,shipping_cost,currency\n" +
      "item-1,Item One,manual,10.00,2.00,USD\n";
    const baseBytes = new TextEncoder().encode(base).length;
    assert.ok(targetBytes >= baseBytes, "Target bytes must be at least base size");
    const pad = " ".repeat(targetBytes - baseBytes);
    const full = base + pad;
    assert.equal(new TextEncoder().encode(full).length, targetBytes);
    return full;
  }

  // 1. Just-under byte limit (256 KB - 100 bytes = 262,044 bytes)
  const justUnderBytes = MAX_SUPPLIER_CSV_BYTES - 100;
  const justUnderCsv = makeByteCsv(justUnderBytes);
  const justUnderRes = parseSupplierCsvText(justUnderCsv, "just-under.csv");
  assert.equal(justUnderRes.fileLevelIssues.includes("file_size_exceeds_limit"), false, "Just-under byte limit must not trigger file_size_exceeds_limit");
  assert.equal(justUnderRes.totalRows, 1);
  assert.equal(justUnderRes.validRowCount, 1);

  // 2. Exactly at byte limit (256 KB = 262,144 bytes)
  const atLimitCsv = makeByteCsv(MAX_SUPPLIER_CSV_BYTES);
  const atLimitRes = parseSupplierCsvText(atLimitCsv, "at-limit.csv");
  assert.equal(atLimitRes.fileLevelIssues.includes("file_size_exceeds_limit"), false, "At byte limit must not trigger file_size_exceeds_limit");
  assert.equal(atLimitRes.totalRows, 1);
  assert.equal(atLimitRes.validRowCount, 1);

  // 3. Over byte limit by 1 byte (256 KB + 1 byte = 262,145 bytes)
  const overLimitCsv = makeByteCsv(MAX_SUPPLIER_CSV_BYTES + 1);
  const overLimitRes = parseSupplierCsvText(overLimitCsv, "over-limit.csv");
  assert.equal(overLimitRes.fileLevelIssues.includes("file_size_exceeds_limit"), true, "Over byte limit must trigger file_size_exceeds_limit");
  assert.equal(overLimitRes.totalRows, 0, "Oversized CSV must fail-closed with 0 parsed rows");
  assert.equal(overLimitRes.validRowCount, 0);
  assert.equal(overLimitRes.invalidRowCount, 0);
  assert.equal(overLimitRes.rows.length, 0);
});

test("supplier CSV parser: row count boundary tests (just-under 99 rows, at limit 100 rows, and over limit 101 rows)", () => {
  function makeRowCsv(count) {
    const lines = ["candidate_id,supplier_title,supplier,unit_cost,shipping_cost,currency"];
    for (let i = 1; i <= count; i++) {
      lines.push(`item-${i},Product ${i},manual,10.00,2.00,USD`);
    }
    return lines.join("\n");
  }

  // 1. Just-under row limit (99 data rows)
  const underCsv = makeRowCsv(MAX_SUPPLIER_CSV_ROWS - 1);
  const underRes = parseSupplierCsvText(underCsv);
  assert.equal(underRes.totalRows, 99);
  assert.equal(underRes.validRowCount, 99);
  assert.equal(underRes.fileLevelIssues.includes("row_count_exceeds_limit"), false);
  assert.equal(underRes.fileLevelIssues.includes("preview_rows_truncated"), false);

  // 2. Exactly at row limit (100 data rows)
  const atLimitCsv = makeRowCsv(MAX_SUPPLIER_CSV_ROWS);
  const atLimitRes = parseSupplierCsvText(atLimitCsv);
  assert.equal(atLimitRes.totalRows, 100);
  assert.equal(atLimitRes.validRowCount, 100);
  assert.equal(atLimitRes.fileLevelIssues.includes("row_count_exceeds_limit"), false);
  assert.equal(atLimitRes.fileLevelIssues.includes("preview_rows_truncated"), false);

  // 3. Over row limit (101 data rows)
  const overLimitCsv = makeRowCsv(MAX_SUPPLIER_CSV_ROWS + 1);
  const overLimitRes = parseSupplierCsvText(overLimitCsv);
  assert.equal(overLimitRes.totalRows, 100, "Must bound parsed preview rows to MAX_SUPPLIER_CSV_ROWS (100)");
  assert.equal(overLimitRes.validRowCount, 100);
  assert.equal(overLimitRes.fileLevelIssues.includes("row_count_exceeds_limit"), true, "Must flag row_count_exceeds_limit when rows > 100");
  assert.equal(overLimitRes.fileLevelIssues.includes("preview_rows_truncated"), true, "Must flag preview_rows_truncated when rows > 100");

  // 4. Far over row limit (150 data rows)
  const farOverCsv = makeRowCsv(150);
  const farOverRes = parseSupplierCsvText(farOverCsv);
  assert.equal(farOverRes.totalRows, 100);
  assert.equal(farOverRes.fileLevelIssues.includes("row_count_exceeds_limit"), true);
  assert.equal(farOverRes.fileLevelIssues.includes("preview_rows_truncated"), true);
});

test("supplier CSV parser: detects malformed encoding (null bytes and replacement characters)", () => {
  // 1. Null byte \0 in CSV content
  const nullByteCsv = "candidate_id,supplier_title,unit_cost,shipping_cost\n" +
    "item-null,Product\0Corrupt,10.00,2.00";
  const nullRes = parseSupplierCsvText(nullByteCsv);
  assert.equal(nullRes.totalRows, 1);
  assert.ok(nullRes.fileLevelIssues.includes("malformed_encoding"), "Must flag malformed_encoding on null byte");
  assert.ok(nullRes.rows[0].validationIssues.includes("sensitive_or_malformed_cell_content"));
  assert.equal(nullRes.rows[0].isValid, false);

  // 2. Unicode replacement character \uFFFD in CSV content
  const replacementCharCsv = "candidate_id,supplier_title,unit_cost,shipping_cost\n" +
    "item-replace,Product\uFFFDGarbled,15.00,3.00";
  const repRes = parseSupplierCsvText(replacementCharCsv);
  assert.equal(repRes.totalRows, 1);
  assert.ok(repRes.fileLevelIssues.includes("malformed_encoding"), "Must flag malformed_encoding on replacement character");
  assert.ok(repRes.rows[0].validationIssues.includes("sensitive_or_malformed_cell_content"));
  assert.equal(repRes.rows[0].isValid, false);

  // 3. Empty CSV with null byte still reports both empty and malformed encoding
  const emptyNullCsv = "\0";
  const emptyNullRes = parseSupplierCsvText(emptyNullCsv);
  assert.ok(emptyNullRes.fileLevelIssues.includes("malformed_encoding"));
  assert.ok(emptyNullRes.fileLevelIssues.includes("empty_csv_file"));
});

test("supplier CSV parser: missing versus explicit zero cost combinations and derivation boundaries", () => {
  const csv = `candidate_id,supplier_title,unit_cost,shipping_cost
both-zero,Both Explicit Zero,0,0
both-zero-formatted,Both Formatted Zero,0.00,$0.00
unit-zero-ship-missing,Unit Zero Ship Missing,0.00,
unit-missing-ship-zero,Unit Missing Ship Zero,,0.00
unit-zero-ship-val,Unit Zero Ship Val,0,4.50
unit-val-ship-zero,Unit Val Ship Zero,12.00,0
unit-missing-ship-val,Unit Missing Ship Val,,4.50
unit-val-ship-missing,Unit Val Ship Missing,12.00,
neg-unit,Negative Unit Cost,-5.00,2.00
neg-ship,Negative Shipping Cost,10.00,-2.00`;

  const result = parseSupplierCsvText(csv);
  assert.equal(result.totalRows, 10);

  // Row 0: Both explicit 0
  const r0 = result.rows[0];
  assert.equal(r0.unitCost, 0);
  assert.equal(r0.isUnitCostExplicitZero, true);
  assert.equal(r0.shippingCost, 0);
  assert.equal(r0.isShippingCostExplicitZero, true);
  assert.equal(r0.estimatedLandedCost, 0);

  // Row 1: Both formatted 0 ($0.00, 0.00)
  const r1 = result.rows[1];
  assert.equal(r1.unitCost, 0);
  assert.equal(r1.isUnitCostExplicitZero, true);
  assert.equal(r1.shippingCost, 0);
  assert.equal(r1.isShippingCostExplicitZero, true);
  assert.equal(r1.estimatedLandedCost, 0);

  // Row 2: Unit zero, shipping missing -> landed cost must be null
  const r2 = result.rows[2];
  assert.equal(r2.unitCost, 0);
  assert.equal(r2.isUnitCostExplicitZero, true);
  assert.equal(r2.shippingCost, null);
  assert.equal(r2.isShippingCostMissing, true);
  assert.equal(r2.estimatedLandedCost, null, "Landed cost must remain null if shipping is missing");

  // Row 3: Unit missing, shipping zero -> landed cost must be null
  const r3 = result.rows[3];
  assert.equal(r3.unitCost, null);
  assert.equal(r3.isUnitCostMissing, true);
  assert.equal(r3.shippingCost, 0);
  assert.equal(r3.isShippingCostExplicitZero, true);
  assert.equal(r3.estimatedLandedCost, null, "Landed cost must remain null if unit cost is missing");

  // Row 4: Unit zero, shipping 4.50 -> landed cost 4.50
  const r4 = result.rows[4];
  assert.equal(r4.unitCost, 0);
  assert.equal(r4.isUnitCostExplicitZero, true);
  assert.equal(r4.shippingCost, 4.5);
  assert.equal(r4.estimatedLandedCost, 4.5);

  // Row 5: Unit 12.00, shipping zero -> landed cost 12.00
  const r5 = result.rows[5];
  assert.equal(r5.unitCost, 12);
  assert.equal(r5.shippingCost, 0);
  assert.equal(r5.isShippingCostExplicitZero, true);
  assert.equal(r5.estimatedLandedCost, 12);

  // Row 6: Unit missing, shipping 4.50 -> landed cost null
  const r6 = result.rows[6];
  assert.equal(r6.unitCost, null);
  assert.equal(r6.estimatedLandedCost, null);

  // Row 7: Unit 12.00, shipping missing -> landed cost null
  const r7 = result.rows[7];
  assert.equal(r7.shippingCost, null);
  assert.equal(r7.estimatedLandedCost, null);

  // Row 8: Negative unit cost -> invalid
  const r8 = result.rows[8];
  assert.equal(r8.unitCost, null);
  assert.ok(r8.validationIssues.includes("malformed_unit_cost"));
  assert.equal(r8.estimatedLandedCost, null);

  // Row 9: Negative shipping cost -> invalid
  const r9 = result.rows[9];
  assert.equal(r9.shippingCost, null);
  assert.ok(r9.validationIssues.includes("malformed_shipping_cost"));
  assert.equal(r9.estimatedLandedCost, null);
});

test("supplier CSV parser: sanitizes errors and never echoes raw cell content in issues or formatted displays", () => {
  const sensitiveToken = "sk-live-supersecretapikey-1234567890";
  const scriptInjection = "<script>window.location='https://attacker.com'</script>";
  const bearerToken = "bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.xyz";

  const csv = `candidate_id,supplier_title,unit_cost,shipping_cost
cand-1,Normal Item,${sensitiveToken},2.00
cand-2,${scriptInjection},10.00,2.00
cand-3,Normal Item,10.00,${bearerToken}`;

  const result = parseSupplierCsvText(csv);
  assert.equal(result.totalRows, 3);

  for (const row of result.rows) {
    // 1. unitCostDisplay and shippingCostDisplay must never contain raw tokens
    assert.doesNotMatch(row.unitCostDisplay, /supersecret/);
    assert.doesNotMatch(row.unitCostDisplay, /<script/);
    assert.doesNotMatch(row.unitCostDisplay, /bearer/);
    assert.doesNotMatch(row.shippingCostDisplay, /supersecret/);
    assert.doesNotMatch(row.shippingCostDisplay, /<script/);
    assert.doesNotMatch(row.shippingCostDisplay, /bearer/);

    // 2. validationIssues must only contain sanitized issue codes
    for (const issue of row.validationIssues) {
      assert.doesNotMatch(issue, /supersecret/);
      assert.doesNotMatch(issue, /<script/);
      assert.doesNotMatch(issue, /bearer/);
      assert.match(issue, /^[a-z0-9_]+$/, `Issue code "${issue}" must be a sanitized alphanumeric identifier`);
    }
  }

  // 3. fileLevelIssues must only contain sanitized issue codes
  for (const fileIssue of result.fileLevelIssues) {
    assert.doesNotMatch(fileIssue, /supersecret/);
    assert.match(fileIssue, /^[a-z0-9_]+$/, `File issue "${fileIssue}" must be a sanitized identifier`);
  }
});
