# Gate-Driven Prompt Queue

Use one prompt at a time; do not start a downstream task until its stated gate
is true.

| Gate result | Next prompt |
|---|---|
| CJ validation pack reports `credential_missing` | “Guide the operator through server-side CJ credential setup; do not add code.” |
| CJ run observes supplier fields | “Record sanitized CJ live proof and compare it to the JS baseline.” |
| CJ response differs from fixture | “Harden only CJ read-only payload normalization with a sanitized fixture.” |
| CJ account/API is unsuitable | “Evaluate Zendrop read-only access; make no integration yet.” |
| CJ proof and benchmark matrix succeed | “Prove the read-only deployment stack from user-supplied URLs.” |

Every prompt must require: no mutation authority, no committed secrets or
artifacts, targeted tests, a draft PR, and an evidence-based final report.

Before a new prompt starts implementation, run the local quality gate against
the proposed paths. Do not use it to override an active supplier/live
validation PR; its role is to expose overlap and phase risk early.
