# Meta Ad Library advertiser-transparency evidence (offline contract)

Status: **implemented and fixture-tested; dry-run bridge only.** Not integration-tested. Not live-validated. No provider has been called and no credential has been used.

| Capability | State |
|---|---|
| Offline contract and normalizer (`evaluation/commerce/meta_ad_library_evidence.py`) | Implemented |
| Synthetic fixture and offline tests (`tests/test_meta_ad_library_evidence.py`) | Tested (synthetic only) |
| Dry-run bridge (`backend/adapters/research/meta_ad_library.py`) | Dry-run |
| Live transport | Not implemented |
| Use in scoring, decisions, attention or supplier evidence | Not implemented, deliberately |

## Source selection

The brief asked for Meta Ad Library to be evaluated first and, if it could not supply the required evidence under an official supported interface, for another official source to be selected. The primary documentation for every candidate was **not reachable** from this session. The egress policy returned HTTP 403 for `developers.facebook.com`, `www.facebook.com`, `developers.tiktok.com` and `adstransparency.google.com`. The proxy's guidance is not to route around a 403, so no alternative fetch path was used. Every claim below comes from secondary sources or from the repository's own records, and is labelled accordingly.

| Candidate | Official interface | Access, as reported (secondary, unverified) | Required evidence | Decision |
|---|---|---|---|---|
| Meta Ad Library API (`ads_archive`, Graph API) | Yes, Meta | Developer account identity verification, a Meta app, and acceptance of Ad Library API terms. Reported approval times vary. | Commercial-ad page identity, dates, countries and creative text are reported as available. Spend, impressions and targeting are reported as limited to political and social-issue ads. Sources disagree on commercial coverage. | **First candidate, not yet verified.** Implemented as the offline contract. Activation is blocked until primary-source verification. |
| TikTok Commercial Content Library and Research API | Yes, TikTok | Commercial Content Library reported as launched for European commercial content (2023). Research API reported as researcher-gated. | Unknown for the target geography. | Not implemented. Not verified. |
| Google Ads Transparency Center | Web interface | One secondary guide states that no official API exists. A BigQuery dataset was mentioned but not confirmed. | — | Excluded. No official programmatic interface was confirmed, and scraping is prohibited. |
| Meta Content Library | Yes, Meta | Researcher-gated, per one secondary source. | Unknown. | Not evaluated. |

Secondary sources consulted (search snippets only; none fetched):
- Meta reference page surfaced by search: https://developers.facebook.com/docs/graph-api/reference/ads_archive/ (returned, text truncated, not fetched)
- Third-party guides: https://www.admapix.com/blog/ad-intelligence/meta-ads-library-api-developers, https://metapi.io/compare/facebook-ad-library-api, https://www.hyperfx.ai/blog/meta-ad-library-api-scraper-guide, https://adligator.com/blog/meta-ad-library-api-competitor-monitoring
- TikTok: https://techcrunch.com/2023/07/20/tiktok-ads-transparency/
- EU DSA ad repositories: https://adlibrary.com/posts/eu-dsa-ad-repositories-developers, https://foundation.mozilla.org/documents/363/Full_Disclosure_Stress_Testing_Tech_Platforms_Ad_Repositories_3FepU2u.pdf

The guides disagree with each other on coverage, access and rate limits, and several are sold as data products. Treat them as leads only.

## Official access requirements (to verify, not verified)

- Developer account identity verification, and possibly a stricter check for political-ad data. Reported as several days to two weeks.
- A registered Meta developer app and a user access token. One guide says user tokens expire after 60 days.
- Acceptance of Ad Library API terms. One guide calls them "Authorized Access to Public Information".
- Rate limits reported as roughly 200 calls per hour per app, with higher quotas granted case by case. This is unverified. The offline layer allows **zero** retries, and it never reads a `Retry-After` value to schedule a call.

## Terms limitations (to verify)

- Reported prohibition on using archive data to build ad-targeting or resale products, with token or app revocation as the enforcement risk.
- Terms-review status in the repository's capability catalogue is recorded as `reviewed`. That record is not backed by a primary-source reading in this session, and its `commit_sha` is all zeros. Treat it as unverified.
- The repository's OSS intake read the LICENSE of `facebookresearch/Ad-Library-API-Script-Repository` directly at a pinned commit. It is a Facebook API-connection grant, not an open-source license. Its verdict is `reference_only`: do not run it, send tokens, call the API, scrape, or store payloads. Nothing from it is used here.

