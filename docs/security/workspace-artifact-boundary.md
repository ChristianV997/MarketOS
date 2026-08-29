# Workspace artifact path boundary

Canonical owner: `backend/workspaces/artifact_store.py`.

Artifact paths are always:

```text
state/workspaces/{workspace_id}/experiments/{experiment_id}/{filename}
```

`workspace_id` and `experiment_id` are single path segments. `filename` may be
empty (directory probe) or a relative name. The store rejects:

- parent-directory segments (`..`)
- absolute paths (`/etc/passwd`, `C:\...`)
- sibling-workspace hops
- symlink targets that resolve outside `state/workspaces/`
- empty or whitespace-padded identities
- credential-shaped path components

JSON payloads remain lossless for ordinary data. Credential-shaped keys
(`api_key`, `token`, `password`, …) and PEM/token-shaped values are stored as
`[redacted]`. `list_experiments()` stays fail-closed: rejected identities
return `[]` instead of raising.

No second workspace registry, event store, or persistence primitive is
introduced. `state_path` / `save_json_atomic` / `load_json` remain the only
I/O helpers.
