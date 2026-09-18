import json
from pathlib import Path
import evaluation.commerce.product_validation_report as pvr
from evaluation.commerce.product_validation_report import generate,markdown
from evaluation.commerce.benchmark_matrix import build_benchmark_from_paths

ROOT=Path(__file__).resolve().parents[1]
BENCHMARK_SEED=ROOT/"tests"/"fixtures"/"benchmark_matrix"/"candidates.json"

def _forbidden(*_a,**_k):
 raise AssertionError("VAL-GENERATE-DEFAULT-BUILDERS: path-builder must not run when the caller omitted benchmark/readiness/deployment")

def test_fixture_report_is_client_safe():
 r=generate(client_name="Demo Client").to_dict()
 assert r['client_name_optional']=='Demo Client' and r['read_only'] and not r['network_calls'] and not r['mutated']
 assert r['evidence_mode']=='fixture_demo' and 'profit guarantee' in r['operator_disclaimer']
def test_markdown_has_required_client_sections():
 text=markdown(generate().to_dict())
 for section in ('Executive Summary','Candidate Ranking','Supplier Readiness','Risk Flags','Disclaimer'):assert section in text

# --- VAL-GENERATE-DEFAULT-BUILDERS regressions ---

def test_omitted_arguments_never_reach_path_builders(monkeypatch):
 """Required scenario: omitted generate arguments. A bare generate() call
 must never invoke build_benchmark_from_paths/build_from_paths/
 build_readiness -- those are exactly the credential-bearing/path-builder
 flows the mission forbids reaching merely because optional stubs were
 left out."""
 monkeypatch.setattr(pvr,"build_benchmark_from_paths",_forbidden)
 monkeypatch.setattr(pvr,"build_from_paths",_forbidden)
 monkeypatch.setattr(pvr,"build_readiness",_forbidden)
 report=generate().to_dict()
 assert report["evidence_mode"]=="fixture_demo"

def test_omitted_arguments_return_deterministic_blocked_result_with_reason():
 report=generate().to_dict()
 assert report["launch_readiness"]=={"status":"blocked","deployment":"blocked"}
 assert "no_evidence_supplied" in report["risk_flags"]
 assert report["overall_recommendation"]=="validate_supplier_first"

def test_omitted_arguments_next_action_never_mentions_credentials():
 blob=json.dumps(generate().to_dict()).lower()
 assert "cj" not in blob
 assert "set_cj_credentials" not in blob
 assert "configure_cj" not in blob
 assert "credentials_present" not in blob

def test_omitted_arguments_do_not_read_credential_environment_variables(monkeypatch):
 """No credential/provider/network behavior: even if the real process
 environment carries CJ credentials, a bare generate() call must never
 consult them (it must not reach os.environ at all on the default path)."""
 monkeypatch.setenv("CJ_EMAIL","synthetic-operator@example.com")
 monkeypatch.setenv("CJ_API_KEY","sk-synthetic-must-not-leak")
 blob=json.dumps(generate().to_dict())
 assert "synthetic-operator@example.com" not in blob
 assert "sk-synthetic-must-not-leak" not in blob

def test_explicit_safe_stubs_never_reach_path_builders(monkeypatch):
 """Required scenario: explicit safe stubs. A caller supplying its own
 (even fully blocked) benchmark/readiness/deployment stubs must keep
 getting exactly that supplied content -- never silently replaced by a
 path-builder call."""
 monkeypatch.setattr(pvr,"build_benchmark_from_paths",_forbidden)
 monkeypatch.setattr(pvr,"build_from_paths",_forbidden)
 monkeypatch.setattr(pvr,"build_readiness",_forbidden)
 report=generate(
  benchmark={"candidates":[],"evidence_mode":"fixture_demo"},
  readiness={"overall_status":"blocked","supplier_readiness":{"status":"unknown"},"blocking_gates":["first_phase_blocked_readiness"],"next_best_action":"expand_supplier_research"},
  deployment={"overall_status":"blocked"},
 ).to_dict()
 assert report["source_reports"]["benchmark"]=="supplied"
 assert report["source_reports"]["readiness"]=="supplied"
 assert "cj" not in json.dumps(report).lower()

def test_explicit_path_seed_still_works_and_stays_credential_free():
 """Required scenario: explicit paths. When a caller does point a
 path-builder at a real, explicit fixture path, the (pre-existing, safe)
 file-reading behavior is preserved -- build_benchmark_from_paths never
 touches credentials/environment regardless of path usage."""
 report=build_benchmark_from_paths(candidate_seed=BENCHMARK_SEED).to_dict()
 assert report["candidate_count"]>0
 assert report["network_calls"] is False
 assert report["source_artifacts"]["candidate_seed"]==str(BENCHMARK_SEED)
