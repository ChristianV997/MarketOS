from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.companyos.agent_registry import RUN_MODES, build_agent_registry
from evaluation.companyos.architecture_registry import INTEGRATION_MODES, build_architecture_registry, default_references
from evaluation.companyos.companyos_registry_report import build_companyos_registry_report
from evaluation.companyos.eval_registry import METRICS, QUALITY_GATES, build_eval_registry
from evaluation.companyos.knowledge_registry import SOURCE_TYPES, build_knowledge_registry
from evaluation.companyos.model_router import MODEL_TIERS, build_model_router
from evaluation.companyos.skill_registry import VERIFICATION_STATUSES, build_skill_registry
from evaluation.companyos.tool_registry import AUTH_MODES, LIVE_CATEGORIES, RISK_LEVELS, build_tool_registry
from evaluation.companyos.workflow_registry import build_workflow_registry

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "companyos_registry"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture()
def architecture():
    return build_architecture_registry()


@pytest.fixture()
def agents():
    return build_agent_registry()


@pytest.fixture()
def skills():
    return build_skill_registry()


@pytest.fixture()
def tools():
    return build_tool_registry()


@pytest.fixture()
def workflows():
    return build_workflow_registry()


@pytest.fixture()
def model_router():
    return build_model_router()


@pytest.fixture()
def evals():
    return build_eval_registry()


@pytest.fixture()
def knowledge():
    return build_knowledge_registry()


def test_architecture_has_all_reference_systems(architecture):
    names = {item.name for item in architecture.references}
    assert {"Onyx", "Dify", "LangGraph", "LiteLLM", "Langfuse", "Supabase pgvector", "AWS Bedrock / AgentCore"}.issubset(names)
    assert len(architecture.references) >= 28


@pytest.mark.parametrize("reference", default_references())
def test_architecture_reference_is_complete(reference):
    assert reference.system_id and reference.name and reference.category
    assert reference.integration_mode in INTEGRATION_MODES
    assert reference.license_risk and reference.security_risk and reference.cost_risk
    assert reference.recommended_marketos_mapping
    assert reference.next_review_trigger


@pytest.mark.parametrize("system_id", ["litellm", "langfuse", "langgraph", "onyx", "composio", "n8n", "windmill"])
def test_architecture_mapping_is_explicit(architecture, system_id):
    item = next(item for item in architecture.references if item.system_id == system_id)
    assert item.recommended_marketos_mapping
    assert item.emulate_now_reason
    assert item.avoid_now_reason


def test_litellm_is_high_priority_future_integration(architecture):
    decision = next(item for item in architecture.decisions if item.system_id == "litellm")
    assert decision.decision == "integrate_soon"
    assert decision.priority == "high"


def test_onyx_is_emulated_before_integration(architecture):
    assert next(item for item in architecture.decisions if item.system_id == "onyx").decision == "emulate_now"


def test_architecture_has_cost_license_security_assessments(architecture):
    assert len(architecture.cost_benefit) == len(architecture.references)
    assert len(architecture.license_risks) == len(architecture.references)
    assert len(architecture.security_risks) == len(architecture.references)
    assert architecture.default_policy.startswith("Do not integrate")


def test_architecture_patterns_cover_brain_workflow_model_trace_and_tools(architecture):
    names = {item.pattern_id for item in architecture.patterns}
    assert names == {"company-brain", "durable-workflow", "model-gateway", "trace-eval", "tool-catalog"}


def test_architecture_seed_changes_mode_without_live_call():
    report = build_architecture_registry(seed=load("architecture_candidates.json"))
    assert next(item for item in report.references if item.system_id == "onyx").integration_mode == "emulate_now"


def test_agent_registry_contains_manager_and_specialist_agents(agents):
    names = {item.name for item in agents.agents}
    assert {"CEO Orchestrator", "Finance Manager", "Sales Manager", "Approval Gatekeeper", "Proposal Builder", "Trace Reviewer"}.issubset(names)
    assert len(agents.agents) >= 30


