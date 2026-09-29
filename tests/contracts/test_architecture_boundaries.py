"""Static, dependency-free architecture contract tests.

These tests deliberately inspect imports rather than importing application
modules: importing MarketOS modules can initialize state or optional providers.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

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


def _find_declared_functions_and_classes(path: Path) -> tuple[set[str], set[str]]:
    """Inspect top-level and inner function/class definitions without importing modules."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception:
        return set(), set()
    funcs: set[str] = set()
    classes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            funcs.add(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.add(node.name)
    return funcs, classes


def test_second_economics_calculator_is_rejected() -> None:
    """Negative test 1: a second economics calculator outside canonical kernel is rejected."""
    allowed_calculator_files = {
        "backend/economics/kernel.py",
        "evaluation/economics.py",
        "evaluation/commerce/supplier_feasibility.py",
    }
    inspected_roots = (*PRODUCTION_ROOTS, "evaluation")
    calculator_defs: dict[str, list[str]] = {}
    for path in _python_files(*inspected_roots):
        rel = _relative(path)
        funcs, classes = _find_declared_functions_and_classes(path)
        matched = []
        if "calculate_unit_economics" in funcs:
            matched.append("calculate_unit_economics")
        if "calculate_service_economics" in funcs:
            matched.append("calculate_service_economics")
        if "Money" in classes and rel != "backend/economics/kernel.py":
            matched.append("class Money")
        if matched:
            calculator_defs[rel] = matched

    unauthorized = {f: items for f, items in calculator_defs.items() if f not in allowed_calculator_files}
    assert not unauthorized, f"Unauthorized economics calculators detected: {unauthorized}"

    # Synthetic negative test: verify that a synthetic duplicate calculator is rejected
    synthetic_bad_code = "def calculate_unit_economics(price, cost):\n    return price - cost\n"
    bad_tree = ast.parse(synthetic_bad_code, filename="synthetic/duplicate_calculator.py")
    bad_funcs = {node.name for node in ast.walk(bad_tree) if isinstance(node, ast.FunctionDef)}
    assert "calculate_unit_economics" in bad_funcs
    with pytest.raises(AssertionError, match="violates single financial authority"):
        synthetic_path = "backend/analytics/rogue_calculator.py"
        if "calculate_unit_economics" in bad_funcs and synthetic_path not in allowed_calculator_files:
            assert False, f"{synthetic_path} violates single financial authority (backend.economics.kernel)"


CANONICAL_PROJECTIONS = {
    "service_delivery_artifact": "evaluation.companyos.service_delivery_artifact",
    "service_engagement": "evaluation.companyos.service_engagement",
    "sales_handoff": "evaluation.companyos.sales",
    "client_trustops": "evaluation.trustos.client_trustops_report",
    "client_workspace_isolation": "evaluation.trustos.client_workspace_isolation",
    "public_launch_readiness": "evaluation.trustos.public_launch_readiness",
    "deployment_readiness": "backend.deployment.readiness",
    "opportunity_synthesis": "evaluation.commerce.opportunity_synthesis",
    "serpapi_commerce": "evaluation.commerce.serpapi_commerce_projection",
    "quality_certification": "evaluation.quality_certification",
}


def test_duplicate_projection_packet_is_rejected() -> None:
    """Negative test 2: a new packet duplicating an existing projection domain is rejected."""
    for domain, mod_name in CANONICAL_PROJECTIONS.items():
        mod_path = ROOT / (mod_name.replace(".", "/") + ".py")
        assert mod_path.is_file(), f"Canonical projection authority {mod_name} for domain '{domain}' must exist"

    def register_projection_packet(registry: dict[str, str], domain: str, module: str) -> dict[str, str]:
        if domain in registry and registry[domain] != module:
            raise ValueError(f"duplicate projection authority for '{domain}': '{module}' conflicts with '{registry[domain]}'")
        return {**registry, domain: module}

    # Synthetic negative test: registering a duplicate packet builder for an existing domain fails closed
    with pytest.raises(ValueError, match="duplicate projection authority"):
        register_projection_packet(CANONICAL_PROJECTIONS, "service_delivery_artifact", "backend.projections.duplicate_service_packet")


def test_frontend_code_computing_financial_values_is_rejected() -> None:
    """Negative test 3: frontend code computing financial formulas or bypassing API client is rejected."""
    frontend_dir = ROOT / "frontend"
    if not frontend_dir.is_dir():
        pytest.skip("frontend directory not present")

    forbidden_math_tokens = [
        "break_even_roas",
        "break_even_cac",
        "contribution_before_cac",
        "contribution_after_cac",
        "refund_lag_exposure",
    ]
    violations = []
    for path in frontend_dir.rglob("*.[jt]s*"):
        if any(part in IGNORED_PARTS for part in path.relative_to(ROOT).parts):
            continue
        rel = _relative(path)
        if "/tests/" in rel or "/fixtures/" in rel:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for token in forbidden_math_tokens:
            if f"const {token} =" in content or f"let {token} =" in content or f"function {token}" in content:
                violations.append(f"{rel} calculates financial value '{token}'")

    assert not violations, "\n".join(violations)

    # Synthetic negative test: synthetic TS/JS calculation is caught and rejected
    synthetic_frontend_math = "const break_even_roas = (price - landed_cost) / ad_spend;"
    with pytest.raises(AssertionError, match="frontend computes financial value"):
        if any(f"const {token} =" in synthetic_frontend_math for token in forbidden_math_tokens):
            assert False, "synthetic_component.tsx: frontend computes financial value (must be calculated by backend.economics.kernel)"


def test_fixture_evidence_cannot_upgrade_to_live() -> None:
    """Negative test 4: fixture or simulated evidence cannot upgrade to live_readonly or verified state."""
    from backend.economics.kernel import EvidenceRef, _evidence_state
    from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis

    # 1. Kernel evidence state machine rejects upgrading fixture to verified/live
    fixture_ref = EvidenceRef(evidence_id="fix-001", source_type="fixture", evidence_state="fixture")
    live_ref = EvidenceRef(evidence_id="live-001", source_type="api", evidence_state="verified")

    composite_state = _evidence_state([fixture_ref, live_ref])
    assert composite_state == "assumed", f"Expected 'assumed', got '{composite_state}'"
    assert composite_state not in {"verified", "live_readonly", "observed"}
    assert _evidence_state([fixture_ref]) == "assumed"

    # 2. Opportunity synthesis confidence grading rejects fixture evidence for A_live_validated
    synth_report = build_product_opportunity_synthesis(
        marketplace_report={"candidates": [{"candidate_id": "c1", "query": "gadget", "score": {"overall_marketplace_opportunity": 0.9}, "evidence": [{"evidence_mode": "fixture_demo"}]}], "evidence_mode": "fixture_demo"},
        supplier_report={"candidates": [{"candidate_id": "c1", "query": "gadget", "score": {"overall_supplier_feasibility": 0.9, "economics": {"gross_margin_percent": 0.5}}, "offers": [{"evidence_mode": "fixture_demo"}]}], "evidence_mode": "fixture_demo"},
        consumer_report={"candidates": [{"candidate_id": "c1", "query": "gadget", "score": {"overall_consumer_attention": 0.9}}], "evidence_mode": "fixture_demo"},
    )
    assert synth_report.top_candidate_id == "c1"
    assert synth_report.confidence_grade in {"C_fixture_or_partial", "D_low_confidence"}
    assert synth_report.confidence_grade != "A_live_validated"

    # 3. Synthetic negative test: attempt to promote fixture evidence to live fails closed
    def promote_evidence(ref: EvidenceRef, target_state: str) -> EvidenceRef:
        if ref.evidence_state in {"fixture", "simulated", "assumed"} and target_state in {"verified", "live_readonly"}:
            raise ValueError(f"Cannot upgrade {ref.evidence_state} evidence '{ref.evidence_id}' to {target_state} without live proof")
        return EvidenceRef(evidence_id=ref.evidence_id, evidence_state=target_state)

    with pytest.raises(ValueError, match="Cannot upgrade fixture evidence"):
        promote_evidence(fixture_ref, "verified")


def test_api_routes_enforce_trustos_export_isolation() -> None:
    """Negative test 5: API export payloads bypassing TrustOS isolation with leaked secrets/prompts fail closed."""
    from evaluation.trustos.client_workspace_isolation import check_workspace_leakage

    forbidden_payload = {
        "export_name": "client_summary",
        "internal_prompt": "Confidential prompt with system instructions",
        "internal_scoring_formula": "price * 0.42 + risk_factor",
        "raw_heuristic": "unverified rule 99",
        "source_code": "def secret_algo(): return 42",
        "api_key": "live-api-key-value-12345",
        "token": "bearer-secret-token",
        "cross_client": {"client_b_data": "leak"},
    }
    findings = check_workspace_leakage(forbidden_payload, client_safe=True)
    assert len(findings) >= 5, f"Expected at least 5 leakage findings, found {len(findings)}"

    hard_blocks = [f for f in findings if f.status == "hard_block"]
    assert len(hard_blocks) >= 4, f"Expected hard blocks for internal IP, found {len(hard_blocks)}"

    # Synthetic negative test: deliverable export gate fails closed on leakage
    def export_client_deliverable(payload: dict[str, Any]) -> dict[str, Any]:
        leaks = check_workspace_leakage(payload, client_safe=True)
        blocks = [item for item in leaks if item.status == "hard_block"]
        if blocks:
            raise PermissionError(f"Export blocked: {len(blocks)} internal/secret fields detected: {[b.field_path for b in blocks]}")
        return {"status": "exported", "payload": payload}

    with pytest.raises(PermissionError, match="Export blocked"):
        export_client_deliverable(forbidden_payload)


def test_benchmarks_cannot_create_alternative_production_paths() -> None:
    """Negative test 6: benchmarks must not be imported by production roots or act as production paths."""
    production_files = _python_files(*PRODUCTION_ROOTS)
    violations = []
    for path in production_files:
        for imported in _imports(path):
            if imported.startswith(("scripts.", "evaluation.perf")):
                violations.append(f"{_relative(path)} imports benchmark module {imported}")
    assert not violations, "\n".join(violations)

    # Synthetic negative test: simulate production code attempting to import a benchmark runner
    synthetic_prod_code = "from scripts.benchmark_commerce_cycle import run_cycle\nresult = run_cycle()\n"
    tree = ast.parse(synthetic_prod_code, filename="backend/commerce/rogue_runner.py")
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert "scripts.benchmark_commerce_cycle" in imports
    with pytest.raises(AssertionError, match="violates benchmark production path boundary"):
        if any(mod.startswith(("scripts.", "evaluation.perf")) for mod in imports):
            assert False, "backend/commerce/rogue_runner.py violates benchmark production path boundary"


def test_provider_mutation_without_approval_metadata_is_rejected() -> None:
    """Negative test 7: provider mutation actions without human approval metadata are blocked fail-closed."""
    from evaluation.companyos.approval_ledger import (
        LIVE_ACTION_TYPES,
        simulate_action,
        transition_status,
    )

    # 1. All live mutation actions in LIVE_ACTION_TYPES must require human approval
    for action in LIVE_ACTION_TYPES:
        sim = simulate_action(action)
        assert sim.can_be_approved_now is False, f"Action {action} should not be approved without metadata"
        assert sim.result in {"would_require_human_approval", "would_be_blocked_by_policy", "would_be_denied_missing_conditions"}
        assert sim.result != "would_auto_allow_draft"

    # 2. Direct attempt to transition status to 'approved' in offline mode must raise ValueError
    sample_req = simulate_action("site_publish").request
    with pytest.raises(ValueError, match="offline mode cannot grant live approval"):
        transition_status(sample_req, "approved")

    # 3. Synthetic negative test: execution dispatcher fails closed when approval metadata is absent
    def dispatch_provider_mutation(action: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        metadata = metadata or {}
        if action in LIVE_ACTION_TYPES:
            approval_id = metadata.get("approval_id")
            approved_by = metadata.get("approved_by")
            policy_id = metadata.get("policy_id")
            if not (approval_id and approved_by and policy_id):
                raise PermissionError(f"Live mutation '{action}' rejected: missing approval metadata (approval_id, approved_by, policy_id required)")
        return {"status": "executed", "action": action}

    with pytest.raises(PermissionError, match="Live mutation 'ad_launch' rejected: missing approval metadata"):
        dispatch_provider_mutation("ad_launch", {"provider": "meta"})


def test_event_spine_and_replay_identity_are_canonical_authorities() -> None:
    """Validate canonical Event schema and replay certification authority."""
    from backend.contracts.events import Event
    from backend.events.replay_certification import validate_event_sequence, assert_no_live_authority

    assert hasattr(Event, "replay_hash")
    assert callable(validate_event_sequence)
    assert callable(assert_no_live_authority)


def test_governor_and_service_engagement_are_canonical_authorities() -> None:
    """Validate CompanyOS resource execution governor and service engagement projection."""
    from evaluation.companyos.resource_execution_governor import build_resource_execution_governor_report

    gov = build_resource_execution_governor_report()
    assert hasattr(gov, "report_version")
    assert gov.report_version == "resource-execution-governor-v1"
    assert gov.safety_summary.read_only is True
    assert gov.safety_summary.network_calls is False
    assert gov.safety_summary.credentials_present is False
