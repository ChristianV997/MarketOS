from scripts.ai import session_start


def test_owner_for_normalizes_windows_paths():
    assert session_start.owner_for(r"scripts\ai\session_start.py") == "codex"
    assert session_start.owner_for("services/sales_automation/real_handoff.py") == "claude"
    assert session_start.owner_for("backend/commerce/loop.py") is None


def test_shared_handoff_is_not_assigned_to_one_agent():
    assert session_start.owner_for("docs/ai/SESSION_HANDOFF.md") == "shared"