@pytest.mark.parametrize("agent", build_agent_registry().agents)
def test_agent_has_boundaries_budget_trace_and_eval(agent):
    assert agent.department_owner and agent.responsibilities
    assert agent.allowed_inputs and agent.allowed_outputs
    assert agent.forbidden_actions and agent.approval_required_actions
    assert agent.model_tier and agent.budget_cap >= 0
    assert agent.trace_required and agent.eval_required
    assert agent.default_run_mode in RUN_MODES


@pytest.mark.parametrize("agent", [item for item in build_agent_registry().agents if item.department_owner in {"sales", "launch", "website_store_funnel", "operations"}])
def test_external_action_agents_are_not_live_by_default(agent):
    assert agent.default_run_mode in {"draft_only", "read_only", "approval_required", "blocked"}
    assert agent.default_run_mode != "sandbox" or agent.session_profile.human_interrupts
    assert "publish" in agent.forbidden_actions


def test_approval_gatekeeper_is_approval_required(agents):
    agent = next(item for item in agents.agents if item.agent_id == "approval-gatekeeper")
    assert agent.default_run_mode == "draft_only" or agent.department_owner == "risk_approval"
    assert agent.evaluation_policy.metrics


def test_agent_handoffs_require_approval(agents):
    assert agents.handoff_rules
    assert all(item.approval_required for item in agents.handoff_rules)


def test_agent_seed_can_keep_sales_draft_only():
    report = build_agent_registry(seed=load("agent_registry_seed.json"))
    assert next(item for item in report.agents if item.agent_id == "sdr-draft-agent").default_run_mode == "draft_only"


def test_skill_registry_contains_requested_skills(skills):
    ids = {item.skill_id for item in skills.skills}
    assert {"weekly_operating_review", "lead_scoring", "cold_email_draft", "approval_gate_review", "supplier_proof_review"}.issubset(ids)
    assert len(ids) == 21


@pytest.mark.parametrize("skill", build_skill_registry().skills)
def test_skill_has_contracts_tests_and_boundaries(skill):
    assert skill.name and skill.department_owner and skill.description
    assert skill.trigger_phrases and skill.required_context
    assert skill.allowed_outputs and skill.forbidden_outputs
    assert skill.acceptance_tests and skill.boundary_tests
    assert skill.verification_status in VERIFICATION_STATUSES
    assert skill.input_contract.provenance_required
    assert skill.output_contract.human_review
    assert skill.install_source.trusted is True
    assert skill.install_source.network_required is False


@pytest.mark.parametrize("skill_id", ["cold_email_draft", "dm_draft", "whatsapp_followup_draft", "call_script_draft"])
def test_sales_skills_are_drafts_not_senders(skills, skill_id):
    skill = next(item for item in skills.skills if item.skill_id == skill_id)
    assert "send message" in skill.forbidden_actions
    assert "draft output" in skill.allowed_outputs


@pytest.mark.parametrize("skill_id", ["capital_allocation_plan", "ad_budget_cap_review", "spend_cap_review"])
def test_finance_skills_cannot_pay_or_spend(skills, skill_id):
    skill = next(item for item in skills.skills if item.skill_id == skill_id)
    assert "create payment" in skill.forbidden_actions
    assert "human review" in skill.approval_requirements


@pytest.mark.parametrize("skill_id", ["transaction_categorization", "ledger_reconciliation_review"])
def test_accounting_skills_cannot_mutate_platform(skills, skill_id):
    skill = next(item for item in skills.skills if item.skill_id == skill_id)
    assert "mutate accounting platform" in skill.forbidden_actions


def test_skill_seed_status_is_valid():
    report = build_skill_registry(seed=load("skill_registry_seed.json"))
    assert next(item for item in report.skills if item.skill_id == "lead_scoring").verification_status == "verified"


def test_tool_registry_has_all_categories(tools):
    categories = {item.category for item in tools.tools}
    assert len(categories) >= 22
    assert {"read_file", "send_email", "create_payment", "publish_site", "sync_accounting"}.issubset(categories)


