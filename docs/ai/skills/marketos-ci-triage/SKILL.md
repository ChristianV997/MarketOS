# MarketOS CI Triage

Use for a failing or slow check. Inspect the exact Actions log and changed
paths, then run `select_tests.py` and `ci_matrix_plan.py` locally.

Fix only a demonstrated regression. Do not rewrite workflows or mask flaky
tests without a root cause. Report failing command, root cause, targeted fix,
regressions run, remaining uncertainty, and measured timing if available.
