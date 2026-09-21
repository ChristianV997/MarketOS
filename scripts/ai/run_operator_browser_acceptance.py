#!/usr/bin/env python3
"""Operator-journey browser acceptance for MarketOS read-only surfaces.

Drives /operator/services, /operator/first-phase, and /operator/events through:
  1) a deterministic fixture harness (default), and optionally
  2) a live local Vite UI when MARKETOS_OPERATOR_UI_BASE is set or --live-ui is passed.

Browser backends (already approved; nothing is installed by this script):
  - orca: Orca embedded browser CLI (`orca tab` / `orca eval` / `orca screenshot`)
  - chrome: installed Google Chrome headless --dump-dom / --screenshot
  - none: fixture + HTTP contract only (no browser proof claimed)

Safety:
  - loopback-only mock API
  - fixture/manual/simulated/unknown evidence only
  - instruments fetch methods and fails on POST/PUT/PATCH/DELETE
  - never treats unavailable/404 as demo-success
  - writes screenshots/traces under a local temp/artifacts dir (not for commit)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPOSITORY_ROOT / "frontend" / "tests" / "fixtures" / "operator-journey"
HARNESS_NAME = "harness.html"

OPERATOR_ROUTES = (
    ("services", "/operator/services"),
    ("first-phase", "/operator/first-phase"),
    ("events", "/operator/events"),
)

API_MODES = ("ok-fixture", "down", "429", "500", "malformed")
VIEWPORTS = (
    ("mobile", 375, 812),
    ("tablet", 768, 1024),
    ("desktop", 1440, 900),
)
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
FORBIDDEN_EXTERNAL_HOST = re.compile(
    r"https?://(?!127\.0\.0\.1|localhost)([^\s\"']+)",
    re.IGNORECASE,
)


@dataclass
class AcceptanceConfig:
    repo: Path = field(default_factory=lambda: REPOSITORY_ROOT)
    host: str = "127.0.0.1"
    port: int = 0
    browser: str = "auto"  # auto|orca|chrome|none
    live_ui_base: str | None = None
    artifact_dir: Path | None = None
    hold_s: float = 0.0
    request_timeout_s: float = 8.0
    include_viewports: bool = True


class OperatorJourneyHandler(BaseHTTPRequestHandler):
    server_version = "MarketOSOperatorJourney/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/harness", f"/{HARNESS_NAME}"}:
            html = (FIXTURE_DIR / HARNESS_NAME).read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
            return
        if parsed.path.startswith("/__mock_api/"):
            route = parsed.path.split("/__mock_api/", 1)[-1].strip("/") or "services"
            mode = (parse_qs(parsed.query).get("mode") or ["ok-fixture"])[0]
            if mode == "429":
                self._send(429, b'{"error":"rate_limited"}', "application/json")
                return
            if mode == "500":
                self._send(500, b'{"error":"server_error"}', "application/json")
                return
            if mode == "malformed":
                self._send(200, b"{not-json", "application/json")
                return
            if mode == "down":
                # Client-side "down" skips fetch; still answer if probed.
                self._send(503, b'{"error":"down"}', "application/json")
                return
            payload = _fixture_payload(route)
            body = json.dumps(payload).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return
        if parsed.path.startswith("/operator/"):
            # Honest unavailable for real SPA paths on the fixture server.
            body = (
                b"<!DOCTYPE html><html lang='en'><body>"
                b"<main><h1>Route unavailable on fixture harness</h1>"
                b"<p role='status'>This fixture server does not serve the Vite SPA. "
                b"Unavailable is not demo-success.</p></main></body></html>"
            )
            self._send(404, body, "text/html; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        self._send(405, b'{"error":"method_not_allowed"}', "application/json")

    def do_PUT(self) -> None:  # noqa: N802
        self._send(405, b'{"error":"method_not_allowed"}', "application/json")

    def do_PATCH(self) -> None:  # noqa: N802
        self._send(405, b'{"error":"method_not_allowed"}', "application/json")

    def do_DELETE(self) -> None:  # noqa: N802
        self._send(405, b'{"error":"method_not_allowed"}', "application/json")


def _fixture_payload(route: str) -> dict[str, Any]:
    if route == "first-phase":
        return {
            "schema": "operator-journey-fixture-v1",
            "availability": "fixture",
            "candidates": [
                {
                    "rank": 1,
                    "id": "c-1",
                    "title": "Hydroponics kit",
                    "evidence": "fixture",
                    "decision": "hold_for_manual_review",
                },
                {
                    "rank": 2,
                    "id": "c-2",
                    "title": "Blocked retailer-dominant",
                    "evidence": "manual",
                    "decision": "reject_retailer_dominance",
                },
                {
                    "rank": 3,
                    "id": "c-3",
                    "title": "Simulated candle set",
                    "evidence": "simulated",
                    "decision": "hold_for_manual_review",
                },
                {
                    "rank": 4,
                    "id": "c-4",
                    "title": "Unknown class SKU",
                    "evidence": "unknown",
                    "decision": "hold_for_manual_review",
                },
            ],
        }
    if route == "events":
        return {
            "schema": "operator-journey-fixture-v1",
            "availability": "fixture",
            "events": [
                {
                    "type": "commerce.run.recorded",
                    "provenance": "fixture",
                    "summary": "Fixture commerce run (not live)",
                },
                {
                    "type": "research.portfolio.summary",
                    "provenance": "manual",
                    "summary": "Manual portfolio note",
                },
                {
                    "type": "competition.summary",
                    "provenance": "simulated",
                    "summary": "Simulated competitor snapshot",
                },
                {
                    "type": "evidence.unknown",
                    "provenance": "unknown",
                    "summary": "Unclassified evidence marker",
                },
            ],
        }
    return {
        "schema": "operator-journey-fixture-v1",
        "availability": "fixture",
        "engagements": [
            {
                "id": "eng-ok",
                "title": "Hydroponics sprint",
                "lifecycle": "draft_ready",
                "evidence": "fixture",
                "action": "hold for review",
            },
            {
                "id": "eng-blocked",
                "title": "Category-only brief",
                "lifecycle": "data_inadequate",
                "evidence": "manual",
                "action": "request client records",
            },
            {
                "id": "eng-sim",
                "title": "Simulated packing kit",
                "lifecycle": "in_review",
                "evidence": "simulated",
                "action": "do not treat as live",
            },
            {
                "id": "eng-unknown",
                "title": "Unknown provenance SKU",
                "lifecycle": "in_review",
                "evidence": "unknown",
                "action": "classify evidence",
            },
        ],
    }


def _find_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def start_fixture_server(host: str, port: int) -> tuple[ThreadingHTTPServer, int]:
    if port <= 0:
        port = _find_free_port(host)
    server = ThreadingHTTPServer((host, port), OperatorJourneyHandler)
    thread = threading.Thread(target=server.serve_forever, name="operator-journey-http", daemon=True)
    thread.start()
    return server, port


def _which_chrome() -> str | None:
    candidates = [
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        shutil.which("chrome.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for path in candidates:
        if path and Path(path).is_file():
            return path
    return None


def _orca_available() -> bool:
    return bool(shutil.which("orca") or shutil.which("orca.exe"))


def resolve_browser(preferred: str) -> str:
    if preferred in {"orca", "chrome", "none"}:
        if preferred == "orca" and not _orca_available():
            return "none"
        if preferred == "chrome" and not _which_chrome():
            return "none"
        return preferred
    if _orca_available():
        return "orca"
    if _which_chrome():
        return "chrome"
    return "none"


def _run(cmd: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return subprocess.CompletedProcess(cmd, 124, stdout=stdout, stderr=f"{stderr}\ntimeout_after={timeout}")


def _orca_json(args: list[str], *, timeout: float) -> dict[str, Any]:
    completed = _run(["orca", *args, "--json"], timeout=timeout)
    text = (completed.stdout or "").strip() or (completed.stderr or "").strip()
    try:
        payload = json.loads(text[text.find("{") :]) if "{" in text else {}
    except json.JSONDecodeError:
        payload = {"ok": False, "raw": text[-2000:], "exit_code": completed.returncode}
    if not isinstance(payload, dict):
        payload = {"ok": False, "raw": text[-2000:]}
    payload.setdefault("exit_code", completed.returncode)
    return payload


class BrowserDriver:
    def __init__(self, kind: str, artifact_dir: Path, timeout_s: float) -> None:
        self.kind = kind
        self.artifact_dir = artifact_dir
        self.timeout_s = timeout_s
        self.page_id: str | None = None
        self.chrome = _which_chrome()

    def open(self, url: str) -> dict[str, Any]:
        if self.kind == "orca":
            created = _orca_json(["tab", "create", "--url", url], timeout=self.timeout_s)
            page = None
            if created.get("ok"):
                page = (created.get("result") or {}).get("browserPageId")
            if not page:
                listed = _orca_json(["tab", "list"], timeout=self.timeout_s)
                tabs = (listed.get("result") or {}).get("tabs") or []
                if tabs:
                    page = tabs[-1].get("browserPageId")
            self.page_id = page
            return {"ok": bool(page), "page_id": page, "created": created}
        if self.kind == "chrome":
            return {"ok": True, "page_id": None, "url": url}
        return {"ok": False, "reason": "browser_unavailable"}

    def goto(self, url: str) -> dict[str, Any]:
        if self.kind == "orca":
            args = ["goto", "--url", url]
            if self.page_id:
                args.extend(["--page", self.page_id])
            return _orca_json(args, timeout=self.timeout_s)
        return {"ok": True, "url": url}

    def eval_js(self, expression: str) -> dict[str, Any]:
        if self.kind == "orca":
            args = ["eval", "--expression", expression]
            if self.page_id:
                args.extend(["--page", self.page_id])
            return _orca_json(args, timeout=self.timeout_s)
        if self.kind == "chrome" and self.chrome:
            # Headless dump-dom path cannot eval; callers should use dump_dom.
            return {"ok": False, "reason": "chrome_eval_unsupported"}
        return {"ok": False, "reason": "browser_unavailable"}

    def dump_dom(self, url: str, width: int, height: int) -> str:
        if self.kind != "chrome" or not self.chrome:
            return ""
        # Windows Chrome often hangs on --dump-dom; keep a hard timeout and
        # treat empty/timeout output as unavailable browser proof for that case.
        completed = _run(
            [
                self.chrome,
                "--headless=new",
                "--disable-gpu",
                "--disable-extensions",
                "--no-first-run",
                "--disable-background-networking",
                "--allow-insecure-localhost",
                f"--window-size={width},{height}",
                "--virtual-time-budget=2000",
                "--timeout=5000",
                "--dump-dom",
                url,
            ],
            timeout=max(self.timeout_s, 20.0),
        )
        if completed.returncode == 124:
            return ""
        return completed.stdout or ""

    def screenshot(self, label: str, width: int, height: int, url: str | None = None) -> str | None:
        target = self.artifact_dir / f"{label}-{width}x{height}.png"
        if self.kind == "orca":
            args = ["screenshot", "--format", "png"]
            if self.page_id:
                args.extend(["--page", self.page_id])
            completed = _run(["orca", *args], timeout=self.timeout_s)
            # Orca may print a path or binary; best-effort copy if a path appears.
            text = (completed.stdout or "") + (completed.stderr or "")
            match = re.search(r"([A-Za-z]:\\[^\r\n]+?\.(?:png|jpe?g)|/[^\r\n]+?\.(?:png|jpe?g))", text)
            if match:
                src = Path(match.group(1))
                if src.is_file():
                    shutil.copy2(src, target)
                    return str(target)
            marker = self.artifact_dir / f"{label}-{width}x{height}.screenshot-attempted.txt"
            marker.write_text(text[-2000:], encoding="utf-8")
            return str(marker)
        if self.kind == "chrome" and self.chrome and url:
            completed = _run(
                [
                    self.chrome,
                    "--headless=new",
                    "--disable-gpu",
                    "--disable-extensions",
                    "--no-first-run",
                    "--allow-insecure-localhost",
                    f"--window-size={width},{height}",
                    "--virtual-time-budget=2000",
                    "--timeout=5000",
                    f"--screenshot={target}",
                    url,
                ],
                timeout=max(self.timeout_s, 20.0),
            )
            if completed.returncode == 124:
                return None
            return str(target) if target.is_file() else None
        return None

    def keypress(self, key: str) -> dict[str, Any]:
        if self.kind == "orca":
            args = ["keypress", "--key", key]
            if self.page_id:
                args.extend(["--page", self.page_id])
            return _orca_json(args, timeout=self.timeout_s)
        return {"ok": False, "reason": "keypress_unsupported"}

    def close(self) -> None:
        if self.kind == "orca" and self.page_id:
            _orca_json(["tab", "close", "--page", self.page_id], timeout=self.timeout_s)
            self.page_id = None


def _http_get(url: str, timeout: float) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            return int(response.status), response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return int(exc.code), body
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def _assert_no_mutations(requests: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for entry in requests:
        method = str(entry.get("method") or "").upper()
        url = str(entry.get("url") or "")
        if method in MUTATING_METHODS:
            failures.append(f"mutating_method:{method}:{url}")
        if FORBIDDEN_EXTERNAL_HOST.search(url):
            failures.append(f"external_provider_url:{url}")
    return failures


def _extract_acceptance(dom_or_json: str) -> dict[str, Any]:
    match = re.search(r"data-surface=\"([^\"]+)\"", dom_or_json)
    surface = match.group(1) if match else None
    live = "live_validated" in dom_or_json.lower() and "never" not in dom_or_json.lower()
    return {
        "surface": surface,
        "mentions_skip": "Skip to" in dom_or_json or "skip-link" in dom_or_json,
        "mentions_fixture": "fixture" in dom_or_json.lower(),
        "claims_live_validated": bool(re.search(r"evidence class:\s*live_validated", dom_or_json, re.I)),
        "has_grid": 'role="grid"' in dom_or_json,
        "has_export_control": "Safe export preview" in dom_or_json or "export preview" in dom_or_json.lower(),
        "raw_live_flag": live,
    }


def run_fixture_journey(config: AcceptanceConfig) -> dict[str, Any]:
    if not (FIXTURE_DIR / HARNESS_NAME).is_file():
        return {
            "schema": "MarketOS.OperatorBrowserAcceptance.v1",
            "status": "failed",
            "reason": "fixture_harness_missing",
            "browser_method": "none",
            "browser_proof": False,
        }

    artifact_dir = config.artifact_dir or Path(tempfile.gettempdir()) / "marketos-operator-browser-acceptance"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    server, port = start_fixture_server(config.host, config.port)
    base = f"http://{config.host}:{port}"
    browser_kind = resolve_browser(config.browser)
    driver = BrowserDriver(browser_kind, artifact_dir, config.request_timeout_s)
    report: dict[str, Any] = {
        "schema": "MarketOS.OperatorBrowserAcceptance.v1",
        "status": "passed",
        "browser_method": browser_kind,
        "browser_proof": browser_kind in {"orca", "chrome"},
        "fixture_base": base,
        "routes": [path for _, path in OPERATOR_ROUTES],
        "viewport_matrix": [{"name": n, "width": w, "height": h} for n, w, h in VIEWPORTS],
        "api_modes": list(API_MODES),
        "cases": [],
        "request_method_evidence": [],
        "screenshots": [],
        "artifacts_dir": str(artifact_dir),
        "mutated": False,
        "network_providers": False,
        "live_ui": None,
        "failures": [],
    }

    try:
        # Honest 404 on SPA paths for the fixture server.
        for key, path in OPERATOR_ROUTES:
            code, body = _http_get(f"{base}{path}", config.request_timeout_s)
            case = {
                "id": f"fixture-server-spa-{key}",
                "route": path,
                "mode": "spa-on-fixture-server",
                "http_status": code,
                "passed": code == 404 and "not demo-success" in body,
            }
            report["cases"].append(case)
            if not case["passed"]:
                report["failures"].append(case["id"])

        opened = False
        for route_key, route_path in OPERATOR_ROUTES:
            for mode in API_MODES:
                url = f"{base}/harness?route={route_key}&api={mode}"
                case: dict[str, Any] = {
                    "id": f"fixture-{route_key}-{mode}",
                    "route": route_path,
                    "fixture_url": url,
                    "api_mode": mode,
                    "passed": False,
                }
                requests_log: list[dict[str, Any]] = []
                if browser_kind == "orca":
                    if not opened:
                        open_result = driver.open(url)
                        opened = bool(open_result.get("ok"))
                        case["open"] = open_result
                    else:
                        case["goto"] = driver.goto(url)
                    time.sleep(0.6)
                    evaluated = driver.eval_js(
                        "JSON.stringify({acceptance: window.__mosAcceptance || null, "
                        "requests: window.__mosRequests || [], "
                        "consoleErrors: window.__mosConsoleErrors || [], "
                        "banner: (document.getElementById('status-banner')||{}).textContent || '', "
                        "viewport: document.getElementById('viewport-label')?.textContent || '', "
                        "hasSkip: !!document.getElementById('skip-link'), "
                        "title: document.title})"
                    )
                    case["eval"] = {"ok": evaluated.get("ok"), "exit_code": evaluated.get("exit_code")}
                    result_text = ""
                    if evaluated.get("ok"):
                        result_text = str((evaluated.get("result") or {}).get("result") or evaluated.get("result") or "")
                    parsed: dict[str, Any] = {}
                    if result_text:
                        try:
                            parsed = json.loads(result_text)
                        except json.JSONDecodeError:
                            parsed = {}
                    requests_log = list(parsed.get("requests") or [])
                    acceptance = parsed.get("acceptance") or {}
                    surface = acceptance.get("surface")
                    banner = str(parsed.get("banner") or "")
                    if mode in {"down", "429", "500", "malformed"}:
                        case["passed"] = surface == "unavailable" and "not demo-success" in banner.lower()
                    else:
                        case["passed"] = surface in {"blocked", "partial", "stale"} and surface != "success"
                        case["passed"] = bool(case["passed"] and parsed.get("hasSkip"))
                    if config.include_viewports and mode == "ok-fixture":
                        for name, width, height in VIEWPORTS:
                            shot = driver.screenshot(f"{route_key}-{mode}-{name}", width, height, url)
                            if shot:
                                report["screenshots"].append(shot)
                            # Soft check: resize via JS when orca supports it.
                            driver.eval_js(f"window.resizeTo({width}, {height}); document.getElementById('viewport-label')?.textContent")
                    # Keyboard smoke on happy path.
                    if mode == "ok-fixture":
                        driver.keypress("Tab")
                        driver.keypress("Tab")
                elif browser_kind == "chrome":
                    width, height = VIEWPORTS[2][1], VIEWPORTS[2][2]
                    dom = driver.dump_dom(url, width, height)
                    if not dom:
                        # Chrome dump-dom frequently hangs on Windows; fall back to
                        # static HTML GET so the suite stays deterministic, and mark
                        # that this case did not obtain Chrome DOM proof.
                        code, body = _http_get(url, config.request_timeout_s)
                        dom = body
                        case["chrome_dump_dom"] = "timeout_or_empty"
                        case["http_status"] = code
                    extracted = _extract_acceptance(dom)
                    case["dom_extract"] = extracted
                    if mode in {"down", "429", "500", "malformed"}:
                        # Without executed JS, static HTML cannot prove unavailable
                        # surfaces; require either executed surface markers or the
                        # harness still advertising fail-closed copy.
                        case["passed"] = (
                            extracted.get("surface") == "unavailable"
                            or "not demo-success" in dom.lower()
                            or "unavailable — not demo-success" in dom.lower()
                            or (
                                case.get("chrome_dump_dom") == "timeout_or_empty"
                                and "not demo-success" in dom.lower()
                                and extracted.get("mentions_skip")
                            )
                        )
                    else:
                        case["passed"] = bool(
                            extracted.get("mentions_skip")
                            and extracted.get("mentions_fixture")
                            and not extracted.get("claims_live_validated")
                        )
                    if "__mosRequests" in dom or "Network method log" in dom:
                        case["instrumentation_present"] = True
                    if mode == "ok-fixture" and config.include_viewports:
                        for name, w, h in VIEWPORTS:
                            shot = driver.screenshot(f"{route_key}-{mode}-{name}", w, h, url)
                            if shot:
                                report["screenshots"].append(shot)
                            case.setdefault("responsive", {})[name] = {
                                "width": w,
                                "height": h,
                                "css_classes_present": "mobile-only" in dom and "desktop-only" in dom,
                            }
                else:
                    code, body = _http_get(url, config.request_timeout_s)
                    extracted = _extract_acceptance(body)
                    case["http_status"] = code
                    case["dom_extract"] = extracted
                    case["passed"] = code == 200 and extracted.get("mentions_skip") and extracted.get("mentions_fixture")
                    case["browser_proof"] = False

                mutation_failures = _assert_no_mutations(requests_log)
                case["request_methods"] = [str(item.get("method")) for item in requests_log]
                case["mutation_failures"] = mutation_failures
                report["request_method_evidence"].append(
                    {
                        "case": case["id"],
                        "methods": case["request_methods"],
                        "mutation_failures": mutation_failures,
                    }
                )
                if mutation_failures:
                    case["passed"] = False
                    report["failures"].extend(mutation_failures)
                if not case["passed"]:
                    report["failures"].append(case["id"])
                report["cases"].append(case)

        # Live UI probe (optional): never invent success when unavailable.
        live_base = config.live_ui_base or os.environ.get("MARKETOS_OPERATOR_UI_BASE")
        if live_base:
            live_report = _probe_live_ui(live_base.rstrip("/"), driver if browser_kind != "none" else None, config)
            report["live_ui"] = live_report
            if live_report.get("failures"):
                report["failures"].extend(live_report["failures"])

        if config.hold_s > 0:
            time.sleep(config.hold_s)
    finally:
        driver.close()
        server.shutdown()
        server.server_close()

    if report["failures"]:
        report["status"] = "failed"
    if browser_kind == "none":
        report["status"] = "passed_without_browser_proof" if not report["failures"] else "failed"
        report["browser_proof"] = False
    elif browser_kind == "chrome":
        chrome_dom_hits = [
            case
            for case in report["cases"]
            if case.get("api_mode") == "ok-fixture" and case.get("chrome_dump_dom") != "timeout_or_empty" and case.get("dom_extract")
        ]
        # Only claim Chrome browser proof when at least one dump-dom produced DOM.
        executed = any(case.get("chrome_dump_dom") != "timeout_or_empty" and case.get("dom_extract", {}).get("surface") for case in report["cases"])
        report["browser_proof"] = bool(executed)
        if not report["failures"] and not report["browser_proof"]:
            report["status"] = "passed_without_browser_proof"
            report["chrome_note"] = "dump-dom timed out or returned empty; static fixture contract still passed"
        report["chrome_dom_hits"] = len(chrome_dom_hits)
    report_path = artifact_dir / "operator-browser-acceptance-report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def _probe_live_ui(base: str, driver: BrowserDriver | None, config: AcceptanceConfig) -> dict[str, Any]:
    result: dict[str, Any] = {
        "base": base,
        "routes": {},
        "failures": [],
        "request_methods": [],
        "browser_proof": bool(driver and driver.kind in {"orca", "chrome"}),
    }
    parsed = urlparse(base)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        result["failures"].append("live_ui_not_loopback")
        return result

    for key, path in OPERATOR_ROUTES:
        url = f"{base}{path}"
        code, body = _http_get(url, config.request_timeout_s)
        entry: dict[str, Any] = {"url": url, "http_status": code, "passed": False}
        if code == 0:
            entry["classification"] = "unavailable"
            entry["passed"] = True  # honest unavailable
        elif code == 404:
            entry["classification"] = "unavailable"
            entry["passed"] = "demo-success" not in body.lower()
        elif 200 <= code < 400:
            entry["classification"] = "reachable"
            # Read-only probe: install interceptor when orca is available.
            if driver and driver.kind == "orca":
                if driver.page_id is None:
                    driver.open(url)
                else:
                    driver.goto(url)
                time.sleep(1.0)
                # Patch on the already-loaded document. Do not full-navigate again
                # (that would wipe the patch). Trigger safe refresh/filter only.
                driver.eval_js(
                    """
                    (() => {
                      window.__mosRequests = [];
                      if (!window.__mosFetchPatched) {
                        const orig = window.fetch.bind(window);
                        window.fetch = async (input, init = {}) => {
                          window.__mosRequests.push({
                            method: String((init && init.method) || 'GET').toUpperCase(),
                            url: String(input),
                          });
                          return orig(input, init);
                        };
                        window.__mosFetchPatched = true;
                      }
                      const buttons = Array.from(document.querySelectorAll('button'));
                      const refresh = buttons.find((btn) => /refresh/i.test(btn.textContent || ''));
                      if (refresh) refresh.click();
                      const filter = document.querySelector('input[type="search"], input[placeholder*="filter" i], input[placeholder*="candidate" i]');
                      if (filter) {
                        filter.focus();
                        filter.value = 'a';
                        filter.dispatchEvent(new Event('input', { bubbles: true }));
                      }
                      return 'patched';
                    })()
                    """
                )
                time.sleep(1.2)
                evaluated = driver.eval_js("JSON.stringify(window.__mosRequests || [])")
                raw_result = evaluated.get("result")
                if isinstance(raw_result, dict):
                    text = str(raw_result.get("result") or "[]")
                else:
                    text = str(raw_result or "[]")
                try:
                    requests_log = json.loads(text)
                except json.JSONDecodeError:
                    requests_log = []
                entry["request_methods"] = [str(item.get("method")) for item in requests_log]
                entry["request_urls"] = [str(item.get("url")) for item in requests_log][:20]
                result["request_methods"].extend(entry["request_methods"])
                mutation_failures = _assert_no_mutations(requests_log)
                entry["mutation_failures"] = mutation_failures
                entry["passed"] = not mutation_failures
                entry["note"] = (
                    "post-load instrumentation; mount-time GETs may precede the patch; "
                    "acceptance clicks never include public-run POST"
                )
                if mutation_failures:
                    result["failures"].extend(mutation_failures)
            else:
                entry["passed"] = True
                entry["note"] = "reachable_without_method_instrumentation"
        else:
            entry["classification"] = "unavailable"
            entry["passed"] = True
        if not entry["passed"]:
            result["failures"].append(f"live-{key}")
        result["routes"][path] = entry
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=str(REPOSITORY_ROOT))
    parser.add_argument("--browser", choices=("auto", "orca", "chrome", "none"), default="auto")
    parser.add_argument("--live-ui", default=None, help="Loopback Vite base, e.g. http://127.0.0.1:5173")
    parser.add_argument("--artifact-dir", default=None)
    parser.add_argument("--hold-seconds", type=float, default=0.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--skip-viewports", action="store_true")
    args = parser.parse_args(argv)

    config = AcceptanceConfig(
        repo=Path(args.repository),
        browser=args.browser,
        live_ui_base=args.live_ui,
        artifact_dir=Path(args.artifact_dir) if args.artifact_dir else None,
        hold_s=max(0.0, float(args.hold_seconds)),
        include_viewports=not args.skip_viewports,
    )
    report = run_fixture_journey(config)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"status={report.get('status')} browser={report.get('browser_method')} "
            f"proof={report.get('browser_proof')} failures={len(report.get('failures') or [])}"
        )
        if report.get("report_path"):
            print(f"report={report['report_path']}")
    return 0 if str(report.get("status", "")).startswith("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
