# Gate-Driven Prompt Queue

Use one prompt at a time; do not start a downstream task until its stated gate
is true.

| Gate result | Next prompt |
|---|---|
| Readiness cockpit reports `credential_missing` | â€œGuide the operator through server-side CJ credential setup; do not add code.â€ |
| CJ validation pack reports `credential_missing` | “Guide the operator through server-side CJ credential setup; do not add code.” |
| CJ run observes supplier fields | “Record sanitized CJ live proof and compare it to the JS baseline.” |
| CJ response differs from fixture | “Harden only CJ read-only payload normalization with a sanitized fixture.” |
| CJ account/API is unsuitable | “Evaluate Zendrop read-only access; make no integration yet.” |
| CJ proof and benchmark matrix succeed | “Prove the read-only deployment stack from user-supplied URLs.” |

Every prompt must require: no mutation authority, no committed secrets or
artifacts, targeted tests, a draft PR, and an evidence-based final report.

When credentials are unavailable, the allowed commercial prompt is: “Run the
offline marketplace trend intelligence slice against sanitized fixtures or a
manual import, enrich the existing Product Validation Report, and identify one
candidate for later supplier validation. Do not add a provider, scrape paid
dashboards, or claim supplier proof.”

After marketplace evidence exists, the next offline prompt is: “Run supplier
feasibility intelligence from sanitized CJ/Alibaba/AliExpress/manual imports,
add landed-cost and break-even scenarios to the existing Product Validation
Report, and preserve the credential-missing gate.”

Before a new prompt starts implementation, run the local quality gate against
the proposed paths. Do not use it to override an active supplier/live
validation PR; its role is to expose overlap and phase risk early.

When all three offline pillars are available, run: “Generate Product
Opportunity Synthesis v1 and Consulting Report v2 from the existing reports;
preserve provenance, add price/break-even thresholds and a fourteen-day plan,
and do not add live actions.”

When supplier and marketplace inputs exist but creative evidence is missing,
the next offline prompt is: “Run the consumer attention intelligence slice
from sanitized search, review, comment, and creative imports; enrich the
existing Product Validation Report with hooks and objections; do not call
platforms, launch ads, or publish content.”
* After Product Opportunity Synthesis: generate and review the Launch Draft Pack; resolve approval blockers before any future Launch Copilot work.
* After Launch Draft Pack: generate a site/store/funnel draft for the selected client type; resolve policy, asset, supplier, and platform-readiness blockers before implementation.
## CompanyOS prompts

1. Run the offline CompanyOS report and review the approval queue.
2. Replace finance assumptions with accountant-reviewed inputs.
3. Review one client handoff from opportunity → launch → site draft.
4. Review sales consent and do-not-contact status before any human-approved outreach.
