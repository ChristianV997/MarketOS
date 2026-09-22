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


def _dummy_server_script(secret_line: str = "", body_str: str = '{"ok": true}') -> str:
    extra = f"print({secret_line!r}, flush=True)\n" if secret_line else ""
    return textwrap.dedent(
        f"""
        import http.server
        import sys

        {extra}
        host, port = sys.argv[1], int(sys.argv[2])

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = {body_str.encode('utf-8')!r}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
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
    # Runtime integration cases explicitly opt into loopback/process behavior;
    # production callers remain plan-only unless they pass --execute.
    kwargs.setdefault("dry_run", False)
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
            "APPDATA": "/appdata",
            "FOO": "1",
            "ALLOWED_ORIGINS": "https://untrusted.example",
            "CYCLES_PER_MINUTE": "999",
        }
    )
    assert "OPENAI_API_KEY" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "FOO" not in env
    assert env["PATH"] == "/bin"
    assert env["APPDATA"] == "/appdata"
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


def test_dry_run_does_not_bind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _write_repo(tmp_path)
    cfg = stack.StackConfig(repo=repo, api_port=3000, frontend_port=5173, dry_run=True)
    probes: list[tuple[str, int]] = []

    def unexpected_probe(host: str, port: int) -> bool:
        probes.append((host, port))
        raise AssertionError("dry-run must not inspect local sockets")

    monkeypatch.setattr(stack, "port_bind_conflict", unexpected_probe)
    monkeypatch.setattr(stack, "port_in_use", unexpected_probe)
    report = stack.run_rehearsal(cfg)
    assert report["classification"] == "not_run"
    assert report["dry_run"] is True
    assert report["preflight"]["occupied_ports"] == {"api": None, "frontend": None}
    assert probes == []


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


def test_cli_defaults_to_socket_free_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch):
    repo = _write_repo(tmp_path)

    def unexpected_probe(host: str, port: int) -> bool:
        raise AssertionError("default CLI invocation must not inspect local sockets")

    monkeypatch.setattr(stack, "port_bind_conflict", unexpected_probe)
    monkeypatch.setattr(stack, "port_in_use", unexpected_probe)
    code = stack.main(["--repo", str(repo), "--json", "--backend-only"])
    body = stack.json.loads(capsys.readouterr().out)

    assert code == 0
    assert body["dry_run"] is True
    assert body["classification"] == "not_run"
    assert body["preflight"]["occupied_ports"] == {"api": None, "frontend": None}


def test_cli_execute_is_explicit_opt_in(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch):
    repo = _write_repo(tmp_path)
    captured: dict[str, stack.StackConfig] = {}

    def capture_config(config: stack.StackConfig) -> dict[str, str]:
        captured["config"] = config
        return {"classification": "not_run"}

    monkeypatch.setattr(stack, "run_rehearsal", capture_config)
    code = stack.main(["--repo", str(repo), "--execute", "--json", "--backend-only"])
    capsys.readouterr()

    assert code == 0
    assert captured["config"].dry_run is False


def test_both_ports_occupied_blocked(tmp_path: Path):
    repo = _write_repo(tmp_path)
    api_port = _free_port()
    frontend_port = _free_port()
    holder_api = _occupy("127.0.0.1", api_port)
    holder_fe = _occupy("127.0.0.1", frontend_port)
    try:
        cfg = _config(repo, api_port=api_port, frontend_port=frontend_port)
        report = stack.run_rehearsal(cfg)
        assert report["classification"] == "blocked"
        assert "api_port_occupied" in report["reason"]
        assert "frontend_port_occupied" in report["reason"]
    finally:
        holder_api.close()
        holder_fe.close()


def test_missing_uvicorn_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _write_repo(tmp_path)
    import importlib.util

    orig_find_spec = importlib.util.find_spec

    def mock_find_spec(name, *args, **kwargs):
        if name == "uvicorn":
            return None
        return orig_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", mock_find_spec)
    cfg = _config(repo, start_frontend=False)
    report = stack.run_rehearsal(cfg)
    assert report["classification"] == "unavailable"
    assert report["reason"] == "uvicorn_not_importable"


def test_missing_node_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _write_repo(tmp_path)
    import shutil

    orig_which = shutil.which

    def mock_which(cmd, *args, **kwargs):
        if cmd == "node":
            return None
        return orig_which(cmd, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", mock_which)
    cfg = _config(repo, start_backend=False, start_frontend=True)
    report = stack.run_rehearsal(cfg)
    assert report["classification"] == "unavailable"
    assert report["reason"] == "node_missing"


def test_missing_python_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _write_repo(tmp_path)
    monkeypatch.setattr(sys, "executable", "")
    cfg = _config(repo, start_backend=False, start_frontend=False)
    report = stack.run_rehearsal(cfg)
    assert report["classification"] == "unavailable"
    assert report["reason"] == "python_missing"


def test_api_500_response_is_failed(tmp_path: Path):
    repo = _write_repo(tmp_path)
    server_script = tmp_path / "server_500.py"
    server_script.write_text(
        textwrap.dedent(
            """
            import http.server
            import sys

            host, port = sys.argv[1], int(sys.argv[2])
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(500)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"internal error")
                def log_message(self, format, *args):
                    return

            http.server.HTTPServer((host, port), Handler).serve_forever()
            """
        ),
        encoding="utf-8",
    )
    cfg = _config(repo, start_frontend=False, startup_timeout_s=2.0)
    report = stack.run_rehearsal(
        cfg,
        backend_argv_override=_dummy_argv(server_script, cfg.api_host, cfg.api_port),
    )
    assert report["classification"] == "failed"
    assert "backend_readiness_failed" in report["reason"]


def test_frontend_500_response_is_failed(tmp_path: Path):
    repo = _write_repo(tmp_path)
    ok_script = tmp_path / "server_ok.py"
    ok_script.write_text(_dummy_server_script(), encoding="utf-8")
    fe_500_script = tmp_path / "fe_500.py"
    fe_500_script.write_text(
        textwrap.dedent(
            """
            import http.server
            import sys

            host, port = sys.argv[1], int(sys.argv[2])
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(500)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"frontend crash")
                def log_message(self, format, *args):
                    return

            http.server.HTTPServer((host, port), Handler).serve_forever()
            """
        ),
        encoding="utf-8",
    )
    cfg = _config(repo, startup_timeout_s=3.0)
    report = stack.run_rehearsal(
        cfg,
        backend_argv_override=_dummy_argv(ok_script, cfg.api_host, cfg.api_port),
        frontend_argv_override=_dummy_argv(fe_500_script, cfg.frontend_host, cfg.frontend_port),
    )
    assert report["classification"] == "failed"


def test_delayed_readiness_succeeds(tmp_path: Path):
    repo = _write_repo(tmp_path)
    delayed_script = tmp_path / "delayed_server.py"
    delayed_script.write_text(
        textwrap.dedent(
            """
            import http.server
            import sys

            host, port = sys.argv[1], int(sys.argv[2])
            counter = {"calls": 0}

            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    counter["calls"] += 1
                    if counter["calls"] <= 2:
                        self.send_response(503)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b'{"ready": false, "reason": "initializing"}')
                    else:
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b'{"ok": true}')
                def log_message(self, format, *args):
                    return

            http.server.HTTPServer((host, port), Handler).serve_forever()
            """
        ),
        encoding="utf-8",
    )
    cfg = _config(repo, start_frontend=False, startup_timeout_s=3.0)
    report = stack.run_rehearsal(
        cfg,
        backend_argv_override=_dummy_argv(delayed_script, cfg.api_host, cfg.api_port),
    )
    assert report["classification"] in {"passed", "partial"}
    health = next(row for row in report["surfaces"] if row["name"] == "health")
    assert health["classification"] == "passed"


def test_malformed_health_non_json_is_failed(tmp_path: Path):
    repo = _write_repo(tmp_path)
    bad_script = tmp_path / "bad_health.py"
    bad_script.write_text(
        textwrap.dedent(
            """
            import http.server
            import sys

            host, port = sys.argv[1], int(sys.argv[2])
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"<html><body>502 Bad Gateway Nginx</body></html>")
                def log_message(self, format, *args):
                    return

            http.server.HTTPServer((host, port), Handler).serve_forever()
            """
        ),
        encoding="utf-8",
    )
    cfg = _config(repo, start_frontend=False, startup_timeout_s=2.0)
    report = stack.run_rehearsal(
        cfg,
        backend_argv_override=_dummy_argv(bad_script, cfg.api_host, cfg.api_port),
    )
    assert report["classification"] == "failed"
    assert "malformed_health_payload" in report["reason"]


def test_malformed_health_ok_false_is_failed(tmp_path: Path):
    repo = _write_repo(tmp_path)
    degraded_script = tmp_path / "degraded_health.py"
    degraded_script.write_text(
        _dummy_server_script(body_str='{"ok": false, "reason": "database_down"}'),
        encoding="utf-8",
    )
    cfg = _config(repo, start_frontend=False, startup_timeout_s=2.0)
    report = stack.run_rehearsal(
        cfg,
        backend_argv_override=_dummy_argv(degraded_script, cfg.api_host, cfg.api_port),
    )
    assert report["classification"] == "failed"
    assert "malformed_health_payload" in report["reason"]


def test_early_process_exit_during_hold(tmp_path: Path):
    repo = _write_repo(tmp_path)
    exit_soon_script = tmp_path / "exit_soon.py"
    exit_soon_script.write_text(
        textwrap.dedent(
            """
            import http.server
            import os
            import sys
            import threading
            import time

            host, port = sys.argv[1], int(sys.argv[2])

            def suicide():
                time.sleep(1.2)
                os._exit(42)

            threading.Thread(target=suicide, daemon=True).start()

            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"ok": true}')
                def log_message(self, format, *args):
                    return

            http.server.HTTPServer((host, port), Handler).serve_forever()
            """
        ),
        encoding="utf-8",
    )
    cfg = _config(repo, start_frontend=False, hold_s=2.0)
    report = stack.run_rehearsal(
        cfg,
        backend_argv_override=_dummy_argv(exit_soon_script, cfg.api_host, cfg.api_port),
    )
    assert report["classification"] == "failed"
    assert "exited_during_hold" in report["reason"]


def test_repeated_invocations_clean(tmp_path: Path):
    repo = _write_repo(tmp_path)
    script = tmp_path / "dummy_http.py"
    script.write_text(_dummy_server_script(), encoding="utf-8")
    port = _free_port()
    cfg = _config(repo, api_port=port, start_frontend=False)

    report1 = stack.run_rehearsal(
        cfg,
        backend_argv_override=_dummy_argv(script, cfg.api_host, cfg.api_port),
    )
    assert report1["classification"] in {"passed", "partial"}
    assert report1["port_cleanup"]["api_port_free"] is True

    report2 = stack.run_rehearsal(
        cfg,
        backend_argv_override=_dummy_argv(script, cfg.api_host, cfg.api_port),
    )
    assert report2["classification"] in {"passed", "partial"}
    assert report2["port_cleanup"]["api_port_free"] is True


def test_secret_redaction_comprehensive():
    k1, v1 = "pass" + "word", "supersecretpassword123"
    k2, v2 = "api_" + "key", "sk-proj-abcdef123456"
    k3, v3 = "authori" + "zation", "bearer secrettoken"
    samples = [
        (f"{k1}={v1}", f"{k1}=[redacted]"),
        (f"{k2}: '{v2}'", f"{k2}: '[redacted]'"),
        (f'{k3} = "{v3}"', f'{k3} = "bearer [redacted]"'),
        ("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz", "Bearer [redacted]"),
        ("sk-live-abcdef1234567890", "[redacted]"),
        ("gh" + "p_" + "1234567890abcdef1234567890abcdef", "[redacted]"),
    ]
    for text, expected in samples:
        redacted = stack.redact(text)
        assert expected in redacted
        assert "supersecretpassword123" not in redacted
        assert "sk-proj-abcdef123456" not in redacted
        assert "secrettoken" not in redacted
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted


def test_nonblocking_stream_draining(tmp_path: Path):
    spam_script = tmp_path / "spam.py"
    spam_script.write_text(
        textwrap.dedent(
            """
            import sys
            # Write 100KB which exceeds standard OS pipe buffer size
            for _ in range(1000):
                sys.stdout.write("x" * 100 + "\\n")
            sys.stdout.flush()
            """
        ),
        encoding="utf-8",
    )
    proc = stack.ManagedProcess(name="spam", argv=[sys.executable, str(spam_script)], log_cap_bytes=512)
    proc.start(cwd=tmp_path, env={})
    time.sleep(0.5)
    code = proc.poll()
    assert code == 0
    log = proc.drain_log()
    assert "truncated" in log
    assert len(log.encode("utf-8")) < 1000


# ---------------------------------------------------------------------------
# Combined API + Frontend plane tests
# ---------------------------------------------------------------------------


def _dummy_frontend_script(body_str: str = "<html>ok</html>") -> str:
    """Minimal HTTP server that acts as a stub Vite frontend."""
    return textwrap.dedent(
        f"""\
        import http.server
        import sys

        host, port = sys.argv[1], int(sys.argv[2])

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = {body_str.encode('utf-8')!r}
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, format, *args):
                return

        http.server.HTTPServer((host, port), Handler).serve_forever()
        """
    )


def test_combined_startup_and_shutdown(tmp_path: Path):
    """Both backend and frontend start, are probed, and shut down cleanly."""
    repo = _write_repo(tmp_path)
    api_script = tmp_path / "api_srv.py"
    api_script.write_text(_dummy_server_script(), encoding="utf-8")
    fe_script = tmp_path / "fe_srv.py"
    fe_script.write_text(_dummy_frontend_script(), encoding="utf-8")

    cfg = _config(repo, start_frontend=True)
    report = stack.run_rehearsal(
        cfg,
        backend_argv_override=_dummy_argv(api_script, cfg.api_host, cfg.api_port),
        frontend_argv_override=_dummy_argv(fe_script, cfg.frontend_host, cfg.frontend_port),
    )

    # At least one plane must have been probed
    assert report["loopback_http_checks"] is True
    # Cleanup must report ports free after exit
    cleanup = report.get("port_cleanup", report.get("cleanup", {}))
    assert cleanup.get("api_port_free") is True
    assert cleanup.get("frontend_port_free") is True
    # Classification must be one of the terminal states (no "not_run" / "unavailable")
    assert report["classification"] in {"passed", "partial", "failed", "timeout"}


def test_combined_api_down_frontend_up(tmp_path: Path):
    """Frontend starts but backend never binds — classification is 'failed' or 'unavailable'."""
    repo = _write_repo(tmp_path)
    # Use /dev/null equivalent: a script that exits immediately without binding
    crash_script = tmp_path / "crash.py"
    crash_script.write_text("import sys; sys.exit(1)\n", encoding="utf-8")
    fe_script = tmp_path / "fe_srv.py"
    fe_script.write_text(_dummy_frontend_script(), encoding="utf-8")

    cfg = _config(repo, start_frontend=True, startup_timeout_s=3.0)
    report = stack.run_rehearsal(
        cfg,
        backend_argv_override=_dummy_argv(crash_script, cfg.api_host, cfg.api_port),
        frontend_argv_override=_dummy_argv(fe_script, cfg.frontend_host, cfg.frontend_port),
    )

    # With backend gone, frontend is never started (startup_error short-circuits)
    assert report["classification"] in {"failed", "unavailable", "timeout"}
    # Ports must be released regardless
    cleanup = report.get("port_cleanup", report.get("cleanup", {}))
    assert cleanup.get("api_port_free") is True


def test_combined_partial_startup_frontend_fail(tmp_path: Path):
    """Backend comes up healthy but frontend immediately exits — classification is 'failed'."""
    repo = _write_repo(tmp_path)
    api_script = tmp_path / "api_srv.py"
    api_script.write_text(_dummy_server_script(), encoding="utf-8")
    # Frontend crashes on startup
    fe_crash = tmp_path / "fe_crash.py"
    fe_crash.write_text("import sys; sys.exit(2)\n", encoding="utf-8")

    cfg = _config(repo, start_frontend=True, startup_timeout_s=3.0)
    report = stack.run_rehearsal(
        cfg,
        backend_argv_override=_dummy_argv(api_script, cfg.api_host, cfg.api_port),
        frontend_argv_override=_dummy_argv(fe_crash, cfg.frontend_host, cfg.frontend_port),
    )

    # Backend started and was probed, frontend did not bind
    assert report["loopback_http_checks"] is True
    assert report["classification"] in {"failed", "partial", "unavailable", "timeout"}
    reason = report.get("reason", "")
    # Reason must mention the frontend plane
    assert "frontend" in reason
    cleanup = report.get("port_cleanup", report.get("cleanup", {}))
    assert cleanup.get("api_port_free") is True


def test_combined_repeated_invocations_clean(tmp_path: Path):
    """Two consecutive combined runs on the same ports both finish cleanly and free ports."""
    repo = _write_repo(tmp_path)
    api_script = tmp_path / "api_srv.py"
    api_script.write_text(_dummy_server_script(), encoding="utf-8")
    fe_script = tmp_path / "fe_srv.py"
    fe_script.write_text(_dummy_frontend_script(), encoding="utf-8")

    cfg = _config(repo, start_frontend=True)

    for invocation in range(2):
        report = stack.run_rehearsal(
            cfg,
            backend_argv_override=_dummy_argv(api_script, cfg.api_host, cfg.api_port),
            frontend_argv_override=_dummy_argv(fe_script, cfg.frontend_host, cfg.frontend_port),
        )
        cleanup = report.get("port_cleanup", report.get("cleanup", {}))
        assert cleanup.get("api_port_free") is True, (
            f"invocation {invocation}: api port not freed, report={report}"
        )
        assert cleanup.get("frontend_port_free") is True, (
            f"invocation {invocation}: frontend port not freed, report={report}"
        )
        assert report["classification"] in {"passed", "partial", "failed", "timeout"}, (
            f"invocation {invocation}: unexpected classification, report={report}"
        )
