# src-pyperf copy-pattern (draft)

Updated: 2026-09-27
Base: `origin/main` `e697f1c0365115cba2e96ff857a953377d5d261d`
Branch: `grok/source-adaptation-pyperf-copy-pattern-v1`
Mode: `copy_pattern` only. Do not merge until an operator re-runs in-tree pytest.

## Selected candidate

Highest-priority compatible work order with a vacant isolated boundary:

- source_id: `src-pyperf`
- upstream: https://github.com/psf/pyperf
- work-order target: `scripts/benchmarks/perf_engine.py` / `run_benchmark`
- authority: `scripts.benchmarks.perf_engine` (benchmark isolation; not a PRODUCTION_ROOT)

`integrate` was rejected: the registry evidence does not support vendoring pyperf or adding it as a runtime dependency. Host metadata collection and process runner stay out.

## Authoritative pin (verified 2026-09-27)

| Field | Evidence |
|---|---|
| Tag | `2.8.1` |
| Commit | `c58426688e1a28b2519695a3869b98dc51f3a69d` |
| Commit URL | https://github.com/psf/pyperf/commit/c58426688e1a28b2519695a3869b98dc51f3a69d |
| Message | Prepare the 2.8.1 release (#209) |
| License file at pin | https://github.com/psf/pyperf/blob/c58426688e1a28b2519695a3869b98dc51f3a69d/COPYING |
| License | MIT — Copyright 2016, Red Hat, Inc. and Google Inc. |
| Inspected paths | `pyperf/_bench.py` (JSON 1.0 suite), `COPYING` |

Registry-recorded SHA `c0e9eb8a78fd148f0746ba2b9cb030206dfd8478` is **not** a commit on `psf/pyperf`. The frozen catalog hash in `tests/contracts/test_source_adaptation_governance.py` is left unchanged on purpose.

## What shipped

- `scripts/benchmarks/perf_engine.py` — offline JSON 1.0 suite encoder from operator-supplied samples
- `tests/contracts/test_pyperf_suite_pattern.py`
- attribution rows in `THIRD_PARTY_NOTICES.md` and `docs/oss/LICENSE_MANIFEST.yml`

Runtime guarantees: no pyperf import, no sockets, no host metadata, no credentials, no live timing.

## Pin verification of named defects

| Record | Registry SHA / tag | Authoritative result | Action |
|---|---|---|---|
| src-coderos | `b980e90b49ea7c0639094f3060ced5aaf772a571` / frozen-control-plane | Commit exists on ChristianV997/CoderOS (2026-08-28) | Keep. reference_only. |
| src-gstack | `a6b3a57512ca6d5c6aa5b68f74f736195021f96e` / main | Commit exists. LICENSE at pin is MIT (Garry Tan) | Keep. reference_only. |
| src-hermes-ecc | `027d1a8a6043355b7af53b4c0645336b41372b7b` / main-reference | Commit exists on NousResearch/hermes-agent. LICENSE at pin is MIT (Nous Research) | Keep. reference_only. |
| src-scrapy | `8c85937adef8279f12e35e0ee9a20c52ff6d1648` / 2.12.0 | SHA is **not** a commit. Tag `2.12.0` is `b1f9e56693cd2000ddcea922306f726f3e9339af`. LICENSE at tag is BSD-3-Clause | Not rewritten (frozen catalog hash). emulate already claimed `backend.scouting.item_pipeline`. |
| src-pyperf | `c0e9eb8a78fd148f0746ba2b9cb030206dfd8478` / 2.8.1 | SHA is **not** a commit. Tag `2.8.1` is `c58426688e1a28b2519695a3869b98dc51f3a69d` | Implementation uses verified tag SHA. Catalog not rewritten. |
| src-crawl4ai | `b04ed9f3a941a96509272f3bc14be85f5767736a` / v0.4.2 | SHA is an **annotated tag object for v0.4.24**, not a commit and not v0.4.2. Peeled tag object points at `67d0999bc3973fd804e55e2320a92c886e28fde3`; `commits/v0.4.24` currently reports `bd71f7f4ea7854c4d1a8f86d42d0c58f3366ca8f` | Not rewritten. Main work order stays `defer`. Do not integrate. |
| capability catalog zeros | `0000000000000000000000000000000000000000` | Used on proprietary SaaS rows with `pinned_release: official-api` (e.g. Alibaba, CJ). There is no public git commit to pin | Left unchanged. Inventing a SHA would be false provenance. |

## Candidates rejected for this PR

- src-crawl4ai `integrate`: pin/tag mismatch; live browser worker; existing adapter already deferred on main.
- src-opentelemetry-python `copy_pattern`: would write `backend/observability.py` and collide with lineage_facets authority.
- src-saleor / src-vendure / src-medusa: commerce kernel / existing sidecar authorities.
- src-scrapy `emulate`: target already reserved; SHA unverified as a commit.

## Validation (sandbox)

```
pytest tests/contracts/test_pyperf_suite_pattern.py  # 8 passed in isolated package layout
```

Operator must re-run on a real checkout:

```
pytest tests/contracts/test_pyperf_suite_pattern.py tests/contracts/test_source_adaptation_governance.py tests/contracts/test_architecture_boundaries.py -q
python -m compileall scripts/benchmarks/perf_engine.py
```

## Rollback

Delete the changed paths in this PR. Registry and work-order hashes stay on main.
