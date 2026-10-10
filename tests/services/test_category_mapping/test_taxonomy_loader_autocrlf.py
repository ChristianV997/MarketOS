"""Windows checkout regression tests for the bundled taxonomy digest."""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from services.category_mapping import taxonomy_loader
from services.category_mapping.schemas import CategoryTaxonomyError, TAXONOMY_SOURCE_PROVENANCE


def test_core_autocrlf_checkout_requires_the_repository_eol_rule(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[3]
    snapshot_path = taxonomy_loader._DEFAULT_SNAPSHOT_PATH
    relative_path = snapshot_path.relative_to(repo_root).as_posix()
    git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}

    def run_git(repository: Path, *args: str) -> bytes:
        result = subprocess.run(
            ["git", "-C", str(repository), *args],
            env=git_env,
            capture_output=True,
            check=True,
            timeout=60,
        )
        return result.stdout

    head = run_git(repo_root, "rev-parse", "HEAD").decode("ascii").strip()
    git_blob = run_git(repo_root, "show", f"{head}:{relative_path}")
    expected_digest = TAXONOMY_SOURCE_PROVENANCE["snapshot_sha256"]
    assert hashlib.sha256(git_blob).hexdigest() == expected_digest

    attributes = (repo_root / ".gitattributes").read_text(encoding="utf-8")
    rule_prefix = f"{relative_path} "
    assert any(line.startswith(rule_prefix) and "eol=lf" in line for line in attributes.splitlines())
    attributes_without_rule = "\n".join(
        line for line in attributes.splitlines() if not line.startswith(rule_prefix)
    ) + "\n"

    for label, attribute_text in (
        ("with-eol-rule", attributes),
        ("without-eol-rule", attributes_without_rule),
    ):
        checkout_root = tmp_path / label
        checkout_root.mkdir()
        run_git(checkout_root, "init", "--quiet")
        run_git(checkout_root, "config", "core.autocrlf", "true")
        run_git(checkout_root, "config", "user.name", "taxonomy-checkout-test")
        run_git(checkout_root, "config", "user.email", "taxonomy-checkout@example.invalid")
        (checkout_root / ".gitattributes").write_text(attribute_text, encoding="utf-8", newline="\n")
        checkout_path = checkout_root / Path(relative_path)
        checkout_path.parent.mkdir(parents=True)
        checkout_path.write_bytes(git_blob)
        run_git(checkout_root, "add", "--", ".gitattributes", relative_path)
        tree = run_git(checkout_root, "write-tree").decode("ascii").strip()
        commit = run_git(checkout_root, "commit-tree", tree, "-m", label).decode("ascii").strip()
        run_git(checkout_root, "update-ref", "refs/heads/main", commit)
        run_git(checkout_root, "symbolic-ref", "HEAD", "refs/heads/main")
        assert run_git(checkout_root, "show", f"HEAD:{relative_path}") == git_blob
        checkout_path.unlink()
        run_git(checkout_root, "checkout", "--force", "HEAD", "--", relative_path)

        checkout_bytes = checkout_path.read_bytes()
        assert run_git(checkout_root, "config", "--get", "core.autocrlf").strip() == b"true"
        monkeypatch.setattr(taxonomy_loader, "_DEFAULT_SNAPSHOT_PATH", checkout_path)
        if label == "with-eol-rule":
            assert checkout_bytes == git_blob
            assert b"\r\n" not in checkout_bytes
            loaded = taxonomy_loader.load_taxonomy()
            assert loaded.source_provenance["snapshot_sha256"] == expected_digest
            assert loaded.source_provenance["evidence_mode"] == "bundled_offline_snapshot"
        else:
            assert checkout_bytes != git_blob
            assert b"\r\n" in checkout_bytes
            assert hashlib.sha256(checkout_bytes).hexdigest() != expected_digest
            with pytest.raises(CategoryTaxonomyError, match="snapshot checksum mismatch"):
                taxonomy_loader.load_taxonomy()
