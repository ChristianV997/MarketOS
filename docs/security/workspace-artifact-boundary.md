# Workspace artifact path boundary

Canonical owner: `backend/workspaces/artifact_store.py`.

Artifact paths are always:

```text
state/workspaces/{workspace_id}/experiments/{experiment_id}/{filename}
```

An `ArtifactStore` is constructed with a `ClientWorkspace` principal and the
existing `WorkspaceRegistry`. Before every filesystem operation, the store
reloads that principal and requires an exact registry match. Callers cannot
choose a workspace by passing a raw workspace ID to save, load, list, or path
operations. A caller that has not registered a workspace is rejected before
path resolution.

`workspace_id`, `experiment_id`, and `filename` are non-empty single path
segments. The store rejects:

- parent-directory segments (`..`)
- absolute paths (`/etc/passwd`, `C:\...`)
- sibling-workspace hops
- symlink targets that canonically resolve outside `state/workspaces/`
- empty, whitespace-padded, NUL, and Unicode-control components
- credential-shaped path components
- payload metadata (`workspace_id` or `workspace`) that disagrees with the
  bound workspace

JSON payloads remain lossless for ordinary data. Credential-shaped keys
(`api_key`, `token`, `password`, …) and PEM/token-shaped values are stored as
`[redacted]`. Errors and debug logs do not include rejected components,
filesystem paths, or caught exception text. `list_experiments()` stays
fail-closed: rejected identities return `[]` instead of raising.

This is a path-jail and registry-identity guarantee, not a replacement for
request authentication or tenant authorization. The caller that selects a
registered workspace remains responsible for authorization. No second
workspace registry, event store, or persistence primitive is introduced.
`state_path` remains the shared state-root resolver; the artifact store uses
its own atomic JSON/text writes so failure logs never expose artifact paths.
