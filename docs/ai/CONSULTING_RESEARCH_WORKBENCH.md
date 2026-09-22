# Consulting research workbench

Route-independent frontend feature at `frontend/src/features/consulting-research-workbench/`. It is not mounted in the shared operator shell or router.

The feature adapts a `consulting-research-review-v1` packet into a view model and a client-safe export preview. Evidence classes are `observed`, `manual`, `fixture`, `derived`, `assumed`, and `unavailable`. Strings that claim `live` or `live_validated` normalize to `unavailable`. The surface never reports live validation or launch authorization.

Missing confidence, dates, and sources stay null. The adapter does not invent them. Export omits internal prompts, formulas, source code, credentials, raw payloads, hidden heuristics, and cross-client data.

Mount later by rendering `ConsultingResearchWorkbench` with a packet. Do not add a second API client from this feature.