@pytest.mark.parametrize("tool", build_tool_registry().tools)
def test_tool_has_schema_cost_audit_and_sandbox(tool):
    assert tool.category in LIVE_CATEGORIES or tool.risk_level in RISK_LEVELS
    assert tool.auth_mode in AUTH_MODES
    assert tool.provider_candidates
    assert tool.cost_estimate.estimated_cost >= 0
    assert tool.input_schema.rejects_secrets
    assert tool.output_schema.sanitized
    assert tool.audit_event_type
    assert tool.sandbox_policy.audit_required


@pytest.mark.parametrize("category", sorted(LIVE_CATEGORIES))
def test_live_tools_are_blocked_or_approval_gated(category):
    tool = next(item for item in build_tool_registry().tools if item.category == category)
    assert tool.default_mode == "blocked"
    assert tool.approval_required is True
    assert tool.side_effect_profile.external_world is True
    assert tool.approval_policy.approval_required is True


@pytest.mark.parametrize("category", ["read_file", "read_database", "query_vector_memory", "run_script"])
def test_non_live_tools_remain_offline(category):
    tool = next(item for item in build_tool_registry().tools if item.category == category)
    assert tool.sandbox_policy.network_allowed is False
    assert tool.side_effect_profile.external_world is False


def test_tool_seed_cannot_make_email_live():
    report = build_tool_registry(seed=load("tool_registry_seed.json"))
    email = next(item for item in report.tools if item.tool_id == "send_email")
    assert email.default_mode == "blocked"


def test_workflow_registry_contains_requested_workflows(workflows):
    ids = {item.workflow_id for item in workflows.workflows}
    assert {"weekly_operating_review", "supplier_proof_review", "lead_to_sales_brief", "sales_brief_to_proposal", "model_cost_review"}.issubset(ids)
    assert len(ids) == 10


@pytest.mark.parametrize("workflow", build_workflow_registry().workflows)
def test_workflow_has_steps_checkpoints_retries_failures_and_contract(workflow):
    assert workflow.trigger.operator_confirmation_required
    assert workflow.steps and workflow.checkpoint_policy
    assert workflow.human_approval_points
    assert workflow.retry_policy.max_attempts >= 1
    assert workflow.failure_policy.preserve_checkpoint
    assert workflow.output_contract.human_review_required
    assert workflow.run_envelope.advisory and not workflow.run_envelope.authoritative


@pytest.mark.parametrize("interrupt", ["pause_before_external_action", "pause_before_spend", "pause_before_message_send", "pause_before_publish", "pause_before_payment", "pause_before_order"])
def test_workflow_global_interrupts_are_explicit(workflows, interrupt):
    assert interrupt in workflows.global_interrupts
    assert all(any(item.point == interrupt for item in workflow.human_approval_points) for workflow in workflows.workflows)


def test_supplier_proof_workflow_has_approval_pause(workflows):
    workflow = next(item for item in workflows.workflows if item.workflow_id == "supplier_proof_review")
    assert any(item.interrupt_before for item in workflow.steps)
    assert "create_order" in workflow.forbidden_tools


def test_model_router_has_required_tiers(model_router):
    assert {item.tier_id for item in model_router.tiers} == set(MODEL_TIERS)
    assert {item.provider_id for item in model_router.providers} >= {"local_stub", "ollama", "openai", "aws_bedrock"}


@pytest.mark.parametrize("task, tier", [("ledger_categorization", "local_low_cost"), ("sales_draft_variants", "cheap_api"), ("report_synthesis", "frontier_reasoning"), ("legal_finance_approval", "human_review"), ("live_external_action", "blocked")])
def test_model_route_policy(task, tier, model_router):
    route = next(item for item in model_router.policy.routes if item.task_type == task)
    assert route.recommended_tier == tier
    assert route.max_cost_per_run >= 0
    assert route.monthly_budget_cap >= 0
    assert route.human_review_required is (tier in {"frontier_reasoning", "human_review", "blocked"})


