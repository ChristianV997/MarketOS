"""Security regression tests for workspace-bound artifact persistence."""
from __future__ import annotations

import ast
import logging
import os
from pathlib import Path

import backend.core.persistence as pers
import backend.workspaces.registry as registry_module
import pytest
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry

_EXPECTED_PRODUCTION_CALLERS = frozenset(
    {
        "services/creative_growth/plan.py",
        "services/customer_intelligence/sprint.py",
        "services/digital_products/plan.py",
        "services/ecommerce_operator/contribution_profit.py",
        "services/product_research/audit.py",
        "services/profit_stack_advisor/advisor.py",
        "services/sales_automation/simulate.py",
        "services/unit_economics/analyzer.py",
    }
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(registry_module, "_registry", None)
    return tmp_path


@pytest.fixture
def workspaces(tmp_path):
    registry = WorkspaceRegistry(str(tmp_path / "workspaces.json"))
    alpha = registry.register(ClientWorkspace(name="workspace-alpha"))
    beta = registry.register(ClientWorkspace(name="workspace-beta"))
    return registry, alpha, beta


def test_registered_workspace_round_trip_and_list(workspaces):
    registry, alpha, _ = workspaces
    store = ArtifactStore(alpha, registry)
    assert store.save("exp-1", "result.json", {"score": 0.9}) is True
    assert store.load("exp-1", "result.json") == {"score": 0.9}
    assert store.list_experiments() == ["exp-1"]


def test_registered_workspace_text_round_trip(workspaces):
    registry, alpha, _ = workspaces
    store = ArtifactStore(alpha, registry)
    assert store.save_text("exp-1", "report.md", "# Hello\n") is True
    assert store.load_text("exp-1", "report.md") == "# Hello\n"


def test_path_is_canonical_and_workspace_local(tmp_path, workspaces):
    registry, alpha, _ = workspaces
    path = Path(ArtifactStore(alpha, registry).path_for("exp-1", "result.json"))
    assert path.is_relative_to((tmp_path / "workspaces").resolve())
    assert alpha.workspace_id in path.parts


@pytest.mark.parametrize("experiment_id", ["../escape", "a/../../b", ".."])
def test_rejects_relative_path_traversal(workspaces, experiment_id):
    registry, alpha, _ = workspaces
    with pytest.raises(ValueError, match="invalid experiment_id"):
        ArtifactStore(alpha, registry).save(experiment_id, "result.json", {})


@pytest.mark.parametrize("filename", ["/etc/passwd", "C:\\Windows\\Temp\\evil.json", "\\\\server\\share\\evil.json"])
def test_rejects_posix_and_windows_absolute_filenames(workspaces, filename):
    registry, alpha, _ = workspaces
    with pytest.raises(ValueError, match="invalid filename"):
        ArtifactStore(alpha, registry).save("exp-1", filename, {})


def test_rejects_sibling_workspace_escape(workspaces):
    registry, alpha, beta = workspaces
    left = ArtifactStore(alpha, registry)
    right = ArtifactStore(beta, registry)
    assert right.save("exp-1", "result.json", {"owner": "beta"})
    with pytest.raises(ValueError, match="invalid experiment_id"):
        left.save("../" + beta.workspace_id, "result.json", {"owner": "attacker"})
    assert right.load("exp-1", "result.json")["owner"] == "beta"


def test_rejects_unknown_and_forged_workspace_principals(workspaces):
    registry, alpha, _ = workspaces
    unknown = ClientWorkspace(name="unknown")
    forged = ClientWorkspace(workspace_id=alpha.workspace_id, name="forged-name")
    with pytest.raises(ValueError, match="not registered"):
        ArtifactStore(unknown, registry)
    with pytest.raises(ValueError, match="not registered"):
        ArtifactStore(forged, registry)


@pytest.mark.parametrize("raw_principal", ["workspace-alpha", {"workspace_id": "workspace-alpha"}, None])
def test_rejects_raw_workspace_principals(workspaces, raw_principal):
    registry, _, _ = workspaces
    with pytest.raises(ValueError, match="invalid workspace identity"):
        ArtifactStore(raw_principal, registry)


def test_production_artifact_callers_use_registered_workspace_contract():
    root = Path(__file__).resolve().parents[2]
    constructor_calls: dict[str, list[tuple[ast.Call, ast.AST, ast.AST]]] = {}

    def is_registry_access(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"get", "register"}
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "get_workspace_registry"
        )

    def is_approved_binding_call(node: ast.AST) -> bool:
        if is_registry_access(node):
            return True
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "run_unit_economics"
            and any(
                keyword.arg == "workspace"
                and isinstance(keyword.value, ast.Name)
                and keyword.value.id == "workspace"
                for keyword in node.keywords
            )
        )

    for production_root in (root / "api", root / "backend", root / "services"):
        for path in production_root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            parents = {
                child: parent
                for parent in ast.walk(tree)
                for child in ast.iter_child_nodes(parent)
            }
            for node in ast.walk(tree):
                is_constructor = (
                    isinstance(node, ast.Call)
                    and (
                        (isinstance(node.func, ast.Name) and node.func.id == "ArtifactStore")
                        or (isinstance(node.func, ast.Attribute) and node.func.attr == "ArtifactStore")
                    )
                )
                if not is_constructor:
                    continue
                scope = parents.get(node)
                while scope is not None and not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    scope = parents.get(scope)
                assert scope is not None, f"ArtifactStore construction outside a function: {path}"
                constructor_calls.setdefault(path.relative_to(root).as_posix(), []).append(
                    (node, scope, tree)
                )

    assert set(constructor_calls) == _EXPECTED_PRODUCTION_CALLERS
    for path, calls in constructor_calls.items():
        for node, scope, _ in calls:
            assert node.args and isinstance(node.args[0], ast.Name)
            assert node.args[0].id == "workspace", f"unbound ArtifactStore construction in {path}"
            assert any(
                is_approved_binding_call(candidate) and candidate.lineno < node.lineno
                for candidate in ast.walk(scope)
            ), f"ArtifactStore construction is not preceded by registry access in {path}"


