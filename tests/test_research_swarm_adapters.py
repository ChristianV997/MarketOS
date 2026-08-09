import json
import sys

from backend.research import AgentReachSensorAdapter, HermesRuntimeAdapter, SwarmJobSpec, benchmark_runtimes
from backend.research.swarm_adapters import DeerFlowRuntimeAdapter


def _spec(runtime="hermes"):
    return SwarmJobSpec.create(
        job_id="benchmark-1",
        query="research tools",
        objective="collect attributable evidence",
        runtime=runtime,
        sources=("agent_reach",),
    )


def _envelope(spec, runtime=None):
    return {
        "schema": "MarketOS.ResearchEvidence.v1",
        "job_id": spec["job_id"],
        "runtime": runtime or spec["runtime"],
        "status": "succeeded",
        "records": [{
            "evidence_id": "evidence-1",
            "topic": "research tools",
            "intent": "research",
            "velocity": 0.5,
            "competition": None,
            "source": "agent_reach",
            "freshness_ts": "2026-08-02T00:00:00+00:00",
            "confidence": 0.8,
            "raw": {"title": "Research tools"},
            "source_url": "https://example.com/research-tools",
            "retrieved_at": "2026-08-02T00:00:00+00:00",
            "provider": "fixture",
        }],
        "rejected": [],
    }


def test_agent_reach_bridge_uses_argv_and_json_stdin(monkeypatch):
    monkeypatch.setenv("FF_RESEARCH_SENSOR_AGENT_REACH", "true")
    command = [
        sys.executable,
        "-c",
        "import json,sys; req=json.load(sys.stdin); print(json.dumps({'records': [], 'request_id': req['request_id']}))",
    ]
    adapter = AgentReachSensorAdapter(command=command)
    response = adapter.fetch(_spec().to_dict())
    assert response["records"] == []
    assert response["request_id"]
    assert adapter.health().reachable is True


def test_agent_reach_bridge_is_flag_gated(monkeypatch):
    monkeypatch.setenv("FF_RESEARCH_SENSOR_AGENT_REACH", "false")
    adapter = AgentReachSensorAdapter(command=[sys.executable, "-c", "print('{}')"])
    try:
        adapter.fetch(_spec().to_dict())
    except RuntimeError as err:
        assert "disabled" in str(err)
    else:
        raise AssertionError("disabled Agent-Reach sensor unexpectedly executed")


def test_hermes_and_deerflow_benchmark_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("FF_RESEARCH_SWARM_HERMES", raising=False)
    monkeypatch.delenv("FF_RESEARCH_SWARM_DEERFLOW", raising=False)
    result = benchmark_runtimes(_spec(), runtimes={})
    assert result["persisted"] is False
    assert result["results"]["hermes"]["status"] == "skipped"
    assert result["results"]["deerflow"]["status"] == "skipped"


def test_benchmark_validates_both_runtime_envelopes_without_persistence(monkeypatch):
    monkeypatch.setenv("FF_RESEARCH_SWARM_HERMES", "true")
    monkeypatch.setenv("FF_RESEARCH_SWARM_DEERFLOW", "true")
    runtimes = {
        "hermes": lambda spec: _envelope(spec, "hermes"),
        "deerflow": lambda spec: _envelope(spec, "deerflow"),
    }
    result = benchmark_runtimes(_spec(), runtimes=runtimes)
    assert result["persisted"] is False
    assert result["results"]["hermes"]["status"] == "succeeded"
    assert result["results"]["deerflow"]["status"] == "succeeded"
    assert result["results"]["hermes"]["record_count"] == 1
    assert result["results"]["deerflow"]["envelope_hash"]


def test_hermes_http_adapter_extracts_governed_json_without_network(monkeypatch):
    monkeypatch.setenv("FF_RESEARCH_SWARM_HERMES", "true")
    spec = _spec().to_dict()
    adapter = HermesRuntimeAdapter(request=lambda url, payload, **kwargs: {
        "choices": [{"message": {"content": json.dumps(_envelope(spec, "hermes"))}}],
    })
    response = adapter(spec)
    assert response["runtime"] == "hermes"
    assert response["records"][0]["source"] == "agent_reach"


def test_deerflow_sse_parser_extracts_governed_json(monkeypatch):
    spec = _spec("deerflow").to_dict()
    payload = json.dumps(_envelope(spec, "deerflow"))
    raw = ("event: values\n" + "data: " + json.dumps({"messages": [{"role": "assistant", "content": payload}]}) + "\n\n").encode()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _limit):
            return raw

    monkeypatch.setenv("FF_RESEARCH_SWARM_DEERFLOW", "true")
    monkeypatch.setattr("backend.research.swarm_adapters.urlopen", lambda *args, **kwargs: Response())
    response = DeerFlowRuntimeAdapter()(spec)
    assert response["runtime"] == "deerflow"
    assert response["records"][0]["source"] == "agent_reach"
