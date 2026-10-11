# Market Research Evidence Currency Comparability

`services.market_research_evidence` reports evidence quality; it does not rank
opportunities, calculate economics, convert currencies, or authorize a launch.
`backend.economics.kernel.Money` remains the only monetary value authority.

## Comparison contract

The report's `comparison_results` contains one deterministic result per observed
field. Results use these states:

- `comparable`: at least two independent, finite, current observations have
  the same explicit currency and unit and are within the existing tolerance.
- `conflict`: the same conditions hold, but the exact Decimal difference is
  outside the tolerance.
- `currency-mismatch`: explicit currencies differ; no implicit FX conversion
  occurs.
- `currency-missing`: a monetary observation has no valid supported currency.
- `unit-mismatch`: explicit units differ.
- `insufficient-evidence`: fewer than two supplied values, missing-versus-zero
  input, duplicate source observations, stale/future/unknown freshness, an
  unknown unit, or a non-finite/malformed numeric value prevents comparison.

Missing is never zero. Explicit zero is retained as a supplied amount, but it
cannot be compared with a missing value. Currency and unit metadata must be
provided by the observation or its typed `Money` value; the report assigns no
default currency, unit, exchange rate, or freshness.

The compatibility function `detect_field_conflicts` remains available for
legacy dimensionless numeric callers. New report consumers must use the strict
`compare_field_observations` result and inspect its state before treating a
value as reconciled.

All output remains fixture/manual/offline evidence. It is not supplier proof,
legal clearance, promotion approval, launch authorization, or live validation.
