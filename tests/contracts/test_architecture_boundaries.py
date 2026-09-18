"""Static, dependency-free architecture contract tests.

These tests deliberately inspect imports rather than importing application
modules: importing MarketOS modules can initialize state or optional providers.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
IGNORED_PARTS = {
    ".git", ".venv", ".venv312", "venv", "env", "node_modules", "__pycache__",
    "build", "dist", "artifacts", "state", "htmlcov", ".pytest_cache", ".mypy_cache", ".ruff_cache",
}
PRODUCTION_ROOTS = ("api", "backend", "core", "marketos", "orchestrator", "services")
ADVISORY_ROOTS = ("backend/commercial_intelligence", "backend/creative_intelligence", "backend/intelligence")
LIVE_MUTATION_PREFIXES = (
    "backend.launch", "backend.organic", "backend.commerce.checkout", "backend.commerce.fulfillment",
    "backend.commerce.orders", "backend.integrations.shopify", "backend.integrations.meta_ads",
    "backend.integrations.tiktok", "backend.integrations.stripe", "backend.integrations.mercado_pago",
    "backend.integrations.postiz", "backend.integrations.medusa",
)
# File-level compatibility list for the two legacy event paths. This is
# deliberately finite: adding a new caller must be an explicit architecture
# decision until EventRepository adapters replace the legacy stores.
APPROVED_LEGACY_EVENT_IMPORTERS = {
    "api/routes/orchestration.py", "api/routes/webhooks.py",
    "backend/commerce/checkout.py", "backend/commerce/fulfillment.py", "backend/commerce/inventory_sync.py", "backend/commerce/orders.py",
    "backend/contracts/event_log.py", "backend/contracts/registry.py", "backend/creation/store_builder.py", "backend/events/adapters/legacy.py",
    "backend/decision/capital_policy.py", "backend/decision/engine.py", "backend/decision/organic_gate.py",
    "backend/deployment/shadow_mode.py", "backend/economics/supplier_feedback.py", "backend/events/log.py", "backend/execution/loop.py",
    "backend/experiments/audit_log.py", "backend/launch/channel_selector.py", "backend/learning/calibration.py",
    "backend/ledger/__init__.py", "backend/ledger/events.py", "backend/ledger/projections.py", "backend/lineage/tracker.py",
    "backend/monitoring/alerts.py", "backend/observability/adapters/lineage_adapter.py", "backend/observability/entropy_metrics.py",
    "backend/observability/metrics.py", "backend/observability/tracing.py", "backend/optimization/budget_scaling.py",
    "backend/orchestration/__init__.py", "backend/orchestration/adapter.py", "backend/orchestration/transaction.py", "backend/orchestration/workflow.py",
    "backend/organic/engagement.py", "backend/organic/poster.py", "backend/runtime/replay_store.py", "backend/runtime/sleep/consolidation_engine.py",
    "backend/runtime/sleep/lineage_summarization.py", "backend/runtime/sleep/replay_scheduler.py", "backend/runtime/state.py",
    "backend/staging/historical_extraction.py", "backend/validation/shadow_flag_report.py", "backend/validation/suppliers.py",
    "backend/workspaces/live_mode_checklist.py", "core/creative/fatigue_detector.py", "core/creative/selection.py", "core/portfolio.py",
    "core/risk/global_risk_engine.py", "core/ugc/creator_tracker.py", "orchestrator/main.py",
}


def _python_files(*roots: str) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        directory = ROOT / root
        if not directory.exists():
            continue
        files.extend(
            path for path in directory.rglob("*.py")
            if not any(part in IGNORED_PARTS for part in path.relative_to(ROOT).parts)
        )
    return sorted(files)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _legacy_event_append_calls(path: Path) -> bool:
    """Detect direct appends to a current legacy event surface without imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    store_names: set[str] = set()
    append_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "backend.orchestration.event_store":
            store_names.update(alias.asname or alias.name for alias in node.names if alias.name == "event_store")
        if isinstance(node, ast.ImportFrom) and node.module == "backend.events.log":
            append_names.update(alias.asname or alias.name for alias in node.names if alias.name == "append")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in append_names:
            return True
        if isinstance(node.func, ast.Attribute) and node.func.attr == "append" and isinstance(node.func.value, ast.Name) and node.func.value.id in store_names:
            return True
    return False


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _assert_no_imports(paths: list[Path], forbidden: tuple[str, ...], boundary: str, move_to: str) -> None:
    violations = []
    for path in paths:
        for imported in _imports(path):
            if any(imported == item or imported.startswith(item + ".") for item in forbidden):
                violations.append(f"{_relative(path)} imports {imported}: violates {boundary}. Move logic to {move_to}.")
    assert not violations, "\n".join(violations)