## Geography coverage (unverified)

The contract requires the queried country to appear exactly in `ad_reached_countries`. Records without any country are dropped. The layer makes **no** coverage claim, because sources disagree on whether commercial ads outside the EU and UK are returned. Coverage must be verified for each target country before any use.

## Date window

- `date_min` and `date_max` are inclusive `YYYY-MM-DD` bounds. A window whose start is later than its end is refused.
- The rule compares the **UTC calendar day** of `ad_delivery_start_time`. Offsets are normalized first, so `2026-08-01T23:30:00-05:00` falls on `2026-08-02`. The rule is reported in `coverage.date_rule`.
- A record with no valid start is dropped with `date_unverifiable` when a window is given.
- The provider's own date semantics are not verified. The UTC rule is this layer's choice, not a documented provider behaviour.

## Costs

The capability catalogue says "free (with API access)". No pricing source was reached. Costs are unverified.

## Fields

Working field set (from secondary sources, unverified against the primary reference):

- Mapped when present and valid: `id`, `page_id`, `page_name`, `ad_delivery_start_time`, `ad_delivery_stop_time`, `ad_reached_countries`, `publisher_platforms`, `ad_creative_bodies`, `ad_snapshot_url`.
- Never mapped or copied, even if a response contains them: `spend`, `impressions`, `delivery_by_region`, `demographic_distribution`, `estimated_audience_size`, `eu_total_reach`, `target_ages`, `target_gender`, `target_locations`. Each is reported as `unavailable` in `field_status`. Only the field names are listed back, in `policy_fields_present`.

Derived status (`delivery_status`):
- `unavailable` when the start is absent or malformed, and also when the stop time is malformed or earlier than the start. A status is not inferred from a timeline that cannot be trusted.
- `ended` when the start is valid and a valid stop time is present.
- `delivering` when the start is valid and no stop time is present.
- It describes the archive at observation time, not a live state.

Duplicates: the first entry for an identifier that passes the caller's filters is kept. Later entries with the same identifier are dropped as `duplicate_id`. A filtered-out entry never shadows a valid one.

Read-only results: reports, records, counts, authority flags and field status are read-only mappings. They are not `dict` instances, so `dict.__setitem__` does not apply. Item assignment, attribute assignment and `dict.__setitem__` all raise `TypeError`, and the stored values do not change. Each report has its own authority mapping, so changing one report does not affect another. These guarantees hold after a pickle or deep-copy round trip. The module-level authority defaults are read-only as well. Access to private storage through `object.__setattr__` is outside this guarantee.

## Sanitization

Text is prepared in two forms. The output form, which is what an excerpt stores, applies NFKC, decodes HTML entities, maps ideographic full stops (U+3002) to `.`, removes format characters (category `Cf`), and turns tab, newline, carriage return and vertical tab into spaces. Accents are kept. Other control characters are deleted with no gap, so they cannot split a token. The cost is that such a character between two words joins them. The stored excerpt then has its tags removed and its whitespace collapsed.

Every detection rule runs on a second form instead. It decodes entities first, applies NFKD, maps U+3002, and deletes combining marks (`Mn`), enclosing marks (`Me`), format and control characters, and the default-ignorable letters U+115F, U+1160, U+3164, U+FFA0 and U+2065. Accented letters therefore match their base letters, so `pássword` is checked as `password`. Tags are removed after the bracket check, and whitespace is then collapsed.

Creative text and advertiser names are withheld entirely, never partly redacted, when the normalized text matches any of these rules:

