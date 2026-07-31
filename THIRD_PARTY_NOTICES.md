# Third-party notices

MarketOS is intended for commercial distribution. Upstream source is not
copied into the MarketOS commercial core: reviewed systems are connected only
through adapters, optional Python profiles, or independently deployed
sidecars. This notice file is aligned with
[`docs/oss/LICENSE_MANIFEST.yml`](docs/oss/LICENSE_MANIFEST.yml) and is not
legal advice.

| Component | Reviewed reference | License | Distribution and notice |
|---|---:|---|---|
| medusa | v2.14.2 | MIT | Commerce sidecar; retain its upstream MIT notice. |
| crawl4ai | v0.8.6 | Apache-2.0-with-attribution | Optional research worker; retain Apache notice and required attribution. |
| browser-use | v0.13.6 | MIT | Optional browser worker; retain upstream MIT notice. |
| pydantic-ai | v2.20.0 | MIT | Optional typed-agent profile; retain upstream MIT notice. |
| postiz | pending-legal-review | AGPL-3.0 | Independently deployed sidecar only; commercial use requires explicit legal approval. |
| n8n | n8n@2.30.5 | Sustainable-Use | Internal operational sidecar only; do not embed or white-label without review. |
| erpnext | pending-deferred-review | GPL-3.0 | Deferred; do not vendor into the commercial core. |
| airbyte | pending-deferred-review | review_required | Deferred pending license and integration review. |
| saleor | pending-benchmark-review | review_required | Benchmark only; do not deploy alongside Medusa. |
| twenty-crm | pending-deferred-review | AGPL-3.0 | Deferred by explicit user decision; AGPL requires legal review before adoption. |
| chatwoot | pending-deferred-review | MIT | Deferred by explicit user decision. |
| cal.com | pending-deferred-review | AGPL-3.0 | Deferred by explicit user decision; AGPL requires legal review before adoption. |
| posthog | posthog-js@1.x | MIT | Client SDK (posthog-js) against PostHog Cloud; retain upstream MIT notice. Default-off via VITE_POSTHOG_KEY; no session-replay enabled. |
| temporal | pending-deferred-review | MIT | Deferred by explicit user decision; would replace hand-rolled workflow tracking if adopted later. |
| crawlee | pending-deferred-review | Apache-2.0 | Deferred; redundant with crawl4ai + firecrawl already selected. |

The generated release SBOM captures resolved Python packages actually present
in the build environment. Before enabling or updating any listed component,
review its exact release, transitive licenses, security posture, attribution,
and rollback plan according to `docs/oss/DEPENDENCY_POLICY.md`.