def test_live_action_model_route_is_blocked(model_router):
    route = next(item for item in model_router.policy.routes if item.task_type == "live_external_action")
    assert route.recommended_tier == "blocked"
    assert route.max_cost_per_run == 0


def test_model_spend_caps_are_approval_required(model_router):
    assert model_router.spend_caps.approval_event == "approval_required_before_cost"
    assert all(item.budget.approval_required for item in model_router.spend_caps.department_caps)


def test_model_seed_changes_only_bounded_route():
    report = build_model_router(seed=load("model_router_seed.json"))
    assert next(item for item in report.policy.routes if item.task_type == "sales_draft_variants").max_cost_per_run == .1


def test_eval_registry_has_required_metrics(evals):
    assert {item.metric_id for item in evals.metrics} == set(METRICS)
    assert len(evals.quality_gates) == len(QUALITY_GATES)


@pytest.mark.parametrize("metric", METRICS)
def test_eval_metric_is_blocking_and_actionable(evals, metric):
    item = next(item for item in evals.metrics if item.metric_id == metric)
    assert item.threshold and item.failure_action


@pytest.mark.parametrize("gate", QUALITY_GATES)
def test_quality_gate_contains_metrics_and_blocks(evals, gate):
    item = next(item for item in evals.quality_gates if item.gate_id == gate)
    assert item.metric_ids and item.blocking


def test_trace_policy_redacts_secrets(evals):
    policy = evals.trace_policies[0]
    assert {"password", "token", "api_key", "authorization"}.issubset(policy.redact_fields)
    assert policy.capture_inputs is False


def test_prompt_versions_and_datasets_are_synthetic(evals):
    assert evals.prompt_versions[0].status == "verified"
    assert evals.datasets[0].privacy_classification == "synthetic"
    assert evals.cases[0].expected_properties


def test_eval_integration_mapping_names_future_observability(evals):
    assert "trace collection" in evals.integration_mapping["Langfuse"]
    assert "regression testing" in evals.integration_mapping["Phoenix"]


def test_knowledge_registry_has_supported_source_types(knowledge):
    assert {item.source_type for item in knowledge.sources} <= SOURCE_TYPES
    assert {"commerce_report", "launch_draft", "site_draft", "accounting_record", "sales_record"}.issubset({item.source_type for item in knowledge.sources})


@pytest.mark.parametrize("source", build_knowledge_registry().sources)
def test_knowledge_source_has_access_freshness_privacy_policy(source):
    assert source.access_level and source.freshness_policy
    assert source.privacy_classification
    assert source.allowed_agents and source.forbidden_agents


def test_knowledge_collection_is_not_indexed(knowledge):
    assert knowledge.indexing_performed is False
    assert knowledge.collections[0].indexing_status == "not_indexed"
    assert knowledge.embedding_policies[0].network_required is False


def test_knowledge_citations_are_required(knowledge):
    assert knowledge.retrieval_profiles[0].citation_required is True
    assert knowledge.citation_policies[0].missing_citation_action


def test_knowledge_access_requires_human_approval(knowledge):
    assert all(item.human_approval_required for item in knowledge.access_policies)


def test_combined_registry_report_has_correct_counts():
    report = build_companyos_registry_report()
    assert report.registry_count == 8
    assert report.agent_count >= 30
    assert report.skill_count == 21
    assert report.tool_count >= 22
    assert report.workflow_count == 10
    assert report.model_route_count == 5
    assert report.quality_gate_count == 7
    assert report.knowledge_source_count >= 7


def test_combined_report_has_priority_and_blocked_capabilities():
    report = build_companyos_registry_report()
    assert report.highest_priority_next_integrations
    assert "send_email" in report.blocked_capabilities
    assert report.safety_summary["network_calls"] is False
    assert report.next_best_action.startswith("Review LiteLLM")


def test_combined_report_is_json_safe():
    report = build_companyos_registry_report()
    assert isinstance(json.dumps(report.to_dict()), str)
    assert "no external systems" in report.to_markdown().lower()