- **Address.** Any `@`, a scheme (`http:`, `https:`, `ftp:`, `javascript:`, or `data:` followed by a media type and a slash), the word `www`, or `at` or `dot` as the whole content between an opening bracket (`[`, `(`, `{` or `<`) and a closing bracket (`]`, `)`, `}` or `>`), with optional spaces. The bracket check runs on the detection form before tags are removed, so `<at>` is caught. Marks and invisible characters inside the brackets are removed first, so `<` followed by a variation selector and `at` still matches. Only the whole content counts. A bracket pair that holds other words as well, such as `(at domain dot com)`, is not matched; see the residuals below.
- **Domain.** A label of letters, digits, underscores or hyphens in any script, a full stop, then two or more letters. Labels such as `müller.de` match. Ideographic full stops count as full stops. A full stop followed by letters with no space is also treated as a domain, so `Ships in two days.Really` is withheld. This false positive is accepted, because the rule fails closed.
- **Phone.** Ten or more digits in one text, where neighbouring digits may be separated by up to four non-word characters, such as spaces, dashes, slashes, dots, en-dashes, double dashes or parentheses. Dash-grouped numbers such as `06-12-34-56-78` match. Calendar dates are not exempt. A single date such as `2026-08-01` has eight digits and is kept, but two dates in one text, or a date followed by a few more digits, are withheld. This over-redaction is accepted, because the rule fails closed.
- **Token prefix.** `sk_`, `pk_` or `rk_` followed by eight or more letters, digits, underscores or hyphens. `ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_` and `github_pat_` followed by eight or more characters. `xox` followed by `b`, `a`, `p`, `r` or `s`, then a hyphen. `AKIA` followed by sixteen uppercase letters or digits. `EAA` followed by twelve or more letters or digits. The prefix must start at a letter-or-digit boundary, so `my_sk_live_…` matches and `Skateboarding` does not.
- **Credential keyword.** `access token`, `auth token`, `api key` and `private key`, with any run of spaces, underscores or hyphens between the words. `bearer`, `password` and `passwd` anywhere in the text, so `Login password123` and `passwordXYZ` match. `secret` or `secrets` as a standalone word, and `secret` followed by `key`, `token`, `value` or `code` as one word, so `SECRETKEY=abc` matches while `Secretary` does not.
- **Credential-shaped run.** Sixteen or more letters and digits in one run, or twenty or more letters, digits, underscores, dots or hyphens in one run, where the run contains both letters and digits. This catches JWTs.

Limits, recorded as residual rather than solved:
- Credentials split by whitespace, such as `sk_ab cdefgh1234`, are not detected.
- Natural-language obfuscation such as "name at domain dot com" is not detected.
- A bracketed `at` or `dot` with other words inside the brackets, such as `(at domain dot com)`, is not detected. The rule matches only the whole content of a bracket pair.
- Full stops from other scripts, such as the Arabic full stop (U+06D4), are not mapped to `.`, so `example۔com` is kept. U+3002 is mapped directly. Full-width and halfwidth stops reach `.` through NFKC or NFKD.
- Credential keywords inside camelCase identifiers, such as `clientSecret`, are not matched, because `secret` is not standalone there.
- `secret` followed by a suffix outside `key`, `token`, `value` and `code`, such as `secretid`, is not matched.
- Cyrillic, Greek and other homoglyphs are not mapped to Latin letters, so `Login pаssword123` written with a Cyrillic letter is kept.
- The excerpt is therefore **not a secret-scanning boundary**. Do not store or display excerpts as trusted content until a dedicated scanner is approved.

Other rules:
- Creative excerpts are capped at 280 characters and flagged when truncated. Advertiser names longer than 100 characters are withheld, not shortened.
- Text over 2,000 characters is withheld before any pattern work, both as supplied and after NFKC normalization, which can expand a character many times over. The detection form can be longer again, since NFKD expands one code point to at most eighteen characters, so it is at most about 36,000 characters for a bounded text. Detection runs about ten regular-expression scans per text, each linear in that length.
- Snapshot references are accepted only when they are `https`, contain no whitespace or control characters, and carry no user information. The query string and fragment are removed. Host and path are percent-decoded repeatedly, up to sixteen passes; a value that still changes is withheld. Both are then checked on the detection form, once with tags present and once with tags removed, for `@`, a scheme, a bracketed `at` or `dot`, credential keywords and credential-shaped runs. The tags-present pass matters because the returned reference keeps its tags. The domain, phone and `www` rules do not apply to them, because a snapshot host is expected to be a domain. A non-HTTPS value, or one with user information, is reported as `malformed` and yields no reference. An absent reference is reported as `unavailable` with no warning.
- Error bodies are read for their status only. Provider messages are never echoed.

## Authority

