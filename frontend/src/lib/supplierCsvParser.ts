/**
 * Local-only, zero-dependency RFC 4180 CSV parser and validation engine for supplier CSV previews.
 *
 * Invariants:
 * - Local-only: does not upload, persist, or transmit file contents.
 * - Missing vs Explicit Zero: preserves missing costs as null while preserving 0 / 0.0 as explicit zero.
 * - Identity integrity: NEVER derives a candidate ID from a product display name.
 * - Evidence truthfulness: marks all imported rows as manual/unverified evidence.
 */

export const MAX_SUPPLIER_CSV_BYTES = 256 * 1024; // 262,144 bytes (256 KB)
export const MAX_SUPPLIER_CSV_ROWS = 100; // 100 records (canonical backend supplier-import bound)

export const RECOGNIZED_SUPPLIERS = Object.freeze([
  "cj",
  "alibaba",
  "aliexpress",
  "zendrop",
  "autods",
  "dsers",
  "spocket",
  "manual",
] as const);

export type RecognizedSupplier = (typeof RECOGNIZED_SUPPLIERS)[number];

export const RECOGNIZED_HEADER_ALIASES: Readonly<Record<string, string>> = Object.freeze({
  // Candidate ID aliases - NEVER map "product", "title", "name", etc. to candidate_id!
  candidate_id: "candidate_id",
  supplier_product_id: "candidate_id",
  product_id: "candidate_id",
  item_id: "candidate_id",
  id: "candidate_id",
  pid: "candidate_id",
  productid: "candidate_id",

  // Product title / display name aliases (strictly separate from candidate_id)
  supplier_title: "supplier_title",
  title: "supplier_title",
  product_title: "supplier_title",
  product: "supplier_title",
  name: "supplier_title",
  nameen: "supplier_title",
  productnameen: "supplier_title",

  // Supplier
  supplier: "supplier",
  vendor: "supplier",

  // SKU
  supplier_sku: "supplier_sku",
  sku: "supplier_sku",
  variantsku: "supplier_sku",
  variant_sku: "supplier_sku",

  // Unit cost
  unit_cost: "unit_cost",
  sellprice: "unit_cost",
  regular_price: "unit_cost",
  unitcost: "unit_cost",
  supplier_cost: "unit_cost",
  cost: "unit_cost",
  price: "unit_cost",

  // Shipping cost
  shipping_cost: "shipping_cost",
  shipping: "shipping_cost",

  // Currency
  currency: "currency",
  price_currency: "currency",

  // Delivery / logistics
  delivery_window: "delivery_window",
  deliverycycle: "delivery_window",
  deliverytime: "delivery_window",
  lead_time_days: "delivery_window",
  delivery_days: "delivery_window",
  delivery_min_days: "delivery_min_days",
  delivery_max_days: "delivery_max_days",

  // Inventory
  inventory_quantity: "inventory_quantity",
  stock: "inventory_quantity",
  inventory: "inventory_quantity",
  inventoryquantity: "inventory_quantity",
  stock_quantity: "inventory_quantity",
  cjinventory: "inventory_quantity",
  totalinventory: "inventory_quantity",

  inventory_status: "inventory_status",
  stock_status: "inventory_status",
  availability: "inventory_status",

  // MOQ
  moq: "moq",
  minimum_order_quantity: "moq",
  minimum_quantity: "moq",
  directminordernum: "moq",
  min_order_quantity: "moq",

  // Regions
  warehouse_region: "warehouse_region",
  warehouse: "warehouse_region",
  origin: "warehouse_region",
  areaen: "warehouse_region",
  store_code: "warehouse_region",
  origin_country: "warehouse_region",
  countrycodeoforigin: "warehouse_region",

  destination_region: "destination_region",
  destination: "destination_region",
  ship_to_country: "destination_region",

  // Fulfillment
  fulfillment_method: "fulfillment_method",
  fulfillment: "fulfillment_method",

  // Rating & Reviews
  supplier_rating: "supplier_rating",
  rating: "supplier_rating",
  supplier_review_count: "supplier_review_count",
  review_count: "supplier_review_count",
  reviews: "supplier_review_count",

  // Metadata
  source_url: "source_url",
  url: "source_url",
  query: "query",
  category: "category",
  source_type: "source_type",
  source_confidence: "source_confidence",
  confidence: "source_confidence",
});

