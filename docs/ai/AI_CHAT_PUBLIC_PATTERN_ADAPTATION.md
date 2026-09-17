# Public pattern adaptation (AI-chat tooling lane)

Inspected 2026-09-17. Concepts only. No vendor source was copied and no
framework was installed.

| Source | URL | Pin | License | Pattern | Decision |
| --- | --- | --- | --- | --- | --- |
| OpenHands | https://github.com/OpenHands/OpenHands | v1.20.0 tag commit `9737f71` (2026-09-17) | MIT | Event-stream / workspace isolation, resume from stored conversation state | Emulate resume-from-artifact; reject runtime install |
| Aider | https://github.com/Aider-AI/aider | v0.86.2 documented pin; Apache-2.0 | Apache-2.0 | Repo map + Architect/Editor split + git-native commits | Emulate bounded repo context via packets; do not vendor Aider |
| SWE-agent | https://github.com/SWE-agent/SWE-agent | MIT project license (upstream now points research users at mini-SWE-agent) | MIT | Issue \u2192 trajectory \u2192 patch evaluation | Emulate claim-vs-command eval only |
| pre-commit | https://github.com/pre-commit/pre-commit | PyPI 4.6.2 (2026-08-10) | MIT | Hook allowlists before commit | Emulate path/secret allowlists; do not add a second hook runner |
| GitHub CLI workflows | https://cli.github.com / `gh pr` JSON | CLI absent in this sandbox | MIT | Structured PR metadata | Consume via existing `gh`; classify `unavailable` when missing |
| OpenTelemetry | https://github.com/open-telemetry/opentelemetry-specification | Apache-2.0 spec | Apache-2.0 | Explicit status + attributes | Emulate classification fields; do not install OTEL SDK |
| OpenLineage | https://github.com/OpenLineage/OpenLineage | 1.53.0 docs pin from prior MarketOS dossier | Apache-2.0 | Job/run/inputs/outputs facets | Already reserved by evidence lanes; not reimplemented here |
| OPA | https://github.com/open-policy-agent/opa | v1.20.2 tag `b2c2670` (2026-09-03) | Apache-2.0 | Deny-by-default policy documents | Emulate packet deny rules in stdlib; reject Rego runtime |
| Great Expectations | https://github.com/great-expectations/great_expectations | Apache-2.0 library | Apache-2.0 | Expectation suites over datasets | Reject as engine; eval rules stay hardcoded |
| reproducible-builds | https://reproducible-builds.org | policy docs | CC / project licenses | Deterministic artifacts + recorded inputs | Emulate SHA + command recording |

## Compatibility / risk

Installing any of the above would add a second orchestration or policy engine
next to MarketOS scripts. Secret surface and maintenance cost are high.
Adaptation is stdlib-only.

## Rejected alternatives

- Copying OpenHands/SWE-agent/Aider source into `scripts/ai/`
- Adding `.pre-commit-config.yaml` from this lane
- Shipping `openlineage-python`, `opa`, or GX Core
- Creating a second `operator_context_snapshot.py` (owned by #252)
