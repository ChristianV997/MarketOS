# Research Query Plan

Canonical path: `services/research_query_plan/`.

Offline, deterministic planner that turns a short product brief into bounded,
source-specific search variants for **marketplace**, **supplier**, and
**consumer_attention** research. It does **not** call providers, assemble
provider URLs or CSVs, score opportunities, prove demand, or authorize launch.

## Operator brief

Required fields (mapping or `ProductResearchBrief`):

| Field | Meaning |
|---|---|
| `product_query` | Short product / query text (preserved verbatim after cleanup) |
| `category` | Category label for bounded synonym lookup |
| `region` | Target region label (e.g. `MX`, `US`, `ES`) |
| `language` | BCP-47-like tag; planning expansions support `en` and `es` |
| `intended_buyer` | `consumer` \| `business` \| `reseller` \| `unknown` |

## Example

```python
from services.research_query_plan import build_research_query_plan

plan = build_research_query_plan({
    "product_query": "portable blender",
    "category": "kitchen appliances",
    "region": "MX",
    "language": "es",
    "intended_buyer": "consumer",
})
assert plan.live_validated is False
assert plan.launch_authorized is False
for item in plan.queries:
    assert item.is_evidence is False
    assert item.source_family in {"marketplace", "supplier", "consumer_attention"}
```

## Behavior

- Emits the original query first for each source family.
- Adds bounded localization / category synonyms / family modifiers / buyer-intent
  and region labels from an explicit offline lexicon.
- Keeps supplier terms (e.g. wholesale, proveedor) out of marketplace-only rows
  and attention terms (e.g. review, reseña) distinct from supplier rows.
- Caps at 5 queries per source family and 15 total.
- Flags `ambiguous_brief` and `unsupported_language` instead of inventing copy.
- Rejects secret-shaped brief text without echoing secrets.

## Limitations

- Not evidence, not demand proof, not supplier availability, not live validation.
- Unsupported languages receive originals only (flagged); no machine translation.
- Lexicon coverage is partial; unknown categories do not invent attributes.
- Does not replace DataForSEO/SerpApi `discover_search_queries` stubs or wire
  provider clients; operators may feed planned `query_text` values into existing
  offline import / seed workflows manually.
- Does not modify opportunity synthesis, frontend, API routes, or research runners.
