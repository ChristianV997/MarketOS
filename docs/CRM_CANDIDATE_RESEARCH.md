# CRM candidate research

Updated: 2026-08-01

Scope: research only. No CRM dependency, provider-catalog entry, sidecar, or
adapter was added. The requested `backend/contracts/adapters.py::CRMProvider`
contract does not exist on the current merged `main`; the fit column therefore
maps each candidate to the intended operations (`upsert_contact`,
`create_opportunity`, `update_stage`, and `record_activity`) as a proposed
boundary rather than claiming an existing MarketOS interface.

## Recommendation

Do not integrate a CRM yet. If a CRM sidecar becomes a priority, evaluate
Krayin first for a narrow contact/opportunity/activity adapter, and Corteza
second if MarketOS needs configurable records and workflows. Keep the CRM
behind a new explicit adapter contract and preserve MarketOS as the owner of
workspace identity, attribution, approvals, and campaign decisions.

Krayin is the best license and domain fit among the reviewed candidates, but
its PHP/Laravel runtime and separate REST API package create meaningful
operational overhead. Corteza has the strongest API-centric and workflow story,
but is a broader low-code platform rather than a focused CRM. Neither justifies
adding a production dependency without a sidecar smoke test and contract
mapping first.

## Comparison

| Candidate | License / commercial disposition | Self-hosting | API surface | Maintenance signal | Fit to proposed CRM boundary | Decision |
|---|---|---|---|---|---|---|
| [Krayin CRM](https://github.com/krayin/laravel-crm) + [REST API](https://github.com/krayin/rest-api) | MIT, stated in the repository README | Apache or Nginx, PHP 8.3+, Composer, MySQL; documented installation and local server flow | REST API is provided as a separate package with Swagger documentation | Active repository with current releases and a large contributor/user footprint at review time | Contacts and leads map naturally to `upsert_contact`; sales/opportunity stages are plausible; activity logging needs endpoint validation; exact IDs, pagination, and auth semantics require a spike | Candidate 1 for later sidecar evaluation |
| [Corteza](https://github.com/cortezaproject/corteza) | Apache-2.0, stated in the repository README and LICENSE | Self-hostable; project documents DevOps setup and Docker/server deployment | API-centric platform with documented REST API, automation, RBAC, and flexible records | Active repository with a substantial commit history and current releases at review time | Flexible records can model contacts, opportunities, stages, and activities, but the mapping is configuration-dependent and less CRM-specific; requires a versioned schema/app definition | Candidate 2; use when workflow flexibility matters more than CRM fit |
| [EspoCRM](https://github.com/espocrm/espocrm) | AGPLv3, stated in the repository README and LICENSE; not suitable for the commercial core without legal approval | Self-hostable; documents PHP/database requirements and Docker installation | REST API backend | Active project with regular releases at review time | Excellent functional fit for contacts, opportunities, sales stages, campaigns, and activities | Reference/sidecar-only; legal review required |
| [SuiteCRM](https://github.com/SuiteCRM/SuiteCRM) | AGPLv3, stated in the repository README; not suitable for the commercial core without legal approval | Self-hostable on Linux/Windows or public cloud; LAMP-oriented | Mature CRM API surface is available, but exact versioned mapping should be tested against the chosen release | Mature project with current security/maintenance releases at review time | Strongest traditional CRM coverage, including accounts, opportunities, workflows, and reports | Reference/sidecar-only; legal review required |

## Evidence notes

- Krayin’s primary README identifies the MIT license, Laravel/Vue architecture,
  server requirements, local installation flow, and CRM-oriented features:
  [krayin/laravel-crm](https://github.com/krayin/laravel-crm).
- Krayin’s separate primary REST API repository documents installation through
  Composer and the Swagger endpoint:
  [krayin/rest-api](https://github.com/krayin/rest-api).
- Corteza’s primary README identifies Apache-2.0 licensing, self-hosting
  documentation, API-centric integration, workflows, and REST API guidance:
  [cortezaproject/corteza](https://github.com/cortezaproject/corteza).
- EspoCRM’s primary README identifies its REST API, self-hosting/Docker path,
  CRM entities, and AGPLv3 license:
  [espocrm/espocrm](https://github.com/espocrm/espocrm).
- SuiteCRM’s primary README identifies self-hosting, mature CRM capabilities,
  maintenance guidance, and AGPLv3 licensing:
  [SuiteCRM/SuiteCRM](https://github.com/SuiteCRM/SuiteCRM).

Stars and release recency were treated only as weak maintenance signals. A
future decision must additionally pin a release, inspect transitive licenses,
run the candidate’s official smoke test, and verify the four adapter operations
against a disposable instance.

## Follow-up spike, if approved

1. Define the missing `CRMProvider` protocol in `backend/contracts/adapters.py`
   with typed records, provenance, workspace, idempotency, and structured
   errors.
2. Run Krayin in an isolated sidecar and validate contact upsert, opportunity
   creation, stage update, and activity recording with duplicate requests.
3. Compare the same contract against Corteza before selecting one.
4. Add health, timeout, retry, and approval gates before any live CRM writes.
