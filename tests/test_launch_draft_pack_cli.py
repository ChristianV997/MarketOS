from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.generate_launch_draft_pack import main


def test_cli_json_is_safe(capsys):
    main(["--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["launch_draft_status"] == "draft_only_pending_human_approval"
    assert report["read_only"] is True
    assert report["published"] is False


def test_cli_markdown_has_client_sections(capsys):
    main(["--markdown"])
    output = capsys.readouterr().out
    assert "# Launch Draft Pack" in output
    assert "## Offer Stack" in output
    assert "## Approval Blockers" in output


def test_cli_writes_only_sanitized_pack_files(tmp_path, capsys):
    main(["--output", str(tmp_path), "--json"])
    capsys.readouterr()
    expected = {"launch_draft_pack.json", "launch_draft_pack.md", "shopify_draft_payload.json", "medusa_draft_payload.json", "creative_test_matrix.json", "ugc_briefs.md", "approval_checklist.md", "operator_risk_review.json"}
    assert {path.name for path in tmp_path.iterdir()} == expected
    raw = (tmp_path / "launch_draft_pack.json").read_text(encoding="utf8")
    assert "CJ_API_KEY" not in raw
    assert "Authorization:" not in raw


def test_cli_rejects_windows_traversal(capsys):
    with pytest.raises(SystemExit):
        main(["--client-context", r"..\secret.json", "--json"])
    assert "traversal" in capsys.readouterr().err


def test_cli_rejects_secret_like_input(tmp_path, capsys):
    path = tmp_path / "context.json"
    path.write_text(json.dumps({"CJ_API_KEY": "not-a-real-key"}), encoding="utf8")
    with pytest.raises(SystemExit):
        main(["--client-context", str(path), "--json"])
    assert "secret" in capsys.readouterr().err


def test_cli_rejects_non_json_input(tmp_path, capsys):
    path = tmp_path / "context.txt"
    path.write_text("draft", encoding="utf8")
    with pytest.raises(SystemExit):
        main(["--client-context", str(path), "--json"])
    assert "non-JSON" in capsys.readouterr().err


def test_cli_json_and_markdown_are_exclusive():
    with pytest.raises(SystemExit):
        main(["--json", "--markdown"])


def test_cli_missing_file_is_actionable(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main(["--opportunity-synthesis-report", str(tmp_path / "missing.json"), "--json"])
    assert "does not exist" in capsys.readouterr().err


def test_cli_output_is_deterministic(tmp_path, capsys):
    first_dir, second_dir = tmp_path / "one", tmp_path / "two"
    main(["--output", str(first_dir), "--json"])
    capsys.readouterr()
    main(["--output", str(second_dir), "--json"])
    capsys.readouterr()
    assert (first_dir / "launch_draft_pack.json").read_text(encoding="utf8") == (second_dir / "launch_draft_pack.json").read_text(encoding="utf8")


def test_cli_does_not_write_without_output(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    main(["--json"])
    capsys.readouterr()
    assert list(tmp_path.iterdir()) == []