Every report declares `publish`, `spend`, `launch`, `supplier_proof`, `product_demand` and `decision_scoring` as `false`. Ad evidence is research context about public advertiser activity. It is not supplier proof, not product demand, and not a decision input.

## Response status semantics

- `ok`: the response was complete, and no record was dropped for a data-quality reason.
- `partial`: the response was not complete (a pagination link was present), or a record was dropped for a data-quality reason or only partly mapped, or the record limit was exceeded.
- Filter drops do not make a response partial. A complete response with no record naming the queried country is `ok` with zero records.
- `rate_limited`, `unavailable_access`, `upstream_unavailable`, `malformed_response`, `invalid_request`, `no_offline_response` and `blocked_live_mode` carry no records.
- An unexpected exception inside the builder is caught and reported as `malformed_response` with the blocker `offline_builder_failed`. It is never raised to the caller.

## What this adapter cannot establish

- Spend, impressions, reach, demographics, targeting or audience size.
- Whether an advertiser is legitimate, or whether any ad converted, sold, or performed.
- Completeness of coverage for any country or period, or whether the archive is complete for a query.
- Current delivery state beyond the observation time. Snapshot references are not fetched, and their content is not verified.
- Product demand, supplier capability, or any launch or spend decision.
- Live availability of the provider, or the accuracy of any field name.
- That every credential-shaped or contact-shaped string is withheld. See the sanitization limits above.

## Live gate and verification

The code gate is exactly `LIVE_PREREQUISITES` in `backend/adapters/research/meta_ad_library.py`. The bridge returns `blocked_live_mode` until a live transport exists, and it names every entry. The steps below are a documentation checklist. Code does not enforce them, and each must be completed before any activation is proposed.

Verification checklist (documentation only):
1. Read the current Meta Ad Library API reference and its terms in full, from primary sources. Record the date and the URL of each reading.
2. Confirm the access process, including identity verification and any political-ad-only gating. Record what a standard developer account can see.
3. Confirm, per field, which are returned for commercial ads. Update the field policy only if the primary reference supports it. Keep spend, impressions and targeting unavailable unless scope explicitly permits them.
4. Confirm the geography coverage for each target country, and any EU or UK disclosure coverage.
5. Confirm rate limits, retry policy and the pagination contract. Correct the zero-retry assumption only with evidence.
6. Confirm the cost model, if any is documented.
7. Satisfy every entry of `LIVE_PREREQUISITES`:
   - approved Approval Ledger request (approval_request_type=provider_call)
   - developer identity verification and Meta app access (primary-source requirement, not verified here)
   - primary-source verification of Ad Library API access, terms, and commercial research use
   - geography coverage verified against primary documentation for the target country
   - field availability verified against primary reference; spend, impression and targeting scope kept unavailable
   - credential reference configured (credential-meta-ad-library, secret value absent)
   - rate-limit policy and retry budget defined for a real transport
   - monthly or per-run call budget approved
   - privacy review of advertiser identity and creative excerpts complete
   - output contract tests passing
   - a separately reviewed live transport implementation
8. Decide whether whitespace-split credentials need a dedicated scanner before any excerpt is stored or shown.

## Residual risks in existing code (not modified)

- `backend/discovery/ad_intelligence.py`, excluded from this work, has a live Meta path (`_live_search`) that runs when `ADLIB_DRY_RUN=false` and `META_ACCESS_TOKEN` is set. On any error it falls back to deterministic mock data, which is invented evidence. Recommend a follow-up that removes the fallback and sends the module through this layer's gates.
- `connectors/meta_ads_intel.py` makes a live `ads_archive` call with a caller-supplied token and has no dry-run gate. It is not used by this layer. Recommend a follow-up.
- `data/external_capability_catalog.json` rows `meta_ad_library` and `tiktok_creative_center` target `backend.adapters.creative.ad_library`, which does not exist. Their lifecycle fields claim `integration_tested: true` and reviewed terms. Neither is supported by the repository, and both `commit_sha` values are all zeros. Recommend correcting those rows.
- The consumer-attention vertical maps ad platform and ad-active fields into `AdSignalEvidence`, an engagement-style attention signal (`evaluation/commerce/consumer_attention.py`). That integration is separate and was not touched. This layer does not feed it.
