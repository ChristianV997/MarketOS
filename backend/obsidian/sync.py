from __future__ import annotations

from .client import ObsidianClient
from .templates import render_proposal_note


def sync_proposal_note(proposal, approval, decision, execution) -> dict:
    relative = f"MarketOS/02_Proposals/{proposal.proposal_id}.md"
    result = ObsidianClient().write_note(relative, render_proposal_note(proposal, approval, decision, execution))
    proposal.obsidian_note_path = relative if result.get("status") == "written" else ""
    return {"status": result.get("status", "skipped"), "path": relative, "detail": result}
