# Parallel Work Matrix

Updated: 2026-09-01

## Current Ownership Model
- **One agent owns one large vertical.** Agents must not overlap scopes.
- **Detached validation worktrees are evidence only, not ownership.** They do not represent active authority over a branch.
- **No new worktree may overwrite an active dirty owner.**
- **No duplicate PRs.** Only one active PR per integration/capability.
- **No parallel edits to shared files.**
- **Merger Agent is the ONLY rebase/merge/close authority.** Feature agents must not self-merge, rebase others, or close other PRs.

## Current WIP Limits & Sequencing
1. **Artifact Security:** Resolving #211 identity-binding containment.
2. **Baseline/Quality Recovery:** Resolving test-health (Ollama/router timeouts, SBOM) and #221 quality-gate evidence.
3. **Learning Ledger Recovery:** Re-establishing deterministic training signals.
4. **Frontend/API Consolidation:** Resolving #213 and the stacked Cursor environment (#214).
5. **SerpApi Consolidation:** #220 organic request, followed safely by downstream #222 commerce projection without double-counting.
6. **Future External Capability Adoption:** Strictly queued after the above integrations merge cleanly.

## Historical Directions
*(Note: Earlier matrix versions assigning Codex ownership over commerce/orchestrator or referencing Phase 1 live validation are now strictly historical and deprecated.)*
