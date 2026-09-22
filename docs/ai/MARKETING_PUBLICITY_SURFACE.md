# Marketing publicity surface

Updated: 2026-09-22

Client-safe planning view stacked on #306. It calls `composeStrategyView` and `buildClientSafeStrategyExport`. Research packets are checked against the same report and appendix versions as the cockpit contract. `launch_authorized: true` is rejected. Node cannot import `overlayResearchToDecision.ts` directly because that module's relative imports omit extensions; the surface still locks the production reason string `launch_authorized_rejected`.

Budget rows, funnel steps, and kill/iterate/scale rules are assumptions. Evidence labels are not proof. Human approvals stay ungranted. A research packet with `launch_authorized: true` is rejected by the existing validator.

This module is not mounted in the router and does not publish, spend, message, or call providers. Evidence for the tests is fixture-tested, not live-validated.
