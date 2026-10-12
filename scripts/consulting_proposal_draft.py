#!/usr/bin/env python3
"""Print one offline consulting proposal draft from a JSON object on stdin.

Does not read credentials, call providers, or write a client file.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import backend.core.persistence as persistence
from backend.organization.commercial_report import CommercialReport
from backend.organization.report_registry import ReportRegistry
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from services.consulting_proposal_draft import ConsultingProposalDraftError, build_consulting_proposal_draft


def main() -> int:
    try:
        request = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        print(json.dumps({"status": "blocked", "blockers": ["invalid_request"]}))
        return 2
    if not isinstance(request, dict):
        print(json.dumps({"status": "blocked", "blockers": ["invalid_request"]}))
        return 2
    workspace_id = str(request.get("workspace_id", ""))
    with tempfile.TemporaryDirectory(prefix="consulting-proposal-draft-") as tmp:
        root = Path(tmp)
        persistence.STATE_DIR = str(root / "state")
        workspace_registry = WorkspaceRegistry(str(root / "workspaces.json"))
        workspace = workspace_registry.register(ClientWorkspace(
            workspace_id=workspace_id,
            name="proposal draft",
            workspace_type="client_service",
            mode="client_service",
            dry_run_default=True,
        ))
        report_registry = ReportRegistry(str(root / "reports.json"))
        for report_id in request.get("linked_component_report_ids") or []:
            if isinstance(report_id, str) and report_id:
                report_registry.register(CommercialReport(
                    report_id=report_id,
                    workspace_id=workspace.workspace_id,
                    proposal_id="proposal-draft",
                    experiment_id="experiment-draft",
                    service_name="product_research",
                    title="Linked report",
                    summary="Bounded linked report.",
                    status="completed",
                    created_at=0.0,
                ))
        try:
            draft = build_consulting_proposal_draft(
                request,
                workspace=workspace,
                artifact_store=ArtifactStore(workspace, workspace_registry),
                workspace_registry=workspace_registry,
                report_registry=report_registry,
            )
        except ConsultingProposalDraftError as exc:
            print(json.dumps({"status": "blocked", "blockers": [str(exc)]}, sort_keys=True))
            return 2
    print(json.dumps(draft, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
