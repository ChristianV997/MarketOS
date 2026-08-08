from backend.obsidian.client import ObsidianClient
from backend.obsidian.sync import sync_proposal_note
from backend.governance.proposal import Proposal


def test_obsidian_skips_when_unconfigured(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    assert ObsidianClient().write_note("x.md", "x")["status"] == "skipped"


def test_obsidian_blocks_traversal(tmp_path):
    client = ObsidianClient(tmp_path)
    assert client.write_note("../escape.md", "x")["status"] == "blocked"
    assert client.write_note("nested/note.md", "x")["status"] == "written"
    assert client.read_note("nested/note.md")["content"] == "x"


def test_proposal_note_sync(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    proposal = Proposal(proposal_id="proposal-test", title="Research", workspace_id="w", department_id="product")
    result = sync_proposal_note(proposal, {"allowed": True}, {"decision": "approved"}, {"status": "completed"})
    assert result["status"] == "written"
    assert (tmp_path / "MarketOS/02_Proposals/proposal-test.md").exists()
