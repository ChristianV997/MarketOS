"""services.reporting.render — minimal markdown report rendering + artifact
saving. No HTML/PDF/evidence-bundle yet (deferred to a later phase).
"""
from __future__ import annotations

import time
from typing import Any

from backend.workspaces.artifact_store import ArtifactStore

_DRY_RUN_DISCLAIMER = (
    "> **DRY RUN** — no live spend, no live credentials used. "
    "Figures are estimates, not live performance evidence.\n"
)


def _render_body(value: Any, *, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(value, dict):
        lines = []
        for key in sorted(value.keys()):
            v = value[key]
            if isinstance(v, (dict, list)):
                lines.append(f"{pad}- **{key}**:")
                lines.append(_render_body(v, indent=indent + 1))
            else:
                lines.append(f"{pad}- **{key}**: {v}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return f"{pad}- (none)"
        lines = []
        for i, item in enumerate(value):
            lines.append(f"{pad}- [{i}]")
            lines.append(_render_body(item, indent=indent + 1))
        return "\n".join(lines)
    return f"{pad}{value}"


def render_markdown_report(
    title: str,
    sections: list[dict[str, Any]],
    *,
    dry_run: bool = True,
    generated_at: float | None = None,
) -> str:
    """sections: [{'heading': str, 'body': str | dict | list}].

    Deterministic output (dict keys sorted) so tests can assert on exact
    substrings. A dry-run disclaimer is mandatory whenever dry_run is True —
    reports must never claim live performance from simulated/dry-run data.
    """
    ts = generated_at if generated_at is not None else time.time()
    lines = [f"# {title}", ""]
    if dry_run:
        lines.append(_DRY_RUN_DISCLAIMER)
    lines.append(f"_Generated at {ts}_")
    lines.append("")
    for section in sections:
        heading = section.get("heading", "")
        body = section.get("body", "")
        lines.append(f"## {heading}")
        lines.append("")
        if isinstance(body, str):
            lines.append(body)
        else:
            lines.append(_render_body(body))
        lines.append("")
    return "\n".join(lines)


def save_report_artifacts(
    store: ArtifactStore,
    workspace_id: str,
    experiment_id: str,
    markdown: str,
    data: dict[str, Any],
) -> dict[str, bool]:
    """Save the rendered markdown + underlying data dict. Never raises —
    save/save_text are already fail-silent (return False on error)."""
    return {
        "report_md": store.save_text(workspace_id, experiment_id, "report.md", markdown),
        "result_json": store.save(workspace_id, experiment_id, "result.json", data),
    }


def export_client_report(
    store: ArtifactStore, workspace_id: str, experiment_id: str, filename: str = "report.md",
) -> str | None:
    """Return the on-disk path to a saved report — the single file a client
    deliverable actually is (hand it over, email it, attach it). Never
    raises; returns None if the report was never saved (e.g. the
    experiment failed before a report.md was written)."""
    path = store.path_for(workspace_id, experiment_id, filename)
    import os
    return path if path and os.path.exists(path) else None
