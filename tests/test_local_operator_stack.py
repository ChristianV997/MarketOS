"""Tests for scripts/run_local_operator_stack.py.

Uses temp directories and harmless subprocess HTTP servers. Does not start
the real uvicorn MarketOS API or the Vite frontend, and does not call live
providers.
"""
from __future__ import annotations

import socket
import sys
import textwrap
import time
from pathlib import Path
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.run_local_operator_stack as stack


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _occupy(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(1)
    return sock


def _dummy_server_script(secret_line: str = "") -> str:
    extra = f"print({secret_line!r}, flush=True)\n" if secret_line else ""
    return textwrap.dedent(
        f"""
        import http.server
        import sys

        {extra}
        host, port = sys.argv[1], int(sys.argv[2])

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'ok'
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, format, *args):
                return

        http.server.HTTPServer((host, port), Handler).serve_forever()
        """
    )


def _write_repo(tmp_path: Path, *, frontend: bool = True, backend: bool = True) -> Path:
    if backend:
        (tmp_path / "backend").mkdir()
        (tmp_path / "backend" / "api.py").write_text("# fixture backend marker\n", encoding="utf-8")
    if frontend:
        (tmp_path / "frontend").mkdir()
        (tmp_path / "frontend" / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
    return tmp_path


def _config(tmp_path: Path, **kwargs) -> stack.StackConfig:
    api_port = kwargs.pop("api_port", _free_port())
    frontend_port = kwargs.pop("frontend_port", _free_port())
    return stack.StackConfig(
        repo=tmp_path,
        api_port=api_port,
        frontend_port=frontend_port,
        startup_timeout_s=kwargs.pop("startup_timeout_s", 5.0),
        request_timeout_s=kwargs.pop("request_timeout_s", 1.0),
        **kwargs,
    )


def _dummy_argv(script: Path, host: str, port: int) -> list[str]:
    return [sys.executable, str(script), host, str(port)]


def test_redact_and_cap_log():
    text = "Authorization: Bearer sk-live-SECRETTOKEN password=hunter2 " + ("x" * 200)
    redacted = stack.redact(text)
    assert "sk-live-SECRETTOKEN" not in redacted
    assert "hunter2" not in redacted or "[redacted]" in redacted
    capped = stack.cap_log("a" * 500, 32)
    assert "truncated" in capped
    assert len(capped.encode("utf-8")) < 80


def test_fixture_environ_strips_secrets():
    env = stack.fixture_environ(
        {
            "OPENAI_API_KEY": "sk-live-abc",
            "AWS_SECRET_ACCESS_KEY": "sentinel-secret",
            "PATH": "/bin",
            "FOO": "1",
            "ALLOWED_ORIGINS": "https://untrusted.example",
            "CYCLES_PER_MINUTE": "999",
        }
    )
    assert "OPENAI_API_KEY" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "FOO" not in env
    assert env["MARKETOS_MVP_MODE"] == "1"
    assert env["MARKETOS_PUBLIC_COMMERCE_RUNS"] == "0"
    assert env["MARKETOS_ALLOW_LIVE"] == "0"
    assert env["ALLOWED_ORIGINS"] == "http://127.0.0.1:5173"
    assert env["CYCLES_PER_MINUTE"] == "1"


def test_non_loopback_bind_is_blocked_before_preflight(tmp_path: Path):
    repo = _write_repo(tmp_path)
    cfg = _config(repo, api_host="0.0.0.0")
    report = stack.run_rehearsal(cfg)
    assert report["classification"] == "blocked"
    assert "api_host_not_loopback" in report["reason"]


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"api_port": 0}, "api_port_out_of_range"),
        ({"startup_timeout_s": 121.0}, "startup_timeout_out_of_range"),
        ({"request_timeout_s": 31.0}, "request_timeout_out_of_range"),
        ({"hold_s": 301.0}, "hold_s_out_of_range"),
    ],
)
def test_unbounded_or_invalid_config_is_blocked(tmp_path: Path, kwargs, reason):
    repo = _write_repo(tmp_path)
    cfg = _config(repo, **kwargs)
    report = stack.run_rehearsal(cfg)
    assert report["classification"] == "blocked"
    assert reason in report["reason"]


def test_dry_run_does_not_bind(tmp_path: Path):
    repo = _write_repo(tmp_path)
    cfg = _config(repo, dry_run=True)
    report = stack.run_rehearsal(cfg)
    assert report["classification"] == "not_run"
    assert report["dry_run"] is True
    assert stack.port_in_use(cfg.api_host, cfg.api_port) is False


def test_occupied_api_port_is_blocked(tmp_path: Path):
    repo = _write_repo(tmp_path)
    port = _free_port()
    holder = _occupy("127.0.0.1", port)
    try:
        cfg = _config(repo, api_port=port)
        report = stack.run_rehearsal(cfg)
        assert report["classification"] == "blocked"
        assert "api_port_occupied" in report["reason"]
    finally:
        holder.close()


def test_occupied_frontend_port_is_blocked(tmp_path: Path):
    repo = _write_repo(tmp_path)
    port = _free_port()
    holder = _occupy("127.0.0.1", port)
    try:
        cfg = _config(repo, frontend_port=port, start_backend=False)
        report = stack.run_rehearsal(cfg)
        assert report["classification"] == "blocked"
        assert "frontend_port_occupied" in report["reason"]
    finally:
        holder.close()


def test_missing_frontend_package_is_unavailable(tmp_path: Path):
    repo = _write_repo(tmp_path, frontend=False)
    cfg = _config(repo, start_backend=False, start_frontend=True)
    report = stack.run_rehearsal(cfg)
    assert report["classification"] == "unavailable"
    assert report["reason"] == "frontend_package_json_missing"