export interface ParsedCost {
  readonly value: number | null;
  readonly isExplicitZero: boolean;
  readonly isMissing: boolean;
  readonly isInvalid: boolean;
  readonly rawText: string;
}

export interface SupplierCsvRowPreview {
  readonly rowIndex: number;
  readonly candidateId: string | null;
  readonly productName: string | null;
  readonly supplier: string;
  readonly unitCost: number | null;
  readonly isUnitCostExplicitZero: boolean;
  readonly isUnitCostMissing: boolean;
  readonly unitCostDisplay: string;
  readonly shippingCost: number | null;
  readonly isShippingCostExplicitZero: boolean;
  readonly isShippingCostMissing: boolean;
  readonly shippingCostDisplay: string;
  readonly estimatedLandedCost: number | null;
  readonly currency: string;
  readonly inventoryQuantity: number | null;
  readonly inventoryStatus: string | null;
  readonly moq: number | null;
  readonly deliveryWindow: string | null;
  readonly isValid: boolean;
  readonly validationIssues: readonly string[];
  readonly rawFields: Readonly<Record<string, string>>;
}

export interface SupplierCsvPreviewResult {
  readonly fileName?: string;
  readonly totalRows: number;
  readonly validRowCount: number;
  readonly invalidRowCount: number;
  readonly rawHeaders: readonly string[];
  readonly recognizedHeaders: readonly string[];
  readonly unrecognizedHeaders: readonly string[];
  readonly missingCandidateIdColumn: boolean;
  readonly evidenceMode: "manual_import";
  readonly evidenceLabel: "Manual / Unverified Evidence";
  readonly rows: readonly SupplierCsvRowPreview[];
  readonly fileLevelIssues: readonly string[];
}

/**
 * Parses numeric cost distinguishing explicit zero (0, "0.00") from missing (null, empty).
 */
export function parseNumericCost(rawValue: string | null | undefined): ParsedCost {
  if (rawValue === null || rawValue === undefined) {
    return { value: null, isExplicitZero: false, isMissing: true, isInvalid: false, rawText: "" };
  }
  const rawText = String(rawValue);
  const text = rawText.trim();
  if (text === "") {
    return { value: null, isExplicitZero: false, isMissing: true, isInvalid: false, rawText };
  }

  // Strip currency prefixes and commas
  const cleaned = text
    .replace(/^[$\u20ac\u00a3\u00a5]/, "")
    .replace(/^(usd|mxn|eur|gbp)\s*/i, "")
    .replace(/,/g, "")
    .trim();

  if (cleaned === "") {
    return { value: null, isExplicitZero: false, isMissing: true, isInvalid: false, rawText };
  }

  const num = Number(cleaned);
  if (!Number.isFinite(num) || num < 0) {
    return { value: null, isExplicitZero: false, isMissing: false, isInvalid: true, rawText };
  }

  if (num === 0) {
    return { value: 0, isExplicitZero: true, isMissing: false, isInvalid: false, rawText };
  }

  return { value: num, isExplicitZero: false, isMissing: false, isInvalid: false, rawText };
}

/**
 * Formats a parsed cost for tabular display.
 * Does not expose raw cell text to prevent leaking sensitive values in error displays.
 */
export function formatCostDisplay(cost: ParsedCost, currency = "USD"): string {
  if (cost.isMissing) return "missing";
  if (cost.isInvalid) return "invalid cost";
  if (cost.value !== null) {
    return `${cost.value.toFixed(2)} ${currency}`;
  }
  return "missing";
}

/**
 * Returns true when a quote appears outside a quoted field, after a closing
 * quote before a delimiter, or when a quoted field is left unterminated.
 */