def test_core_does_not_depend_on_interfaces() -> None:
    _assert_no_imports(_python_files("core"), ("api", "backend.api"), "core -> interface", "backend domain/application code")


def test_execution_and_backend_do_not_depend_on_frontend_or_api() -> None:
    _assert_no_imports(_python_files("backend/execution"), ("api", "backend.api", "frontend"), "execution -> interface", "an execution port or backend domain module")
    _assert_no_imports(_python_files("backend"), ("frontend",), "backend -> frontend", "an API DTO or frontend HTTP boundary")


def test_services_do_not_own_frontend_or_low_level_persistence() -> None:
    _assert_no_imports(
        _python_files("services"),
        ("frontend", "backend.runtime.replay_store", "backend.orchestration.event_store", "backend.data.repositories"),
        "service -> infrastructure", "a backend repository or integration abstraction",
    )


def test_interfaces_and_production_code_exclude_placeholder_architecture() -> None:
    _assert_no_imports(
        _python_files(*PRODUCTION_ROOTS), ("backend.dao_future",), "production -> speculative package", "docs/rfcs or a production-ready backend contract",
    )


def test_integrations_cannot_make_decisions() -> None:
    _assert_no_imports(
        _python_files("backend/integrations"), ("backend.decision", "backend.execution", "backend.optimization"),
        "integration -> decision authority", "a caller that passes an approved command to the integration",
    )


def test_advisory_intelligence_has_no_direct_live_mutation_dependency() -> None:
    _assert_no_imports(
        _python_files(*ADVISORY_ROOTS), LIVE_MUTATION_PREFIXES,
        "advisory intelligence -> live mutation", "an advisory artifact plus a separately approved integration command",
    )


def test_event_store_locations_and_legacy_appenders_are_controlled() -> None:
    event_store_files = [
        _relative(path) for path in ROOT.rglob("*.py")
        if not any(part in IGNORED_PARTS for part in path.relative_to(ROOT).parts)
        and path.stem in {"event_store", "eventstore"}
    ]
    assert event_store_files == ["backend/orchestration/event_store.py"], (
        f"event store modules must live in approved event locations; found {event_store_files}. "
        "Move new persistence behind backend/events/EventRepository."
    )

    violations = []
    for path in _python_files(*PRODUCTION_ROOTS):
        imports = _imports(path)
        uses_legacy_store = any(item.startswith("backend.orchestration.event_store") or item.startswith("backend.events.log") for item in imports)
        if uses_legacy_store and _relative(path) not in APPROVED_LEGACY_EVENT_IMPORTERS:
            violations.append(
                f"{_relative(path)} imports a current event store: violates approved legacy appender boundary. "
                "Move event append logic to backend/events through the future EventRepository adapter."
            )
    assert not violations, "\n".join(violations)

    append_violations = [
        f"{_relative(path)} appends to a current event store: violates approved legacy appender boundary. "
        "Move event append logic to backend/events through the future EventRepository adapter."
        for path in _python_files(*PRODUCTION_ROOTS)
        if _legacy_event_append_calls(path) and _relative(path) not in APPROVED_LEGACY_EVENT_IMPORTERS
    ]
    assert not append_violations, "\n".join(append_violations)


def test_contract_and_speculative_policy_are_present() -> None:
    contract = (ROOT / "ARCHITECTURE_CONTRACT.md").read_text(encoding="utf-8")
    for phrase in ("Canonical owners", "backend/execution/", "backend/events/", "backend/integrations/", "advisory"):
        assert phrase in contract, f"ARCHITECTURE_CONTRACT.md must name canonical owner: {phrase}"
    assert (ROOT / "docs/rfcs").is_dir(), "speculative proposals need docs/rfcs/ rather than production imports"
    assert "production-excluded" in contract, "contract must state the speculative-code production exclusion"


