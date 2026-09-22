import json

from backend.deployment.readiness import build_readiness
from scripts import check_readonly_deployment_readiness as readiness_cli

def test_missing_credentials_blocks_without_values():
 r=build_readiness(environ={"MARKETOS_EVENT_READ_JSONL_PATH":"artifacts/events.jsonl"}).to_dict()
 assert r["overall_status"]=="blocked" and r["secret_presence_redacted"]["CJ_API_KEY"] is False
 assert "CJ_API_KEY" not in str(r["secret_presence_redacted"].values())
 assert r["readiness_endpoint_status"] == "not_run"

def test_readonly_cj_configuration_is_ready():
 env={"MARKETOS_SUPPLIER_PROVIDER":"cj","MARKETOS_SUPPLIER_AUTH_READONLY":"1","CJ_EMAIL":"operator@example.test","CJ_API_KEY":"secret","MARKETOS_EVENT_READ_JSONL_PATH":"artifacts/events.jsonl","MARKETOS_EVENT_WRITE_JSONL_PATH":"artifacts/events.jsonl"}
 r=build_readiness(environ=env).to_dict()
 assert r["supplier_readonly_status"]=="ready" and r["overall_status"]=="ready"
 assert "operator@example.test" not in str(r) and "'secret'" not in str(r)

def test_mutation_flags_block_readiness():
 r=build_readiness(environ={"SHOPIFY_WRITE_ENABLED":"1","MARKETOS_EVENT_READ_JSONL_PATH":"artifacts/events.jsonl"}).to_dict()
 assert r["mutation_authority_status"]=="unsafe_mutation_authority_present"
 assert "unsafe_mutation_authority_present" in r["blocking_gates"]

def test_platform_is_constrained():
 assert build_readiness(environ={},platform="unknown").platform=="local"

def test_readiness_cli_fails_closed_when_report_is_blocked(monkeypatch, capsys):
 monkeypatch.setattr(readiness_cli, "build_readiness", lambda **_: build_readiness(environ={}))
 assert readiness_cli.main(["--json"]) == 1
 report=json.loads(capsys.readouterr().out)
 assert report["overall_status"] == "blocked"
