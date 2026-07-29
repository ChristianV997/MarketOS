from pathlib import Path

from scripts.check_oss_policy import check_policy


def test_current_oss_inventory_passes_commercial_policy():
    assert check_policy() == []


def test_policy_rejects_restricted_license_in_commercial_core(tmp_path: Path):
    inventory = tmp_path / "inventory.yml"
    inventory.write_text("""commercial_distribution: true
candidates:
  - name: bad
    repository: https://github.com/example/bad
    license: GPL-3.0
    mode: commercial_core
    status: selected
    owner: test
    capabilities: [test]
""", encoding="utf-8")
    assert any("restricted license" in error for error in check_policy(inventory))
