# OSS source reuse catalog

Updated: 2026-09-24

## Status

`data/oss_source_intake.json` is an advisory intake catalog. It is not a source authority and it is not a fourth catalog beside the three records below. `catalog_status` is `advisory_intake_only` and `authority` is `none`.

A verdict in this file does not add a dependency, copy code, call a provider, or change runtime behavior. `copy_pattern` means a later, separate handoff could study a permissive pattern. It does not perform that copy. Rows with a non-null `registry_ref` leave `verdict` null. The registry is the single verdict authority for those rows. There is no `inherited` verdict value.

## Relation to the PR #272 registry

The canonical source list remains `data/source_adaptation_registry.json`, owned by the PR #272 lane, with `data/source_adaptation_work_orders.json` and `data/external_capability_catalog.json`. This intake does not edit those files.

Rows leave this intake only by an explicit handoff from the owner of PR #272. That handoff is the only promotion path into the source adaptation registry. Matching `registry_ref` values (`src-scrapy`, `src-duckdb`, `src-polars`) point at existing rows so those repositories are not registered again. Those three rows have `verdict: null`. The validator fails a non-null verdict on any row with `registry_ref` set, and it still requires an intake verdict when `registry_ref` is null.

`scripts/ai/validate_oss_source_catalog.py` is offline. It hard-fails intake violations and only reports existing defects in the canonical registry and the capability catalog. It does not rewrite them.

## Candidate table

Pins were resolved on 2026-09-24 with `git ls-remote` and the primary `LICENSE` file at that commit. Observation detail is on each row.

| source_id | work order | verdict | registry_ref | revision | tag | license |
|---|---|---|---|---|---|---|
| `oss-crawlee-python` | WO-C4-01 | copy_pattern | — | `ac6ebad10bedfb9111c4d95cda8a8831d28a31c5` | v1.9.3 | Apache-2.0 |
| `oss-trafilatura` | WO-C4-01 | copy_pattern | — | `c1bc9531a2a978326112ca9987e1382745116136` | v2.2.0 | Apache-2.0 |
| `oss-scrapy` | WO-C4-01 | null | src-scrapy | `b1f9e56693cd2000ddcea922306f726f3e9339af` | 2.12.0 | BSD-3-Clause |
| `oss-duckdb` | WO-C4-02 | null | src-duckdb | `19864453f7d0ed095256d848b46e7b8630989bac` | v1.1.3 | MIT |
| `oss-polars` | WO-C4-02 | null | src-polars | `87feed72585eff5acf3defb7f81029123d5cba68` | py-1.17.1 | MIT |
| `oss-networkx` | WO-C4-02 | copy_pattern | — | `49ca2290b80c1389eb4d8d8e49dcba73f8fec016` | networkx-3.7 | BSD-3-Clause |
| `oss-ortools` | WO-C4-03 | reference_only | — | `551ad10d94835c99e5e1e684500d3db398c0e345` | v9.15 | Apache-2.0 |
| `oss-ortools-dependency-weight` | WO-C4-03 | defer | — | `551ad10d94835c99e5e1e684500d3db398c0e345` | v9.15 | Apache-2.0 |
| `oss-simpy` | WO-C4-03 | copy_pattern | — | `f43816490c6f76f336ad6e457d3cab9f386894af` | 4.1.2 | MIT |
| `oss-un-comtrade-api-client` | WO-C4-04 | defer | — | `0848a3f1cf63234a93fb5635b9b19b2265afab71` | — | MIT |
| `oss-amazon-sp-api-models` | WO-C4-05 | defer | — | `3659f96867bfc669aca7a524c2f95744ff0e4478` | v2026.08 | Apache-2.0 |
| `oss-tiktok-business-api-sdk` | WO-C4-05 | sidecar | — | `f809c396520df2d7b201a9ccc5378d822b728ed3` | — | MIT |
| `oss-google-ads-python` | WO-C4-05 | defer | — | `48845cfdb8c9d7ea96930a13d9a14c19286c35e8` | 33.0.0 | Apache-2.0 |
| `oss-meta-ad-library-scripts` | WO-C4-REF | reference_only | — | `7c90db6f9a2f8342fba8e2e908b57220354b8d09` | — | LicenseRef-Facebook-API-connection |
| `oss-product-opportunity` | WO-C4-REF | reference_only | — | identity_unresolved, no URL | — | none_verified |
| `oss-gapscope` | WO-C4-REF | reference_only | — | identity_unresolved, no URL | — | none_verified |
| `oss-speculora` | WO-C4-REF | reference_only | — | `c429c24f1edac27f19ef2bb070936aa4be59e7d3` | — | CC-BY-4.0 |

