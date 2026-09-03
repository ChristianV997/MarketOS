# Client Workspace Evidence Boundary

`evaluation.trustos.client_workspace_isolation.export_client_evidence` is the
canonical offline boundary for a client-safe evidence projection. Callers must
provide a `ClientWorkspace` and the existing `WorkspaceRegistry`. The boundary
compares the supplied workspace with the durable registry record and derives
the exported identity from that record. This proves registry identity, but it
does not implement authentication, tenant authorization, a database, or RLS.

The export is deliberately a curated projection. Only the fields in
`CLIENT_EXPORT_FIELDS` are accepted, and the payload is capped at
`MAX_CLIENT_EVIDENCE_EXPORT_BYTES` (64 KiB). Workspace identity, provenance,
and evidence state are preserved in the returned envelope. Provenance is a
bounded `fixture://`, `manual://`, `derived://`, or `offline://` reference, not
a filesystem path or raw external payload.

The boundary fails closed for internal prompts, formulas, heuristics, strategy
or pricing notes, source code, cross-client or private-tenant data, credentials,
cookies, tokens, raw provider payloads, and secret-shaped values. Rejections
use fixed messages and do not reflect attacker values. Accepted envelopes use
canonical JSON for deterministic SHA-256 fingerprints and contain no sensitive
fields; this is validation, not a claim that sensitive data was safely scrubbed.

The implementation is fixture-backed and offline. It does not read credentials,
client data, private artifacts, provider responses, or generated files, and it
does not perform external actions.
