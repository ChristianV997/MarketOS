# Shopify Refund Reconciliation

This contract describes the offline reconciliation report built from an
imported Shopify orders CSV. It is a diagnostic/reporting boundary only. It
does not call Shopify, verify a live store, issue refunds, alter inventory, or
provide accounting authority.

## Inputs and evidence

The importer accepts the documented orders export shape and normalizes two
different observation types:

- An order row with `Refunded Amount` is an order-level observation. The value
  is retained as an imported refund total for that order.
- A refund or transaction row with an explicit `Order Id`, amount, currency,
  and transaction status is a transaction observation. Status is normalized to
  `successful`, `pending`, `failed`, `missing`, or `unknown`.

The report keeps these observations separate. A display name is never treated
as a verified reconciliation key. Matching requires an explicit order ID on
both sides. No raw CSV rows, customer fields, payment identifiers, or source
payloads are copied into the report.

Shopify documents `Refunded Amount` as the amount refunded on an order in an
orders export: <https://help.shopify.com/en/manual/fulfillment/managing-orders/exporting-orders>.
Shopify's richer API exposes an explicit refund-to-line relationship through
`RefundLineItem`, but that relation is not present in this CSV contract:
<https://shopify.dev/docs/api/admin-graphql/latest/objects/refundlineitem>.

## Reconciliation rules

- Amounts are parsed as decimal values and aggregated independently for each
  supported ISO currency. No FX conversion or cross-currency arithmetic is
  performed.
- An explicit `0.00` is a supplied zero and remains observable as such.
  Missing amount or currency remains unavailable and is never replaced with
  zero.
- Only successful transactions with an explicit matching order ID and the
  same currency can be compared with an order-level total.
- Pending, failed, missing-status, and unknown-status observations remain
  separate from successful totals. They can make coverage partial or the
  result inconsistent; they never become successful refunds.
- Unmatched order IDs, currency mismatches, duplicate/conflicting
  observations, and unverified display-name keys are reported as coverage or
  consistency findings. The report does not silently correct them.
- Correlation lists retain their existing field names for compatibility but
  contain deterministic opaque references, not source order, refund, or
  payment identifiers.
- Order-level refunds are classified per opaque order reference as `none`,
  `partial`, `full`, `over_refunded`, or `unknown` by comparing the imported
  refund amount with the imported order total. A missing amount, total, or
  currency keeps the scope `unknown`.
- SKU or line-item attribution is `unavailable` unless this input contract is
  extended with a stable refund-to-line relation. Order-level totals are not
  allocated across products. The report may include separately calculated
  imported SKU gross sales; missing line quantity or price remains an
  unavailable line count and is not filled with zero.

The resulting status is one of `reconciled`, `partial`, `inconsistent`, or
`unavailable`. A reconciled result means only that the imported observations
were internally comparable under the rules above. It is not live supplier,
payment, tax, or accounting validation.

## Safety and deterministic output

The JSON report and Markdown rendering contain bounded, deterministic,
redacted summaries. They retain the manual/imported evidence boundary and the
per-currency totals, counts, coverage findings, and unavailable line
attribution. Building or rendering this report performs no network, credential,
persistence, payment, order, inventory, or customer-mutation action.

The reconciliation report is consumed by the existing Shopify read-only
reporting path. It does not introduce a second money or accounting authority;
the canonical Decimal-based economics contract remains in
`backend/economics/kernel.py` for economics decisions outside this diagnostic
import report.