Primary LICENSE URLs, each at the pinned commit:

- `oss-crawlee-python`: https://github.com/apify/crawlee-python/blob/ac6ebad10bedfb9111c4d95cda8a8831d28a31c5/LICENSE
- `oss-trafilatura`: https://github.com/adbar/trafilatura/blob/c1bc9531a2a978326112ca9987e1382745116136/LICENSE
- `oss-scrapy`: https://github.com/scrapy/scrapy/blob/b1f9e56693cd2000ddcea922306f726f3e9339af/LICENSE
- `oss-duckdb`: https://github.com/duckdb/duckdb/blob/19864453f7d0ed095256d848b46e7b8630989bac/LICENSE
- `oss-polars`: https://github.com/pola-rs/polars/blob/87feed72585eff5acf3defb7f81029123d5cba68/LICENSE
- `oss-networkx`: https://github.com/networkx/networkx/blob/49ca2290b80c1389eb4d8d8e49dcba73f8fec016/LICENSE.txt
- `oss-ortools`: https://github.com/google/or-tools/blob/551ad10d94835c99e5e1e684500d3db398c0e345/LICENSE
- `oss-ortools-dependency-weight`: https://github.com/google/or-tools/blob/551ad10d94835c99e5e1e684500d3db398c0e345/LICENSE
- `oss-simpy`: https://gitlab.com/team-simpy/simpy/-/blob/f43816490c6f76f336ad6e457d3cab9f386894af/LICENSE.rst
- `oss-un-comtrade-api-client`: https://github.com/uncomtrade/comtradeapicall/blob/0848a3f1cf63234a93fb5635b9b19b2265afab71/LICENSE
- `oss-amazon-sp-api-models`: https://github.com/amzn/selling-partner-api-models/blob/3659f96867bfc669aca7a524c2f95744ff0e4478/LICENSE
- `oss-tiktok-business-api-sdk`: https://github.com/tiktok/tiktok-business-api-sdk/blob/f809c396520df2d7b201a9ccc5378d822b728ed3/LICENSE.md
- `oss-google-ads-python`: https://github.com/googleads/google-ads-python/blob/48845cfdb8c9d7ea96930a13d9a14c19286c35e8/LICENSE
- `oss-meta-ad-library-scripts`: https://github.com/facebookresearch/Ad-Library-API-Script-Repository/blob/7c90db6f9a2f8342fba8e2e908b57220354b8d09/LICENSE
- `oss-product-opportunity`: no repository URL and no LICENSE file. A namesake repository was seen and was not verified as the intended project, so none was pinned.
- `oss-gapscope`: no repository URL and no LICENSE file. The name is shared by unrelated public repositories, so none was pinned.
- `oss-speculora`: https://github.com/speculora/speculora/blob/c429c24f1edac27f19ef2bb070936aa4be59e7d3/LICENSE

### Registry pointers

| intake id | registry_ref | repository |
|---|---|---|
| `oss-scrapy` | `src-scrapy` | https://github.com/scrapy/scrapy |
| `oss-duckdb` | `src-duckdb` | https://github.com/duckdb/duckdb |
| `oss-polars` | `src-polars` | https://github.com/pola-rs/polars |

Scrapy's registry `revision` and `commit_sha` both store annotated tag object `8c85937adef8279f12e35e0ee9a20c52ff6d1648` for tag 2.12.0. `git ls-remote` on 2026-09-24 showed that tag peels to commit `b1f9e56693cd2000ddcea922306f726f3e9339af`, which is the intake pin. This is a reported #272 defect: a tag-object SHA stored in a commit field. It is not a version conflict. The registry was not changed. The intake `verdict` is null because the registry is the verdict authority.

DuckDB `v1.1.3` and Polars `py-1.17.1` matched the registry commits directly. Newer tags were listed and were not used.

### Notes that are not promotions

