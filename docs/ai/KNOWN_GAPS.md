# Known Gaps

Updated: 2026-10-11

- External live integrations require credentialed validation; dry-run success is not live validation.
- Optional developer tools are not assumed installed in every environment.
- OSS artifacts need license, security, maintenance, and adapter-fit review before adoption.
- Calibration, ranking, and feedback changes require targeted tests plus an architecture-impact review.
- Source calibration (`docs/SOURCE_CALIBRATION.md`): registry writes are serialized within one process, so keep one writer per state file; `apply_calibration_to_source_quality` is implemented but not on any production path; the architecture-impact review for the 2026-10-11 persistence and ordering changes is still pending.
- CodeQL now runs as a scoped CI analysis for commerce, integrations, orchestration, and connector changes; it remains CI-only rather than a local development-loop tool.

When resolving a gap, update this file and the session handoff rather than creating parallel tracking documents.