def test_rejects_artifact_workspace_mismatch(workspaces):
    registry, alpha, beta = workspaces
    store = ArtifactStore(alpha, registry)
    with pytest.raises(ValueError, match="does not match"):
        store.save("exp-1", "result.json", {"workspace_id": beta.workspace_id})
    with pytest.raises(ValueError, match="does not match"):
        store.save("exp-1", "result.json", {"workspace": beta.workspace_id})


@pytest.mark.parametrize("value", ["", " name ", "bad\x00name", "bad\nname", "bad\u202ename"])
def test_rejects_empty_and_control_character_components(workspaces, value):
    registry, alpha, _ = workspaces
    with pytest.raises(ValueError, match="invalid filename"):
        ArtifactStore(alpha, registry).path_for("exp-1", value)


def test_invalid_workspace_identifier_never_reaches_filesystem(tmp_path):
    registry = WorkspaceRegistry(str(tmp_path / "workspaces.json"))
    unsafe = ClientWorkspace(workspace_id="../outside", name="unsafe")
    with pytest.raises(ValueError, match="invalid workspace_id"):
        ArtifactStore(unsafe, registry)
    assert not (tmp_path.parent / "outside").exists()


def test_symlink_escape_is_rejected(tmp_path, workspaces):
    registry, alpha, _ = workspaces
    store = ArtifactStore(alpha, registry)
    assert store.save("exp-1", "ok.json", {"ok": True})
    artifact_dir = tmp_path / "workspaces" / alpha.workspace_id / "experiments" / "exp-1"
    outside = tmp_path.parent / "artifact-store-outside.json"
    outside.write_text('{"outside": true}', encoding="utf-8")
    try:
        os.symlink(outside, artifact_dir / "outside.json")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc.winerror if isinstance(exc, OSError) else exc}")
    with pytest.raises(ValueError, match="outside the workspace boundary"):
        store.path_for("exp-1", "outside.json")


def test_errors_do_not_reflect_unsafe_input(workspaces):
    registry, alpha, _ = workspaces
    secret_like = "../" + "ghp_" + "abcdefghijklmnopqrstuvwxyz012345"
    with pytest.raises(ValueError) as error:
        ArtifactStore(alpha, registry).path_for(secret_like, "result.json")
    assert secret_like not in str(error.value)


def test_logs_do_not_reflect_filesystem_paths_or_errors(caplog, workspaces, monkeypatch):
    registry, alpha, _ = workspaces
    store = ArtifactStore(alpha, registry)
    monkeypatch.setattr(
        "backend.workspaces.artifact_store.os.replace",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("sensitive-path")),
    )
    with caplog.at_level(logging.DEBUG):
        assert store.save_text("exp-1", "report.md", "safe") is False
    assert "sensitive-path" not in caplog.text
    assert str(Path("state").resolve()) not in caplog.text


def test_json_logs_do_not_reflect_filesystem_paths_or_errors(caplog, workspaces, monkeypatch):
    registry, alpha, _ = workspaces
    store = ArtifactStore(alpha, registry)
    monkeypatch.setattr(
        "backend.workspaces.artifact_store.os.replace",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("sensitive-path")),
    )
    with caplog.at_level(logging.DEBUG):
        assert store.save("exp-1", "result.json", {"safe": True}) is False
    assert "sensitive-path" not in caplog.text
    assert str(Path("state").resolve()) not in caplog.text


def test_secret_shaped_values_are_redacted(workspaces):
    registry, alpha, _ = workspaces
    store = ArtifactStore(alpha, registry)
    redaction_fixture = "sk-test-" + "abcdefghijklmnopqrstuvwxyz"
    assert store.save(
        "exp-1", "creds.json", {"api_key": redaction_fixture, "note": (redaction_fixture,)}
    )
    loaded = store.load("exp-1", "creds.json")
    assert loaded == {"api_key": "[redacted]", "note": ["[redacted]"]}
    assert redaction_fixture not in Path(store.path_for("exp-1", "creds.json")).read_text(encoding="utf-8")


def test_malformed_json_returns_default(workspaces):
    registry, alpha, _ = workspaces
    store = ArtifactStore(alpha, registry)
    path = Path(store.path_for("exp-1", "broken.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    assert store.load("exp-1", "broken.json", default={"safe": True}) == {"safe": True}