function hasMalformedCsvQuoting(csvText: string): boolean {
  const clean = csvText.replace(/^\uFEFF/, "");
  let inQuotes = false;
  let afterQuote = false;
  let atFieldStart = true;

  for (let i = 0; i < clean.length; i++) {
    const char = clean[i];
    const nextChar = clean[i + 1];
    const isRecordDelimiter = char.charCodeAt(0) === 10 || char.charCodeAt(0) === 13;

    if (inQuotes) {
      if (char === '"') {
        if (nextChar === '"') {
          i++;
        } else {
          inQuotes = false;
          afterQuote = true;
        }
      }
      continue;
    }

    if (afterQuote) {
      if (char === "," || isRecordDelimiter) {
        afterQuote = false;
        atFieldStart = true;
      } else {
        return true;
      }
      continue;
    }

    if (char === '"') {
      if (!atFieldStart) return true;
      inQuotes = true;
      atFieldStart = false;
    } else if (char === "," || isRecordDelimiter) {
      atFieldStart = true;
    } else {
      atFieldStart = false;
    }
  }

  return inQuotes;
}

/**
 * Pure RFC 4180 CSV tokenizer and row splitter.
 */
export function parseRawCsvLines(csvText: string): string[][] {
  const clean = csvText.replace(/^\uFEFF/, "");
  if (!clean.replace(/[\0\s]/g, "")) return [];

  const rows: string[][] = [];
  let currentRow: string[] = [];
  let currentField = "";
  let insideQuotes = false;

  for (let i = 0; i < clean.length; i++) {
    const char = clean[i];
    const nextChar = clean[i + 1];

    if (insideQuotes) {
      if (char === '"') {
        if (nextChar === '"') {
          // Escaped double quote
          currentField += '"';
          i++;
        } else {
          // Closing quote
          insideQuotes = false;
        }
      } else {
        currentField += char;
      }
    } else {
      if (char === '"') {
        insideQuotes = true;
      } else if (char === ",") {
        currentRow.push(currentField.trim());
        currentField = "";
      } else if (char === "\r") {
        if (nextChar === "\n") {
          i++;
        }
        currentRow.push(currentField.trim());
        rows.push(currentRow);
        currentRow = [];
        currentField = "";
      } else if (char === "\n") {
        currentRow.push(currentField.trim());
        rows.push(currentRow);
        currentRow = [];
        currentField = "";
      } else {
        currentField += char;
      }
    }
  }

  if (currentField.length > 0 || currentRow.length > 0) {
    currentRow.push(currentField.trim());
    rows.push(currentRow);
  }

  // Filter out trailing empty rows
  return rows.filter((r) => r.length > 1 || (r.length === 1 && r[0] !== ""));
}

/**
 * Parses and validates supplier catalog CSV text into a structured preview result.
 *
 * Enforces:
 * - Recognized headers mapping.
 * - Missing cost vs explicit zero preservation.
 * - Rejection of display name as candidate ID.
 * - Row validation issues.
 * - Fail-closed manual/unverified evidence labeling.
 */
