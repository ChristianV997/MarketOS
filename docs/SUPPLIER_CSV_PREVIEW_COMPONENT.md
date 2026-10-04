# Supplier CSV Preview Component Contract

## Overview

The `SupplierCsvPreview` component is a reusable, local-only React component that parses and previews supplier catalog CSV contents directly in the operator's browser before import.

It preserves canonical MarketOS boundaries:
1. **Local-only / Zero-transmission**: Performs pure browser-side parsing. Does not upload, persist, or transmit file contents over the network; adds no API calls or import authority.
2. **Manual/Unverified Evidence**: Prominently labels imported rows as `evidence_mode=manual_import` with a visible warning that previewed data does not constitute live supplier proof, validated inventory, or purchase authority.
3. **Missing Cost vs. Explicit Zero**: Strictly distinguishes missing costs (`null` / `"missing"`) from explicit zero (`0` / `"$0.00"`). Derived landed cost is computed only when both unit cost and shipping cost are numeric.
4. **Identity Integrity**: Never derives or slugifies a candidate ID from a product display name or title. Rows without an explicit `candidate_id` or recognized product ID alias are flagged with `missing_candidate_id`.

---

## Component Import & Usage

```tsx
import { SupplierCsvPreview } from "@/components/SupplierCsvPreview";
import type { SupplierCsvPreviewResult } from "@/lib/supplierCsvParser";

export function CockpitSupplierSection() {
  const handlePreviewChange = (result: SupplierCsvPreviewResult | null) => {
    if (!result) {
      console.log("No preview active or preview cleared");
      return;
    }
    console.log(`Parsed ${result.totalRows} rows (${result.validRowCount} valid, ${result.invalidRowCount} with issues)`);
  };

  return (
    <div className="space-y-4">
      <SupplierCsvPreview onPreviewChange={handlePreviewChange} />
    </div>
  );
}
```

---

## Props Specification

| Prop | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `initialCsvText` | `string` | `""` | Optional raw CSV text for controlled or testing usage. |
| `file` | `File \| null` | `null` | Optional pre-loaded `File` object from parent drag-and-drop or state. |
| `onPreviewChange` | `(preview: SupplierCsvPreviewResult \| null) => void` | `undefined` | Callback emitted whenever CSV is parsed, updated, or cleared. |
| `className` | `string` | `""` | Optional CSS classes applied to container wrapper. |

---

## Output Contract (`SupplierCsvPreviewResult`)

```typescript
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

export interface SupplierCsvRowPreview {
  readonly rowIndex: number;                  // 1-based data row index
  readonly candidateId: string | null;        // null if missing or invalid
  readonly productName: string | null;        // display name (never used as candidate ID)
  readonly supplier: string;                  // e.g. "cj", "alibaba", "manual"
  readonly unitCost: number | null;           // null if missing, 0 if explicit zero
  readonly isUnitCostExplicitZero: boolean;   // true if explicitly 0
  readonly isUnitCostMissing: boolean;        // true if omitted / empty
  readonly unitCostDisplay: string;           // "$0.00", "missing", "$12.50"
  readonly shippingCost: number | null;       // null if missing, 0 if explicit zero
  readonly isShippingCostExplicitZero: boolean;
  readonly isShippingCostMissing: boolean;
  readonly shippingCostDisplay: string;
  readonly estimatedLandedCost: number | null;// unitCost + shippingCost if both present, else null
  readonly currency: string;                  // e.g. "USD", "MXN"
  readonly inventoryQuantity: number | null;
  readonly inventoryStatus: string | null;
  readonly moq: number | null;
  readonly deliveryWindow: string | null;
  readonly isValid: boolean;                  // true if validationIssues.length === 0
  readonly validationIssues: readonly string[];
  readonly rawFields: Readonly<Record<string, string>>;
}
```

---

## Recognized Header Aliases

| Canonical Target | Recognized Aliases |
| :--- | :--- |
| `candidate_id` | `candidate_id`, `supplier_product_id`, `product_id`, `item_id`, `id`, `pid`, `productid` *(Never product titles)* |
| `supplier_title` | `supplier_title`, `title`, `product_title`, `product`, `name`, `nameen`, `productnameen` |
| `unit_cost` | `unit_cost`, `sellprice`, `regular_price`, `unitcost`, `supplier_cost`, `cost`, `price` |
| `shipping_cost` | `shipping_cost`, `shipping` |
| `currency` | `currency`, `price_currency` |
| `supplier` | `supplier`, `vendor` |
| `supplier_sku` | `supplier_sku`, `sku`, `variantsku`, `variant_sku` |
| `delivery_window`| `delivery_window`, `deliverycycle`, `deliverytime`, `lead_time_days`, `delivery_days` |
| `inventory_quantity` | `inventory_quantity`, `stock`, `inventory`, `inventoryquantity`, `stock_quantity`, `cjinventory`, `totalinventory` |
| `moq` | `moq`, `minimum_order_quantity`, `minimum_quantity`, `directminordernum`, `min_order_quantity` |
| `warehouse_region` | `warehouse_region`, `warehouse`, `origin`, `areaen`, `store_code`, `origin_country`, `countrycodeoforigin` |
| `destination_region` | `destination_region`, `destination`, `ship_to_country` |