def test_creative_artifacts_cannot_authorize_promotion_or_spend() -> None:
    text = (ROOT / "docs/CREATIVE_INTELLIGENCE.md").read_text(encoding="utf-8").lower()
    contract = (ROOT / "ARCHITECTURE_CONTRACT.md").read_text(encoding="utf-8").lower()
    combined = text + "\n" + contract
    assert "never override opportunity gates" in combined
    assert "authorize publishing" in combined or "authorize launch" in combined
    assert "spend" in combined


def test_financial_kernel_is_canonical_money_authority() -> None:
    """Validate that financial calculations enforce backend.economics.kernel as single authority."""
    import backend.economics as package
    import backend.economics.kernel as kernel
    from evaluation.commerce.kernel_integration import CANONICAL_KERNEL_MODULE

    assert kernel.__name__ == CANONICAL_KERNEL_MODULE
    assert package.Money is kernel.Money
    assert package.calculate_unit_economics is kernel.calculate_unit_economics
    assert package.calculate_service_economics is kernel.calculate_service_economics


def test_trustos_is_canonical_export_boundary() -> None:
    """Validate that TrustOS client workspace isolation governs client-safe export boundaries."""
    from evaluation.trustos.client_workspace_isolation import check_workspace_leakage
    test_packet_with_leaks = {
        "client_name": "Acme",
        "internal_prompt": "secret internal instructions",
        "internal_scoring_formula": "x * 2.5",
        "public_summary": "safe description",
    }
    findings = check_workspace_leakage(test_packet_with_leaks, client_safe=True)
    assert len(findings) > 0
    leaked_classes = {f.data_class for f in findings}
    assert "internal_prompt" in leaked_classes or any("internal_prompt" in f.field_path for f in findings)
    assert "internal_scoring_formula" in leaked_classes or any("formula" in f.field_path for f in findings)


def test_companyos_approval_ledger_is_pre_integration_gate() -> None:
    """Validate that CompanyOS Approval Ledger enforces fail-closed pre-integration policy."""
    from evaluation.companyos.approval_ledger import simulate_action
    # Live mutation actions must never auto-allow without human approval or policy clearance
    sim_publish = simulate_action("site_publish")
    assert sim_publish.can_be_approved_now is False
    assert sim_publish.result in {"would_require_human_approval", "would_be_blocked_by_policy"}

    sim_ad = simulate_action("ad_launch")
    assert sim_ad.can_be_approved_now is False
    assert sim_ad.result in {"would_require_human_approval", "would_be_blocked_by_policy"}


def test_frontend_does_not_own_financial_scoring_or_backend_mutation() -> None:
    """Validate that frontend code does not calculate backend economics or call live provider mutation."""
    frontend_dir = ROOT / "frontend"
    if not frontend_dir.is_dir():
        pytest.skip("frontend directory not present")

    forbidden_patterns = [
        "calculate_unit_economics",
        "calculate_service_economics",
        "SHOPIFY_ADMIN_TOKEN",
        "STRIPE_SECRET_KEY",
    ]
    violations = []
    for path in frontend_dir.rglob("*.[jt]s*"):
        if any(part in IGNORED_PARTS for part in path.relative_to(ROOT).parts):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for pattern in forbidden_patterns:
            if pattern in content:
                violations.append(f"{_relative(path)} contains forbidden authority pattern '{pattern}'")

    assert not violations, "\n".join(violations)


def test_readiness_gates_compose_without_competing_authorities() -> None:
    """Validate that Phase 1, Deployment, and TrustOS readiness represent distinct non-overlapping concerns."""
    # 1. Deployment readiness: inspects environment flags and infrastructure
    from backend.deployment.readiness import build_readiness as build_deploy_readiness
    deploy_report = build_deploy_readiness(environ={}, platform="local")
    assert hasattr(deploy_report, "overall_status")
    assert deploy_report.report_version == "readonly-deployment-readiness-v1"

    # 2. TrustOS public launch readiness: evaluates governance and policy areas
    from evaluation.trustos.public_launch_readiness import build_public_launch_readiness
    trust_report = build_public_launch_readiness()
    assert hasattr(trust_report, "decision")
    assert hasattr(trust_report, "score")
    assert trust_report.decision.decision in ("blocked_for_public_beta", "go_for_internal_dry_run", "go_for_private_beta")
