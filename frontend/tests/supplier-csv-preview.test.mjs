import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import {
  parseSupplierCsvText,
  parseNumericCost,
  formatCostDisplay,
  parseRawCsvLines,
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

test("supplier CSV parser bounds large files to MAX_PREVIEW_ROWS with preview_rows_truncated warning", () => {
  const lines = ["candidate_id,supplier_title,unit_cost,shipping_cost"];
  for (let i = 1; i <= 1010; i++) {
    lines.push(`item-${i},Product ${i},5.00,1.00`);
  }
  const result = parseSupplierCsvText(lines.join("\n"));
  assert.equal(result.totalRows, 1000);
  assert.ok(result.fileLevelIssues.includes("preview_rows_truncated"));
});
