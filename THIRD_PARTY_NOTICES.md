# Third-party software policy

MarketOS is intended for commercial distribution. Third-party source is not
copied into the commercial core unless its exact release, license, notices,
and transitive dependencies are reviewed and recorded in `docs/oss/INVENTORY.yml`.

Selected systems are integrated as adapters or independently deployed
sidecars. Their source repositories, trademarks, licenses, and security
updates remain separate from MarketOS.

Current review requirements:

- Medusa: MIT; pin the sidecar release and preserve notices.
- Crawl4AI: Apache 2.0 with the project attribution requirement.
- Browser Use: review the exact package release before installation.
- PydanticAI: MIT; pin the reviewed package release.
- Postiz: AGPL-3.0; production use requires an explicit compliance review.
- n8n: Sustainable Use License; internal automation only unless separately
  approved for the intended commercial product model.
- ERPNext: GPL-3.0; do not vendor into the MarketOS core.

This file is a project policy, not legal advice. Distribution decisions must
be reviewed against the exact versions actually shipped.
