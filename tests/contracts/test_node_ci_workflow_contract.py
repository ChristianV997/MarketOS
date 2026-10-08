"""Static contract tests: Node.js CI workflow configuration and boundary integrity.

Enforces:
1. Node.js CI targets the frontend package workspace with working-directory: frontend.
2. actions/setup-node@v4 explicitly configures cache-dependency-path to frontend/package-lock.json.
3. The referenced frontend/package-lock.json exists, while no root lockfile is present.
4. The workflow runs npm ci, build, and test without skipping or weakening checks.
5. The matrix uses supported Node.js LTS lines and preserves evidence from both legs.
6. The core CI workflow (.github/workflows/ci.yml) remains isolated and untouched.
"""
from __future__ import annotations

from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
NODE_WORKFLOW = ROOT / ".github" / "workflows" / "node.js.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
FRONTEND_DIR = ROOT / "frontend"


def _load_node_workflow() -> dict:
    assert NODE_WORKFLOW.exists(), f"Workflow file not found: {NODE_WORKFLOW}"
    content = NODE_WORKFLOW.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    assert isinstance(data, dict), f"Failed to parse {NODE_WORKFLOW} as a mapping"
    return data


def test_node_ci_workflow_structure_and_triggers():
    data = _load_node_workflow()
    assert data.get("name") == "Node.js CI"

    # PyYAML parses unquoted 'on:' as boolean True
    on_trigger = data.get("on") or data.get(True)
    assert isinstance(on_trigger, dict), "Workflow 'on' trigger must be a dictionary"
    assert "push" in on_trigger
    assert "pull_request" in on_trigger
    assert "main" in on_trigger["push"]["branches"]
    assert "main" in on_trigger["pull_request"]["branches"]


def test_node_ci_targets_frontend_toolchain_and_lockfile_cache():
    data = _load_node_workflow()
    jobs = data.get("jobs", {})
    assert "build" in jobs, "Workflow must define a 'build' job"
    build_job = jobs["build"]

    # Working directory contract
    defaults = build_job.get("defaults", {})
    run_defaults = defaults.get("run", {})
    assert run_defaults.get("working-directory") == "frontend", (
        "Job defaults.run.working-directory must be set to 'frontend'"
    )

    # Matrix contract
    strategy = build_job.get("strategy", {})
    matrix = strategy.get("matrix", {})
    node_versions = matrix.get("node-version", [])
    assert node_versions == ["22.x", "24.x"]
    assert "18.x" not in node_versions
    assert "20.x" not in node_versions
    assert strategy.get("fail-fast") is False

    # Step-level cache and lockfile contract
    steps = build_job.get("steps", [])
    setup_node = next(
        (step for step in steps if step.get("uses", "").startswith("actions/setup-node")),
        None,
    )
    assert setup_node is not None, "Missing actions/setup-node step in build job"
    with_block = setup_node.get("with", {})
    assert with_block.get("cache") == "npm", "setup-node must specify cache: 'npm'"
    assert with_block.get("cache-dependency-path") == "frontend/package-lock.json", (
        "setup-node must specify cache-dependency-path: 'frontend/package-lock.json'"
    )

    # File system truth: frontend/package-lock.json must exist; no root lockfile allowed
    frontend_lockfile = FRONTEND_DIR / "package-lock.json"
    assert frontend_lockfile.is_file(), f"Expected lockfile not found: {frontend_lockfile}"
    assert frontend_lockfile.stat().st_size > 0, "frontend/package-lock.json must not be empty"

    root_lockfile = ROOT / "package-lock.json"
    assert not root_lockfile.exists(), (
        "A root package-lock.json must not be created; the lockfile belongs in frontend/"
    )


def test_node_ci_steps_execute_install_build_and_test():
    data = _load_node_workflow()
    steps = data["jobs"]["build"]["steps"]

    run_commands = [step["run"] for step in steps if "run" in step]
    assert len(run_commands) >= 3, f"Expected at least 3 run steps, found: {run_commands}"
    assert run_commands[0] == "npm ci"
    assert run_commands[1] == "npm run build"
    assert "--if-present" not in run_commands[1], (
        "The frontend build must be required; optional execution can report a green matrix leg without building"
    )
    assert run_commands[2] == "npm test"

    # Ensure no weakening flags (e.g. '|| true', 'continue-on-error')
    for step in steps:
        assert step.get("continue-on-error") is not True, f"Weakened step found: {step}"
        if "run" in step:
            assert "|| true" not in step["run"], f"Weakened command found: {step['run']}"


def test_node_ci_isolation_from_ci_yml():
    # Ensure .github/workflows/ci.yml exists and remains distinct
    assert CI_WORKFLOW.exists(), f"Core CI workflow not found at {CI_WORKFLOW}"
    ci_content = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "actions/setup-node" not in ci_content, (
        ".github/workflows/ci.yml must not be modified or tangled with node.js.yml"
    )


def test_node_ci_workflow_permissions_contract():
    """Verify that the Node.js CI workflow enforces least-privilege permissions.

    Enforces:
    1. Top-level 'permissions:' block exists in node.js.yml.
    2. 'contents: read' is explicitly configured.
    3. No write permissions exist (no 'write', no 'all', and all permission values are strictly 'read').
    """
    data = _load_node_workflow()

    # 1. Verify top-level permissions block exists
    assert "permissions" in data, (
        "Workflow must define a top-level 'permissions' block for least-privilege security"
    )
    permissions = data["permissions"]
    assert isinstance(permissions, dict), (
        "Top-level 'permissions' must be a mapping specifying explicit permission scopes"
    )

    # 2. Verify contents: read is set
    assert permissions.get("contents") == "read", (
        "Workflow top-level permissions must explicitly set 'contents: read'"
    )

    # 3. Verify no write permissions exist and all granted scopes are strictly 'read'
    for scope, access in permissions.items():
        assert access != "write", (
            f"Permission scope '{scope}' must not have write access"
        )
        assert access != "all", (
            f"Permission scope '{scope}' must not have 'all' access"
        )
        assert access == "read", (
            f"Permission scope '{scope}' has unexpected access level '{access}'; "
            "all granted permissions must be strictly 'read'"
        )
