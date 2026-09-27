# Marketing publicity surface

Updated: 2026-09-22

#306 and #315 are one planning surface. `StrategyWorkbench` renders the publicity scenario. `PublicitySurface` is that same component. There is no second campaign planner and no router mount.

Budget rows, funnel steps, and kill/iterate/scale rules are assumptions. Evidence labels are not proof. Human approvals stay ungranted. A research packet with `launch_authorized: true` is rejected by the existing validator.

This module does not publish, spend, message, or call providers. Evidence for the tests is fixture-tested, not live-validated.

## Dependency

Route registration overlaps the #298 shell. This integration branch starts at #298 `6f64b9a` and merges #321 `660cd1f` with ancestry preserved. #298 itself is not rewritten.

One route: `/operator/marketing-strategy`, registered in `frontend/src/main.tsx` and `Sidebar.tsx`. It renders `MarketingStrategyPage`, which calls `composePublicityScenario` and `StrategyWorkbench`. `PublicitySurface` remains an alias and is not mounted a second time. The page is fixture-backed. It does not add a GET client. `live_validated=false` and `launch_authorized=false` stay visible.
