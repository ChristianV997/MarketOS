# Meta Ad Library advertiser-transparency evidence (offline contract)

Status: **implemented and fixture-tested; dry-run bridge only.** Not integration-tested. Not live-validated. No provider has been called and no credential has been used. A fixture is not an authenticated observation and not a performance outcome.

Primary pages read on **2026-10-13** (UTC). This reading does not authorize a live call.

| Capability | State |
|---|---|
| Offline contract and normalizer (`evaluation/commerce/meta_ad_library_evidence.py`) | Implemented |
| Synthetic fixture and offline tests (`tests/test_meta_ad_library_evidence.py`) | Tested (synthetic only) |
| Dry-run bridge (`backend/adapters/research/meta_ad_library.py`) | Dry-run |
| Live transport | Not implemented |
| Use in scoring, attention, purchases, or supplier evidence | Not implemented, deliberately |

## Primary sources read

| Page | What it is |
|---|---|
| [Ad Library API](https://www.facebook.com/ads/library/api) | Product page for access steps and what the API searches |
| [Graph API ads_archive v26.0](https://developers.facebook.com/docs/graph-api/reference/ads_archive/) | Query parameters, error 613, Archived Ad edge |
| [Graph API Archived Ad v26.0](https://developers.facebook.com/docs/graph-api/reference/archived-ad/) | Field list and per-field availability limits |
| [Ad Library tools](https://transparency.meta.com/researchtools/ad-library-tools) | Transparency Center, updated Aug 24, 2023 |
| [Platform Terms](https://developers.facebook.com/terms/) | Developer terms. Ad Library is not named |
| [Meta Terms of Service](https://www.facebook.com/terms.php) | Linked by the API page for creative content and data storage. The storage clause body was not readable in this session |
| [SIEP ad standards](https://transparency.meta.com/policies/ad-standards/SIEP-advertising/SIEP/) | Advertising policy, not the API query contract |

No undocumented endpoint was called. Meta was not called. Marketing API rate limits and Content Library rate limits are different products and are not applied here.

## Confirmed versus unknown

Confirmed from the pages above:

- Access, from the Ad Library API page: a Facebook account; identity and location confirmation at `facebook.com/ID` (the same process required to run ads about social issues, elections or politics; confirmation can take a few days); a Meta for Developers account that agrees to the Platform Policy; then **Access the API** and a new app. The documented example query includes an access token parameter. The FAQ question "Do I need an access token?" was listed, and its answer was not in the fetched page, so token type is not established.
- Searchable scope, from that same page: ads about social issues, elections or politics delivered anywhere in the world during the past 7 years; ads of any type delivered to the United Kingdom or the European Union during the past year.
- `ad_reached_countries` is required. The v26.0 parameter note says: "Ads that did not reach any location in the EU will only return if they are about social issues, elections or politics."
- `search_terms` is at most 100 characters. `search_page_ids` accepts up to ten Page IDs. This offline layer enforces the 100-character search-term cap and does not run Page-ID search.
- Error **613** means calls exceeded the rate limit. The ads_archive page does not state a numeric quota. The FAQ "What is the maximum number of ads a search can return?" was listed without an answer in the fetched page.
- Creating, updating, and deleting an Archived Ad are not supported.
- Individual ad creative (images and text) may be downloaded for analysis only, and must comply with the data-storage terms in the Terms of Service linked from the API page. The same page says a batch of archived ads cannot currently be downloaded.
- `publisher_platforms` search enum: FACEBOOK, INSTAGRAM, AUDIENCE_NETWORK, MESSENGER, WHATSAPP, OCULUS, THREADS, STREAMING_SERVICES. This layer stores only those tokens, in that case.
- Field limits on Archived Ad v26.0, which this layer still does **not** copy: `spend` and `impressions` are ranges and are available only for `POLITICAL_AND_ISSUE_ADS`; `delivery_by_region`, `demographic_distribution`, `bylines`, and `currency` are political-and-issue only; `eu_total_reach` and `beneficiary_payers` are EU-delivery only; `br_total_reach` is political-and-issue ads delivered to Brazil; `age_country_gender_reach_breakdown`, `target_ages`, `target_gender`, and `target_locations` are UK and EU delivery, plus political-and-issue ads delivered to Brazil; `total_reach_by_location` currently lists EU, BR, and UK. `estimated_audience_size` is described as an estimate of accounts meeting selected targeting and placement criteria. The search parameters that bound it are political-and-issue only; the field row itself does not repeat that limit.
- `ad_delivery_start_time` is when an advertiser wants delivery to start, in UTC. `ad_delivery_stop_time` is when an advertiser wants delivery to stop. If it is blank, Meta says the ad will run until the advertiser stops it or spends the campaign budget. That is advertiser intent, not an observation that the ad is live.
- Transparency Center (Aug 24, 2023): the Ad Library stores social-issue, election, and political ads for 7 years, active or inactive, and provides spend, reach, and funding entities for them. Ads that deliver an impression in the EU or associated territories are shown while active and archived for one year after the last impression. The API sentence on that page covers ads about social issues, elections or politics, and ads that deliver to the EU and associated territories. It does not mention the UK. Authorized users may also analyze active public branded content on Facebook and Instagram. This layer does not map branded content.
- SIEP policy: ads about social issues, elections or politics are not allowed to run in the European Union, except ads containing information about the time, place, and manner of voting or voter registration when placed by election authorities in the EU. That is an advertising rule, not a statement of what the API returns.
- Platform Terms section 3.a.iv prohibits selling, licensing, or purchasing Platform Data. Section 3.d requires deletion of Platform Data when keeping it is no longer necessary for a legitimate purpose consistent with those terms, unless law requires retention. Ad Library is not named.

Not established, and not collapsed into one rule:

- Whether a UK-only commercial ad that never reached the EU is returned by `ads_archive`. The landing page lists UK-or-EU any-type ads during the past year. The parameter note names only the EU for the non-political return rule. Both sentences are confirmed. They are not the same sentence.
- Whether "associated territories" (2023 Transparency Center) are inside the current landing page's "European Union", and whether "during the past year" is the same interval as "one year upon the delivery of their last impression".
- Numeric rate limit, numeric result cap, token type, and the meaning of FAQ error 1357045.
- Which clause of `facebook.com/terms.php` is the data-storage term. The page body was not readable here. Do not invent a retention period for copied creative.
- Cost. None of the pages read states a price. Do not treat the API as free.
- That the API returns commercial ads that reached neither the EU nor the UK and are not about social issues, elections, or politics. The landing page does not say that. The separate Ad Library website is described as a search of active ads; that is not this API.
- Any performance outcome: clicks, conversions, purchases, ROAS, or exact spend. The documented spend and impression values are ranges, and only in the political-and-issue scope above.

## What the fixture is allowed to mean

- `source_status` is `fixture_not_authenticated_observation`. `access_method` is `offline_fixture`.
- A parsed field is `supplied_fixture`. It is never `observed`, `live`, or `verified`.
- `delivery_status` is `stop_time_absent`, `stop_time_recorded`, or `unavailable`. It is not `delivering` or `ended`.
- Authority flags stay false: publish, spend, launch, supplier proof, product demand, decision scoring, customer attention, purchase evidence, targeting activation, campaign authority, performance outcome, authenticated observation, and live ad.
- Spend, impressions, reach, bylines, currency, and targeting values are removed even when the payload contains them. Their names may appear only as `unavailable`.

## Date window

- `date_min` and `date_max` are inclusive `YYYY-MM-DD` bounds. A window whose start is later than its end is refused.
- The rule compares the **UTC calendar day** of the supplied `ad_delivery_start_time`. Offsets are normalized first, so `2026-08-01T23:30:00-05:00` falls on `2026-08-02`. The rule is reported in `coverage.date_rule`.
- Meta documents that timestamp as advertiser-intended start, in UTC, with examples such as an offset written `+0000`. This layer accepts that offset and `Z`. The calendar-day comparison is still this layer's rule.
- A record with no valid start is dropped with `date_unverifiable` when a window is given.

## Geography filter in this layer

The contract requires the queried country to appear exactly in `ad_reached_countries`. Records without any country are dropped. That filter does not claim the API will return commercial ads for that country. Coverage for a target country still has to be checked against both official statements above before any future query.

## Costs

Unknown. No pricing statement was on the pages read.

## Fields

Mapped when present and valid, as `supplied_fixture` only: `id`, `page_id`, `page_name`, `ad_delivery_start_time`, `ad_delivery_stop_time`, `ad_reached_countries`, `publisher_platforms`, `ad_creative_bodies`, `ad_snapshot_url`.

Never mapped or copied, even if a response contains them: every name in `UNAVAILABLE_BY_POLICY`. Each is `unavailable` in `field_status`. Only the field names are listed back, in `policy_fields_present`.

`ad_creation_time` is on the Archived Ad reference and is not mapped. It is not a performance metric.

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

Every report sets these flags to `false`: `publish`, `spend`, `launch`, `supplier_proof`, `product_demand`, `decision_scoring`, `customer_attention`, `purchase_evidence`, `targeting_activated`, `campaign_authority`, `performance_outcome`, `authenticated_observation`, and `live_ad`.

Ad-library evidence is not customer attention, not a purchase, not supplier proof, and not permission to activate targeting or a campaign. It does not feed `evaluation/commerce/consumer_attention.py`.

## Response status semantics

- `ok`: the response was complete, and no record was dropped for a data-quality reason.
- `partial`: the response was not complete (a pagination link was present), or a record was dropped for a data-quality reason or only partly mapped, or the record limit was exceeded.
- Filter drops do not make a response partial. A complete response with no record naming the queried country is `ok` with zero records.
- `rate_limited`, `unavailable_access`, `upstream_unavailable`, `malformed_response`, `invalid_request`, `no_offline_response` and `blocked_live_mode` carry no records.
- An unexpected exception inside the builder is caught and reported as `malformed_response` with the blocker `offline_builder_failed`. It is never raised to the caller.
- `rate_limited` is a label for a supplied status. This layer does not retry and does not know Meta's numeric quota.

## What this adapter cannot establish

- Exact spend, impressions, reach, demographics, targeting, or audience size. Documented ranges and estimates are not copied and are not performance outcomes.
- Whether an advertiser is legitimate, or whether any ad converted, sold, or performed.
- That a blank `ad_delivery_stop_time` means the ad is live, or that a recorded stop time means delivery has ended.
- Completeness of coverage for any country or period. The UK landing-page sentence and the EU parameter note are not reconciled.
- Snapshot contents. References are not fetched.
- Product demand, supplier capability, customer attention, purchases, or any launch, spend, or targeting decision.
- Live availability of the provider.
- That every credential-shaped or contact-shaped string is withheld. See the sanitization limits above.

## Gates before any future live collection

The code gate is exactly `LIVE_PREREQUISITES` in `backend/adapters/research/meta_ad_library.py`. The bridge returns `blocked_live_mode` and names every entry. There is still no transport. Do not add one until all of the following are true:

1. An Approval Ledger `provider_call` approval exists for this provider.
2. A human has completed `facebook.com/ID` confirmation and created the Meta app. This repository does not do that.
3. The operator has accepted Platform Terms and the data-storage terms the Ad Library API page links. Acceptance is not recorded here. The unread `facebook.com/terms.php` storage clause still needs a human reading before any creative is stored.
4. Token type, numeric rate limit, result cap, and error 1357045 are taken from a primary page that actually states them. Do not borrow Marketing API or Content Library quotas.
5. The target country is checked against both the API landing page and the `ad_reached_countries` EU note. Do not treat UK-only commercial return as settled.
6. Spend, impression, reach, and targeting values stay unmapped. A documented range is not a performance outcome and is not campaign authority.
7. The credential reference is configured with the secret value absent. No environment variable is read by this layer.
8. A retry budget and a monthly or per-run call budget are approved. This layer allows zero retries.
9. Privacy review of advertiser identity and creative excerpts is complete, including whether whitespace-split credentials need a dedicated scanner before any excerpt is stored.
10. Output contract tests pass, and a separate review approves a live transport. That transport is not this pull request.

## Residual risks in existing code (not modified)

- `backend/discovery/ad_intelligence.py`, excluded from this work, has a live Meta path (`_live_search`) that runs when `ADLIB_DRY_RUN=false` and `META_ACCESS_TOKEN` is set. On any error it falls back to deterministic mock data, which is invented evidence. Recommend a follow-up that removes the fallback and sends the module through this layer's gates.
- `connectors/meta_ads_intel.py` makes a live `ads_archive` call with a caller-supplied token and has no dry-run gate. It is not used by this layer. Recommend a follow-up.
- `data/external_capability_catalog.json` rows `meta_ad_library` and `tiktok_creative_center` target `backend.adapters.creative.ad_library`, which does not exist. Their lifecycle fields claim `integration_tested: true` and reviewed terms. Neither is supported by the repository, and both `commit_sha` values are all zeros. Recommend correcting those rows.
- The consumer-attention vertical maps ad platform and ad-active fields into `AdSignalEvidence`, an engagement-style attention signal (`evaluation/commerce/consumer_attention.py`). That integration is separate and was not touched. This layer does not feed it.