- Crawlee `copy_pattern` excludes `fingerprint_suite`, `proxy_configuration.py`, session pools, curl impersonation, and browser automation observed at the pin. `relevant_module` is `src/crawlee/crawlers/_beautifulsoup/_beautifulsoup_parser.py` at `ac6ebad10bedfb9111c4d95cda8a8831d28a31c5`. That file exists at the pin and defines `BeautifulSoupParser`. `src/crawlee/http_clients/_httpx.py` is a network fetch client and is not the module for offline extraction from stored HTML fixtures.
- Trafilatura `copy_pattern` is allowed only because the LICENSE file at `v2.2.0` is Apache-2.0. Tag `v1.6.0` (`0bce2189288f4211e561c46083d7952fa65a7b72`) still had a GPL-3.0 LICENSE file when read the same day.
- OR-Tools dependency weight is `oss-ortools-dependency-weight` with verdict `defer`. The modeling row stays `reference_only`. GitHub reported repository size `1309998` on 2026-09-24. That number is not an approval to depend on the package.
- Crawlee is pinned at `apify/crawlee-python`, the Python repository. A re-read of the LICENSE blob at `ac6ebad10bedfb9111c4d95cda8a8831d28a31c5` is Apache-2.0, so the verdict stays `copy_pattern`. The JavaScript crawlee repository is not the pin.
- SimPy's canonical repository is GitLab `https://gitlab.com/team-simpy/simpy`. PyPI 4.1.2 names that Source code URL. `https://github.com/simpy/simpy` returned HTTP 404. Tag `4.1.2` peels to `f43816490c6f76f336ad6e457d3cab9f386894af`, and `LICENSE.rst` there is MIT. The exact-URL rule accepts any `https://host/owner/name` forge URL, including GitLab.
- UN Comtrade is `defer` only. The README at the pin takes a `subscription_key`. No key is stored and no call is made. The LICENSE copyright line names the Python Packaging Authority, not the UN.
- Platform SDKs are `sidecar` or `defer` only: Amazon SP-API models `defer`, TikTok Business SDK `sidecar`, Google Ads Python `defer`.

## Rejects and non-canonical names

- GapScope: `reference_only` with `identity_unresolved: true` and a null repository URL. A GitHub name search on 2026-09-24 returned several unrelated repositories. None was selected, and no LICENSE file was read. The license field is `none_verified`.
- product-opportunity: `reference_only` with `identity_unresolved: true`, a null repository URL, and license `none_verified`, the same field values GapScope uses. A namesake repository, `sprensis/product-opportunity`, was seen on 2026-09-24 and was not verified as the intended project. No URL, SHA, or license is claimed. No canonical upstream was established.
- Meta Ad Library scripts: `facebookresearch/Ad-Library-API-Script-Repository` is reference_only. Its LICENSE file is a Facebook API-connection grant, not a general OSI license. Unofficial scrapers were not pinned.
- Speculora: `speculora/speculora` is reference_only methodology. The LICENSE file at `c429c24f1edac27f19ef2bb070936aa4be59e7d3` was read and is CC BY 4.0 for documentation. `none_verified` does not apply. The name and logo are excluded.

## Reported defects, not fixed

The validator reports these and still exits 0 when the intake itself is valid:

- Patterned placeholder SHAs on `src-coderos`, `src-gstack`, and `src-hermes-ecc` in `data/source_adaptation_registry.json` (both `revision` and `commit_sha`).
- Annotated tag-object SHA on `src-scrapy`: `revision` and `commit_sha` both store `8c85937adef8279f12e35e0ee9a20c52ff6d1648`, the annotated tag object for 2.12.0, which peels to commit `b1f9e56693cd2000ddcea922306f726f3e9339af`. The validator reports this as `annotated_tag_object_sha`. It is not a version conflict, and the registry is not edited.
- All-zero `commit_sha` rows in `data/external_capability_catalog.json`, including `meta_ad_library` and `tiktok_creative_center` (15 rows on this base commit).

## Safety limits

- Offline validator and offline tests. No network calls at runtime.
- No scraper, proxy rotation, browser evasion, credential handling, or live provider call.
- No raw provider payload store and no external mutation.
- No new provider adapter and no edit to the three existing catalogs.
- Crawlee anti-blocking, fingerprint, and proxy surfaces are prohibited.
- GPL or AGPL, unknown, or missing licenses cannot be `integrate` or `copy_pattern`.
- Platform SDKs and the UN Comtrade client cannot be anything except `sidecar` or `defer`.
- At most five candidates per work order.
- A null repository URL is allowed only on `reference_only` or `reject` rows with `identity_unresolved: true`. `integrate`, `copy_pattern`, and `sidecar` cannot use a null URL.
- A non-null `registry_ref` requires `verdict: null`. A null `registry_ref` still requires an intake verdict. `inherited` is not a verdict.

## Validator

```bash
python scripts/ai/validate_oss_source_catalog.py --json
python scripts/ai/validate_oss_source_catalog.py --markdown
```

Exit `0` when the intake is valid. Reported registry and capability defects do not change that code. Exit `1` when the intake fails. Exit `2` when the intake file is missing.

## Rollback

Revert the single intake commit, or delete these four files:

- `data/oss_source_intake.json`
- `scripts/ai/validate_oss_source_catalog.py`
- `tests/contracts/test_oss_source_catalog.py`
- `docs/ai/OSS_SOURCE_REUSE_CATALOG.md`

Nothing else in the tree depends on them. The canonical registry, work orders, and capability catalog stay as they were.