def test_combined_report_accepts_all_seed_files():
    seeds = {"architecture": load("architecture_candidates.json"), "agents": load("agent_registry_seed.json"), "skills": load("skill_registry_seed.json"), "tools": load("tool_registry_seed.json"), "workflows": load("workflow_registry_seed.json"), "model_router": load("model_router_seed.json"), "evals": load("eval_registry_seed.json"), "knowledge": load("knowledge_registry_seed.json")}
    report = build_companyos_registry_report(seeds=seeds)
    assert report.model_router.policy.routes[1].max_cost_per_run == .1


def test_registry_cli_json_is_offline():
    result = subprocess.run([sys.executable, "scripts/run_companyos_registry_layer.py", "--json"], cwd=ROOT, capture_output=True, text=True, check=True)
    value = json.loads(result.stdout)
    assert value["safety_summary"]["network_calls"] is False
    assert value["safety_summary"]["model_calls"] is False
    assert "not-real-fixture-secret" not in result.stdout


def test_registry_cli_markdown_has_roadmap():
    result = subprocess.run([sys.executable, "scripts/run_companyos_registry_layer.py", "--markdown"], cwd=ROOT, capture_output=True, text=True, check=True)
    assert "# CompanyOS Agent / Skill / Tool / Workflow Registry" in result.stdout
    assert "## Integration Roadmap" in result.stdout
    assert "LiteLLM" in result.stdout or "litellm" in result.stdout


def test_registry_cli_include_flags_are_accepted():
    args = ["--include-architecture", "--include-agents", "--include-skills", "--include-tools", "--include-workflows", "--include-model-router", "--include-evals", "--include-knowledge", "--json"]
    result = subprocess.run([sys.executable, "scripts/run_companyos_registry_layer.py", *args], cwd=ROOT, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["registry_count"] == 8


def test_registry_cli_writes_sanitized_exports(tmp_path):
    result = subprocess.run([sys.executable, "scripts/run_companyos_registry_layer.py", "--output", str(tmp_path), "--markdown"], cwd=ROOT, capture_output=True, text=True, check=True)
    assert "CompanyOS Agent" in result.stdout
    expected = {"companyos_registry_report.json", "companyos_registry_report.md", "architecture_registry.json", "integration_roadmap.md", "agent_registry.json", "skill_registry.json", "tool_registry.json", "workflow_registry.json", "model_routing_policy.json", "eval_policy.json", "knowledge_registry.json"}
    assert expected == {item.name for item in tmp_path.iterdir()}


def test_registry_cli_rejects_traversal():
    result = subprocess.run([sys.executable, "scripts/run_companyos_registry_layer.py", "--architecture-seed", "../not-allowed.json", "--json"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 2
    assert "traversal" in result.stderr


def test_registry_cli_rejects_secret_like_input():
    result = subprocess.run([sys.executable, "scripts/run_companyos_registry_layer.py", "--architecture-seed", "tests/fixtures/companyos_registry/secret_like_registry_input_rejected.json", "--json"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 2
    assert "secret-like" in result.stderr


def test_registry_cli_is_deterministic():
    args = [sys.executable, "scripts/run_companyos_registry_layer.py", "--json"]
    first = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True).stdout
    second = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert first == second


def test_registry_has_no_provider_clients_or_calls_in_source():
    source = (ROOT / "scripts" / "run_companyos_registry_layer.py").read_text(encoding="utf-8")
    assert "requests" not in source.lower()
    assert "httpx" not in source.lower()
    assert "openai" not in source.lower()


def test_registry_does_not_index_knowledge():
    value = build_companyos_registry_report().to_dict()
    assert value["knowledge"]["indexing_performed"] is False


def test_registry_does_not_authorize_external_actions():
    report = build_companyos_registry_report()
    assert all(item.default_mode == "blocked" for item in report.tools.tools if item.category in LIVE_CATEGORIES)
    assert all(item.authoritative is False for item in report.workflows.workflows for item in [item.run_envelope])
