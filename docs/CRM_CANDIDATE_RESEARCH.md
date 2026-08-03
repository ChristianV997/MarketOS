# CRM candidate research (MIT/Apache/BSD alternatives)

**Status: research-only.** No adapter, catalog entry, or code change is
part of this document — see `backend/contracts/adapters.py::CRMProvider`
for the existing Protocol this research is evaluated against, and
`docs/oss/LICENSE_MANIFEST.yml` for the existing license-review convention
this doc follows. Building an adapter for any candidate below is a
follow-up decision, not something this doc does.

## Why this doc exists

`CRMProvider` (`upsert_contact` / `create_opportunity` / `update_stage` /
`record_activity`) has no concrete adapter today. The one CRM this
Protocol was designed against, Twenty, is AGPL-3.0 and deferred pending
legal review (`docs/oss/LICENSE_MANIFEST.yml`); the only CRM-capable
provider with a live recommendation path today is GoHighLevel
(proprietary), via `backend.stack_planner`. This doc asks: is there a
permissively-licensed (MIT / Apache-2.0 / BSD), genuinely self-hostable
CRM that could fill that gap without an AGPL-style legal-review gate?

## Candidates evaluated

Krayin CRM, Corteza, EspoCRM, and SuiteCRM were evaluated. Every license
claim below was checked against the project's actual repository (LICENSE
file or the README's direct pointer to it), not a secondary listicle.

| Candidate | License (verified) | Self-hostable | API | Maintenance signal | `CRMProvider` fit |
|---|---|---|---|---|---|
| **Krayin CRM** | **MIT** — verified directly against [`LICENSE`](https://github.com/krayin/laravel-crm/blob/master/LICENSE): "MIT License / Copyright 2010-2025, Webkul Software" | Yes — Laravel/Vue app, Docker-deployable ([Railway one-click deploy](https://railway.com/deploy/krayin) exists) | Yes — Sanctum-auth REST API with a public Swagger UI ([`apidoc.krayincrm.com/api/documentation`](https://apidoc.krayincrm.com/api/documentation), [getting-started doc](https://devdocs.krayincrm.com/2.2/api/getting-started-with-the-api.html)); full CRUD across Leads, Persons (contacts), Organizations, Activities, Products | v2.2 current, 4,289 commits, 23.6k stars/1.6k forks, 87 open issues/37 open PRs — actively developed ([repo](https://github.com/krayin/laravel-crm)) | **Good.** Leads have configurable pipeline stages (Settings → Pipelines: Qualified/Proposal/Negotiation/Won) — maps directly to `create_opportunity`/`update_stage`. Persons endpoint → `upsert_contact`. Activities endpoint → `record_activity`. Closest shape match of the four. |
| **Corteza** | **Apache-2.0** — verified from the [repo README](https://github.com/cortezaproject/corteza): "Corteza is released under the Apache-2.0 license," pointing to its [LICENSE file](https://github.com/cortezaproject/corteza/blob/2024.9.x/LICENSE) | Yes — Docker images published ([Docker Hub](https://hub.docker.com/r/cortezaproject/corteza-server)) | Yes — REST API + websockets between front/back end; a "Ready to Use CRM" template ships contact management, lead tracking, sales pipeline as a pre-built low-code module ([cortezaproject.org/features/corteza-crm](https://cortezaproject.org/features/corteza-crm/)) | **Concern.** Latest tagged release found is `2024.9.9` (June 2024) — roughly two years stale as of this doc's writing (2026-08). Release cadence looks to have slowed significantly versus Krayin. | **Weaker, and structurally different.** Corteza is a low-code platform, not a pre-built CRM — its CRM is a *template module* you configure, so `upsert_contact`/`create_opportunity`/etc. would map to a custom Compose-module schema you define yourself rather than a fixed, documented endpoint set. More integration work than Krayin for an equivalent result, on top of the maintenance concern. |
| **EspoCRM** | **AGPL-3.0** — verified directly against [`LICENSE.txt`](https://github.com/espocrm/espocrm/blob/master/LICENSE.txt): "GNU AFFERO GENERAL PUBLIC LICENSE / Version 3" | Yes | Yes — REST API backend | Active | **Disqualified from the permissive bucket.** Same AGPL-3.0 status as Twenty (already deferred) and Postiz/Cal.com — would need the same legal-review gate this research was meant to avoid. Not evaluated further. |
| **SuiteCRM** | **AGPL-3.0** — verified from the [repo](https://github.com/SuiteCRM/SuiteCRM-Core): "SuiteCRM is published under the AGPLv3 license" | Yes | Yes — open REST API, SuiteCRM 8 is an API-first Angular/Symfony rebuild | Active — v8.10.2 current | **Disqualified from the permissive bucket** for the same reason as EspoCRM. Not evaluated further. |

## Recommendation

**Krayin CRM (MIT)** is the only candidate that is both genuinely
permissively licensed and a pre-built CRM (not a low-code platform
requiring its own data-modeling work) with an API surface that maps
cleanly onto the existing `CRMProvider` Protocol shape: Leads-with-
pipeline-stages → `create_opportunity`/`update_stage`, Persons →
`upsert_contact`, Activities → `record_activity`. It is also the most
actively maintained candidate found (current release, high commit/PR
volume vs. Corteza's ~2-year-stale last tag).

Corteza is Apache-2.0 and technically self-hostable with a CRM template,
but its low-code-platform nature means building a `CRMProvider` adapter
against it would mean designing and maintaining a custom Compose-module
schema rather than calling a fixed, documented CRM API — meaningfully more
integration surface than Krayin for a comparable result — compounded by
its maintenance signal looking considerably weaker.

EspoCRM and SuiteCRM were both discarded early: both are AGPL-3.0,
identical to Twenty's already-deferred status, so neither would actually
solve the problem this research set out to address (avoiding another
legal-review-gated candidate).

**If a CRM adapter is built next, Krayin is the candidate this research
recommends starting with** — but building it (adapter code, credential
wiring, tests, `docs/oss/LICENSE_MANIFEST.yml` entry) is an explicit
follow-up decision for the repo owner, not something this document does.
