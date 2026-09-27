# Shopify Product Taxonomy — pinned partial snapshot

## Provenance

- **Upstream repository:** https://github.com/Shopify/product-taxonomy
- **Pinned tag:** `v2026-08`
- **Pinned commit:** `2e9aa2e9b882383952c63d212add13eb80f46cf9` (verified directly via
  `git ls-remote --tags` and a raw-content fetch of `VERSION` at that exact commit
  SHA — not taken from a cached or AI-summarized page render)
- **Upstream `VERSION` file content at that commit:** `2026-08`
- **License:** MIT (`Copyright (c) Shopify`) — see `THIRD_PARTY_NOTICES.md` at the
  repository root and `../source_adaptation_registry.json` entry `src-shopify-product-taxonomy`.
- **Source file:** `dist/en/categories.txt` at the pinned commit (a flat, plain-text
  export; 14,606 categories, one per line).

Do not confuse the `v2026-08-patch` tag with this pin: at inspection time its
annotated-tag object peeled to a different commit whose `VERSION` file read
`2026-11-unstable`, not a patch over `2026-08`. That mismatch between tag name
and tag content is exactly the kind of drift this repository's own AI policy
warns against trusting without direct verification, so `v2026-08` (the
lightweight tag whose target commit's `VERSION` file reads `2026-08` byte-for-byte)
is the one pinned here.

## What is bundled here, and what is deliberately excluded

`categories.v2026-08.partial.txt` is **not** a full mirror of the upstream
taxonomy. The upstream `dist/en/categories.txt` has 14,606 categories across
8 hierarchy levels; this file keeps only the top **3** levels (levels 1–3:
the 26 top-level verticals, their 218 direct children, and those children's
1,619 direct children — 1,863 rows total, ~190 KB). Levels 4–8 (the remaining
~12,743 more specific leaf categories) are excluded.

This is a deliberate scope boundary, not an oversight:

- It keeps the artifact small and easy to review/diff, per this repository's
  preference for a small, versioned data file over a large dependency or a
  runtime network fetch of the full upstream release.
- `services/category_mapping` treats every category outside this snapshot as
  **unmapped** and reports that explicitly as evidence for a human to review —
  it never invents, guesses, or silently widens coverage. See
  `docs/CATEGORY_MAPPING_EVIDENCE.md` for the full scope statement.

## Format

Unchanged from the upstream file, reproduced verbatim for every kept row
(only the file-level header comment differs, to record the trim):

```
gid://shopify/TaxonomyCategory/<code>   : <Ancestor name> > ... > <Category name>
```

- `<code>` is the upstream category code (e.g. `ap-2-1`); its hierarchy depth is
  the number of hyphen-separated segments (`ap` = level 1, `ap-2` = level 2,
  `ap-2-1` = level 3).
- The right-hand side is the full breadcrumb path from the top-level vertical
  down to the category itself, joined with ` > `.
- Every category's parent code (all but the last hyphen-separated segment) is
  itself present in this same file, for every row kept — the loader verifies
  this invariant at load time and fails closed if it is ever violated.

## Regenerating this snapshot

The exact, reproducible steps used to produce this file from the pinned
upstream source:

1. Fetch `dist/en/categories.txt` at commit `2e9aa2e9b882383952c63d212add13eb80f46cf9`.
2. Keep every line whose GID code has 3 or fewer hyphen-separated segments.
3. Prepend the provenance header above (as `#`-prefixed comment lines,
   matching the upstream file's own comment convention) in place of the
   upstream header.

No network fetch happens at MarketOS runtime or test time — this file is the
single, already-fetched, versioned input `services/category_mapping` loads.