def test_missing_backend_module_is_unavailable(tmp_path: Path):
    repo = _write_repo(tmp_path, backend=False)
    cfg = _config(repo, start_frontend=False)
    report = stack.run_rehearsal(cfg)
    assert report["classification"] == "unavailable"
    assert report["reason"] == "backend_api_module_missing"


def test_successful_fixture_startup_and_cleanup(tmp_path: Path):
    repo = _write_repo(tmp_path)
    script = tmp_path / "dummy_http.py"
    script.write_text(_dummy_server_script(secret_line="password=supersecret"), encoding="utf-8")
    cfg = _config(repo)
    report = stack.run_rehearsal(
        cfg,
        backend_argv_override=_dummy_argv(script, cfg.api_host, cfg.api_port),
        frontend_argv_override=_dummy_argv(script, cfg.frontend_host, cfg.frontend_port),
    )
    assert report["classification"] in {"passed", "partial"}
    health = next(row for row in report["surfaces"] if row["name"] == "health")
    assert health["classification"] == "passed"
    cockpit = next(row for row in report["surfaces"] if row["name"] == "cockpit_ui")
    assert cockpit["classification"] == "passed"
    workbench_ui = next(row for row in report["surfaces"] if row["name"] == "workbench_ui")
    assert workbench_ui["classification"] == "passed"
    assert report["cleanup"]["backend"] in {"terminated", "killed", "already_exited"}
    assert report["cleanup"]["frontend"] in {"terminated", "killed", "already_exited"}
    assert "supersecret" not in report["logs"]["backend"]
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and (
        stack.port_in_use(cfg.api_host, cfg.api_port) or stack.port_in_use(cfg.frontend_host, cfg.frontend_port)
    ):
        time.sleep(0.05)
    assert stack.port_in_use(cfg.api_host, cfg.api_port) is False
    assert stack.port_in_use(cfg.frontend_host, cfg.frontend_port) is False


def test_backend_unavailable_does_not_invent_success(tmp_path: Path):
    repo = _write_repo(tmp_path)
    cfg = _config(repo, start_backend=False, start_frontend=False)
    report = stack.run_rehearsal(cfg)
    health = next(row for row in report["surfaces"] if row["name"] == "health")
    workbench = next(row for row in report["surfaces"] if row["name"] == "workbench_api")
    assert health["classification"] == "unavailable"
    assert workbench["classification"] == "unavailable"
    assert report["classification"] == "unavailable"


def test_startup_timeout(tmp_path: Path):
    repo = _write_repo(tmp_path)
    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    cfg = _config(repo, start_frontend=False, startup_timeout_s=0.3)
    report = stack.run_rehearsal(
        cfg,
        backend_argv_override=[sys.executable, str(sleeper)],
    )
    assert report["classification"] == "timeout"
    assert report["reason"] == "backend_startup_timeout"
    assert report["cleanup"]["backend"] in {"terminated", "killed", "already_exited"}
    assert stack.port_in_use(cfg.api_host, cfg.api_port) is False


def test_frontend_process_exit_is_failed(tmp_path: Path):
    repo = _write_repo(tmp_path)
    boom = tmp_path / "boom.py"
    boom.write_text("raise SystemExit(7)\n", encoding="utf-8")
    dummy = tmp_path / "dummy_http.py"
    dummy.write_text(_dummy_server_script(), encoding="utf-8")
    cfg = _config(repo, startup_timeout_s=2.0)
    report = stack.run_rehearsal(
        cfg,
        backend_argv_override=_dummy_argv(dummy, cfg.api_host, cfg.api_port),
        frontend_argv_override=[sys.executable, str(boom)],
    )
    assert report["classification"] == "failed"
    assert report["reason"].startswith("frontend_exited")


def test_http_404_is_surface_absent_not_passed():
    port = _free_port()
    import http.server
    import threading

    class NotFound(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404)
            self.end_headers()

        def log_message(self, format, *args):
            return

    server = http.server.HTTPServer(("127.0.0.1", port), NotFound)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    time.sleep(0.05)
    row = stack.http_get(f"http://127.0.0.1:{port}/api/service-delivery/workbench", 1.0)
    server.server_close()
    assert row["classification"] == "surface_absent"
    assert row["http_status"] == 404


def test_http_probe_does_not_follow_redirects(monkeypatch: pytest.MonkeyPatch):
    captured_handlers = []

    class RedirectingOpener:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 302, "redirect", {}, None)

    def fake_build_opener(*handlers):
        captured_handlers.extend(handlers)
        return RedirectingOpener()

    monkeypatch.setattr(stack.urllib.request, "build_opener", fake_build_opener)
    row = stack.http_get("http://127.0.0.1:3000/health", 1.0)
    assert row["classification"] == "failed"
    assert row["http_status"] == 302
    assert any(handler.__class__.__name__ == "_NoRedirectHandler" for handler in captured_handlers)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.invalid/health",
        "http://user:sentinel-42@127.0.0.1:3000/health",
        "http://127.0.0.1:3000/health?marker=sentinel-42",
    ],
)
def test_http_probe_rejects_unsafe_target_without_network(url):
    row = stack.http_get(url, 1.0)
    assert row["classification"] == "blocked"
    assert row["http_status"] is None
    assert "sentinel-42" not in stack.json.dumps(row)


def test_cli_dry_run_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    repo = _write_repo(tmp_path)
    code = stack.main(["--repo", str(repo), "--dry-run", "--json", "--backend-only"])
    captured = capsys.readouterr()
    assert code == 0
    body = stack.json.loads(captured.out)
    assert body["schema"] == stack.SCHEMA
    assert body["classification"] == "not_run"