export function parseSupplierCsvText(csvText: string, fileName?: string): SupplierCsvPreviewResult {
  // Early byte bound check before expensive full parsing
  const byteLength = new TextEncoder().encode(csvText).length;
  if (byteLength > MAX_SUPPLIER_CSV_BYTES) {
    return {
      fileName,
      totalRows: 0,
      validRowCount: 0,
      invalidRowCount: 0,
      rawHeaders: [],
      recognizedHeaders: [],
      unrecognizedHeaders: [],
      missingCandidateIdColumn: true,
      evidenceMode: "manual_import",
      evidenceLabel: "Manual / Unverified Evidence",
      rows: [],
      fileLevelIssues: ["file_size_exceeds_limit"],
    };
  }

  const hasMalformedEncoding = csvText.includes("\0") || csvText.includes("\uFFFD");
  if (hasMalformedCsvQuoting(csvText)) {
    return {
      fileName,
      totalRows: 0,
      validRowCount: 0,
      invalidRowCount: 0,
      rawHeaders: [],
      recognizedHeaders: [],
      unrecognizedHeaders: [],
      missingCandidateIdColumn: true,
      evidenceMode: "manual_import",
      evidenceLabel: "Manual / Unverified Evidence",
      rows: [],
      fileLevelIssues: ["malformed_csv_quoting"],
    };
  }

  const rawRows = parseRawCsvLines(csvText);

  if (rawRows.length === 0) {
    return {
      fileName,
      totalRows: 0,
      validRowCount: 0,
      invalidRowCount: 0,
      rawHeaders: [],
      recognizedHeaders: [],
      unrecognizedHeaders: [],
      missingCandidateIdColumn: true,
      evidenceMode: "manual_import",
      evidenceLabel: "Manual / Unverified Evidence",
      rows: [],
      fileLevelIssues: hasMalformedEncoding
        ? ["empty_csv_file", "malformed_encoding"]
        : ["empty_csv_file"],
    };
  }

  const rawHeaders = rawRows[0];
  const headerKeyMap: Array<{ raw: string; canonical: string | null }> = [];
  const recognizedHeadersSet = new Set<string>();
  const unrecognizedHeadersSet = new Set<string>();
  let hasCandidateIdHeader = false;

  for (const rawHeader of rawHeaders) {
    const normalizedKey = rawHeader.toLowerCase().replace(/[\s_-]+/g, "_");
    const canonical = RECOGNIZED_HEADER_ALIASES[normalizedKey] || null;
    headerKeyMap.push({ raw: rawHeader, canonical });

    if (canonical) {
      recognizedHeadersSet.add(canonical);
      if (canonical === "candidate_id") {
        hasCandidateIdHeader = true;
      }
    } else if (rawHeader.trim() !== "") {
      unrecognizedHeadersSet.add(rawHeader);
    }
  }

  const isOverRowCount = rawRows.length > MAX_SUPPLIER_CSV_ROWS + 1;
  const rowsToProcess = isOverRowCount ? rawRows.slice(0, MAX_SUPPLIER_CSV_ROWS + 1) : rawRows;

  const fileLevelIssues: string[] = [];
  if (hasMalformedEncoding) {
    fileLevelIssues.push("malformed_encoding");
  }
  if (!hasCandidateIdHeader) {
    fileLevelIssues.push("missing_candidate_id_column");
  }
  if (isOverRowCount) {
    fileLevelIssues.push("row_count_exceeds_limit");
    fileLevelIssues.push("preview_rows_truncated");
  }

  const seenCandidateIds = new Set<string>();
  const previewRows: SupplierCsvRowPreview[] = [];
  let validRowCount = 0;
  let invalidRowCount = 0;

  for (let rowIndex = 1; rowIndex < rowsToProcess.length; rowIndex++) {
    const rawCols = rowsToProcess[rowIndex];
    const issues: string[] = [];
    const record: Record<string, string> = Object.create(null);

    if (rawCols.length !== rawHeaders.length) {
      issues.push("malformed_column_count");
    }

    for (let c = 0; c < rawHeaders.length; c++) {
      const colVal = c < rawCols.length ? rawCols[c] : "";
      const rawHeaderName = rawHeaders[c];
      record[rawHeaderName] = colVal;

      const mapping = headerKeyMap[c];
      if (mapping && mapping.canonical) {
        // If multiple columns map to same canonical, preserve first non-empty
        if (!record[mapping.canonical] || record[mapping.canonical] === "") {
          record[mapping.canonical] = colVal;
        }
      }
    }

    // Sensitive pattern or script injection detection across all columns (fail-closed, no leak)
    for (const val of Object.values(record)) {
      if (!val) continue;
      if (
        /[\0\uFFFD]/.test(val) ||
        /^(?:sk[-_]|ghp_|gho_|xox[baprs]-|AKIA[0-9A-Z]{16})/i.test(val) ||
        /^bearer\s+[a-z0-9._~+/-]+=*/i.test(val) ||
        /<script\b/i.test(val) ||
        /javascript:/i.test(val)
      ) {
        if (!issues.includes("sensitive_or_malformed_cell_content")) {
          issues.push("sensitive_or_malformed_cell_content");
        }
        break;
      }
    }

    // 1. Candidate ID resolution (NEVER use product display name)
    const rawCandidateId = record["candidate_id"] ? record["candidate_id"].trim() : "";
    let candidateId: string | null = null;
    if (rawCandidateId) {
      candidateId = rawCandidateId;
      if (seenCandidateIds.has(candidateId)) {
        issues.push("duplicate_candidate_id");
      } else {
        seenCandidateIds.add(candidateId);
      }
    } else {
      // Missing candidate ID. We strictly DO NOT derive one from supplier_title/product
      issues.push("missing_candidate_id");
    }

    // 2. Product Name / Title
    const productName = record["supplier_title"] ? record["supplier_title"].trim() : null;

    // 3. Supplier resolution & validation
    const rawSupplier = record["supplier"] ? record["supplier"].trim().toLowerCase() : "manual";
    const supplier = rawSupplier || "manual";
    if (!RECOGNIZED_SUPPLIERS.includes(supplier as RecognizedSupplier)) {
      issues.push("unsupported_supplier");
    }

    // 4. Currency
    const currency = (record["currency"] ? record["currency"].trim().toUpperCase() : "USD") || "USD";

    // 5. Unit Cost (preserves explicit zero vs missing)
    const unitCostParsed = parseNumericCost(record["unit_cost"]);
    if (unitCostParsed.isInvalid) {
      issues.push("malformed_unit_cost");
    } else if (unitCostParsed.isMissing) {
      issues.push("missing_unit_cost");
    }

    // 6. Shipping Cost (preserves explicit zero vs missing)
    const shippingCostParsed = parseNumericCost(record["shipping_cost"]);
    if (shippingCostParsed.isInvalid) {
      issues.push("malformed_shipping_cost");
    } else if (shippingCostParsed.isMissing) {
      issues.push("missing_shipping_cost");
    }

    // 7. Landed Cost (derived only when both unit cost and shipping cost are numeric)
    let estimatedLandedCost: number | null = null;
    if (unitCostParsed.value !== null && shippingCostParsed.value !== null) {
      estimatedLandedCost = Number((unitCostParsed.value + shippingCostParsed.value).toFixed(2));
    }

    // 8. Other numeric / text fields
    const rawMoq = record["moq"] ? parseInt(record["moq"].trim(), 10) : NaN;
    const moq = Number.isNaN(rawMoq) ? null : moqNonNegative(rawMoq);

    const rawQty = record["inventory_quantity"] ? parseInt(record["inventory_quantity"].trim(), 10) : NaN;
    const inventoryQuantity = Number.isNaN(rawQty) ? null : rawQty;

    const inventoryStatus = record["inventory_status"] ? record["inventory_status"].trim() : null;
    const deliveryWindow = record["delivery_window"] ? record["delivery_window"].trim() : null;

    const isValid = issues.length === 0;
    if (isValid) {
      validRowCount++;
    } else {
      invalidRowCount++;
    }

    previewRows.push({
      rowIndex,
      candidateId,
      productName,
      supplier,
      unitCost: unitCostParsed.value,
      isUnitCostExplicitZero: unitCostParsed.isExplicitZero,
      isUnitCostMissing: unitCostParsed.isMissing,
      unitCostDisplay: formatCostDisplay(unitCostParsed, currency),
      shippingCost: shippingCostParsed.value,
      isShippingCostExplicitZero: shippingCostParsed.isExplicitZero,
      isShippingCostMissing: shippingCostParsed.isMissing,
      shippingCostDisplay: formatCostDisplay(shippingCostParsed, currency),
      estimatedLandedCost,
      currency,
      inventoryQuantity,
      inventoryStatus,
      moq,
      deliveryWindow,
      isValid,
      validationIssues: Object.freeze(issues),
      rawFields: Object.freeze(record),
    });
  }

  return {
    fileName,
    totalRows: previewRows.length,
    validRowCount,
    invalidRowCount,
    rawHeaders: Object.freeze(rawHeaders),
    recognizedHeaders: Object.freeze(Array.from(recognizedHeadersSet).sort()),
    unrecognizedHeaders: Object.freeze(Array.from(unrecognizedHeadersSet).sort()),
    missingCandidateIdColumn: !hasCandidateIdHeader,
    evidenceMode: "manual_import",
    evidenceLabel: "Manual / Unverified Evidence",
    rows: Object.freeze(previewRows),
    fileLevelIssues: Object.freeze(fileLevelIssues),
  };
}

function moqNonNegative(val: number): number {
  return Math.max(1, val);
}
