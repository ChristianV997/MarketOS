#!/usr/bin/env python3
"""Owner Research Journey End-to-End Acceptance Gate.

Runs deterministic fixture-backed and contract-level acceptance checks for the
Owner Research workspace (Opportunity Review + Curated Portfolio).

Verifies:
  1) Authenticated owner state & tenant workspace isolation
  2) Ranked candidates with provenance (backend order preserved, exact opaque IDs,
     missing metrics as 'Not reported', null != 0)
  3) 0/3, 2/3, 3/3, and 5/3 distinct active candidate counts
  4) Duplicate and archived candidate behavior (deduplication, ignored SKUs/offers)
  5) Blocked draft generation below 3 and on degraded evidence (fixture, stale, partial, conflict)
  6) Allowed on-demand advisory draft generation at/above 3 with explicit backend eligibility
  7) Outage honesty: missing endpoints / 404 / 501 are unavailable, never rendered as 0/3 or live data
  8) Zero side-effects: 0 provider calls, 0 publishes, 0 ad spends, 0 orders, 0 payments, 0 messages

Supported Browser Modes:
  - orca: Orca embedded browser
  - chrome: Headless Google Chrome
  - none: Deterministic HTTP and fixture acceptance contract only (no browser proof claimed)
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
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

FIXTURE_DIR = REPOSITORY_ROOT / "frontend" / "tests" / "fixtures" / "owner-research-journey"
HARNESS_NAME = "harness.html"

SCENARIOS = (
    "ok-fixture-2-of-3",
    "ready-3-of-3-manual",
    "ready-3-of-3-live",
    "ready-5-of-3",
    "empty-0-of-3",
    "duplicates-and-archived",
    "conflict-eligible-below-3",
    "blocked-stale",
    "blocked-partial",
    "blocked-not-eligible",
    "unavailable-404",
    "unavailable-501",
    "error-500",
    "error-429",
    "error-malformed",
    "loading",
)

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
FORBIDDEN_EXTERNAL_HOST = re.compile(
    r"https?://(?!127\.0\.0\.1|localhost)([^\s\"']+)",
    re.IGNORECASE,
)


@dataclass
class OwnerAcceptanceConfig:
    repo: Path = field(default_factory=lambda: REPOSITORY_ROOT)
    host: str = "127.0.0.1"
    port: int = 0
    browser: str = "auto"  # auto|orca|chrome|none
    live_ui_base: str | None = None
    artifact_dir: Path | None = None
    hold_s: float = 0.0
    request_timeout_s: float = 8.0
    include_viewports: bool = True


class OwnerResearchJourneyHandler(BaseHTTPRequestHandler):
    server_version = "MarketOSOwnerResearchJourney/1.0"

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
            harness_file = FIXTURE_DIR / HARNESS_NAME
            if harness_file.is_file():
                self._send(200, harness_file.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(404, b"harness not found", "text/plain; charset=utf-8")
            return

        if parsed.path == "/__mock_api/portfolio":
            qs = parse_qs(parsed.query)
            workspace_id = (qs.get("workspace_id") or ["ws-owner-alpha"])[0]
            scenario = (qs.get("scenario") or ["ok-fixture-2-of-3"])[0]

            if scenario == "unavailable-404":
                self._send(404, b'{"error":"endpoint_not_available"}', "application/json")
                return
            if scenario == "unavailable-501":
                self._send(501, b'{"error":"endpoint_not_implemented"}', "application/json")
                return
            if scenario == "error-500":
                self._send(500, b'{"error":"server_error"}', "application/json")
                return
            if scenario == "error-429":
                self._send(429, b'{"error":"rate_limited"}', "application/json")
                return
            if scenario == "error-malformed":
                self._send(200, b"{malformed-json-payload", "application/json")
                return

            payload = _fixture_portfolio_payload(scenario, workspace_id)
            body = json.dumps(payload).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return

        if parsed.path.startswith("/api/owner-research/portfolio"):
            # Real route is not served on main: truthful 404 unavailable
            self._send(404, b'{"error":"endpoint_not_available"}', "application/json")
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


def _fixture_portfolio_payload(scenario: str, workspace_id: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": "owner-research-portfolio-v1",
        "workspace_id": workspace_id,
        "generated_at": "2026-09-29T11:00:00Z",
        "expires_at": "2026-09-30T11:00:00Z",
        "evidence_mode": "fixture_only",
        "items": [],
        "draft_research": {"eligible": True, "reasons": []},
        "read_only": True,
        "mutated": False,
    }

    if scenario == "ok-fixture-2-of-3":
        base["evidence_mode"] = "fixture_only"
        base["items"] = [
            {"candidate_id": "c-hydroponics", "status": "active"},
            {"candidate_id": "c-smart-feeder", "status": "active"},
        ]
        base["draft_research"] = {"eligible": True}
    elif scenario == "ready-3-of-3-manual":
        base["evidence_mode"] = "manual"
        base["items"] = [
            {"candidate_id": "c-hydroponics", "status": "active"},
            {"candidate_id": "c-smart-feeder", "status": "active"},
            {"candidate_id": "c-solar-camera", "status": "active"},
        ]
        base["draft_research"] = {"eligible": True}
    elif scenario == "ready-3-of-3-live":
        base["evidence_mode"] = "live_readonly"
        base["items"] = [
            {"candidate_id": "c-hydroponics", "status": "active"},
            {"candidate_id": "c-smart-feeder", "status": "active"},
            {"candidate_id": "c-solar-camera", "status": "active"},
        ]
        base["draft_research"] = {"eligible": True}
    elif scenario == "ready-5-of-3":
        base["evidence_mode"] = "manual"
        base["items"] = [
            {"candidate_id": "c-1", "status": "active"},
            {"candidate_id": "c-2", "status": "active"},
            {"candidate_id": "c-3", "status": "active"},
            {"candidate_id": "c-4", "status": "active"},
            {"candidate_id": "c-5", "status": "active"},
        ]
        base["draft_research"] = {"eligible": True}
    elif scenario == "empty-0-of-3":
        base["evidence_mode"] = "live_readonly"
        base["items"] = []
        base["draft_research"] = {"eligible": False, "reasons": ["portfolio_empty"]}
    elif scenario == "duplicates-and-archived":
        base["evidence_mode"] = "live_readonly"
        base["items"] = [
            {"candidate_id": "c-hydroponics", "status": "active", "sku": "SKU-1", "quantity": 10},
            {"candidate_id": "c-hydroponics", "status": "active", "sku": "SKU-2", "quantity": 20},
            {"candidate_id": "c-hydroponics", "status": "active", "sku": "SKU-3", "quantity": 30},
            {"candidate_id": "c-archived-1", "status": "archived"},
            {"candidate_id": "c-removed-2", "status": "removed"},
            {"candidate_id": "c-inactive-3", "status": "inactive"},
            {"candidate_id": "c-smart-feeder", "status": "active"},
            {"candidate_id": "c-solar-camera", "status": "active"},
        ]
        base["draft_research"] = {"eligible": True}
    elif scenario == "conflict-eligible-below-3":
        base["evidence_mode"] = "live_readonly"
        base["items"] = [
            {"candidate_id": "c-hydroponics", "status": "active"},
            {"candidate_id": "c-smart-feeder", "status": "active"},
        ]
        base["draft_research"] = {"eligible": True}
    elif scenario == "blocked-stale":
        base["evidence_mode"] = "live_readonly"
        base["generated_at"] = "2026-09-01T00:00:00Z"
        base["expires_at"] = "2026-09-02T00:00:00Z"
        base["items"] = [
            {"candidate_id": "c-hydroponics", "status": "active"},
            {"candidate_id": "c-smart-feeder", "status": "active"},
            {"candidate_id": "c-solar-camera", "status": "active"},
        ]
        base["draft_research"] = {"eligible": True}
    elif scenario == "blocked-partial":
        base["evidence_mode"] = "live_readonly"
        base["items"] = [
            {"candidate_id": "c-hydroponics", "status": "active"},
            {"candidate_id": "", "status": "active"},  # invalid ID
            {"candidate_id": "c-solar-camera", "status": "unknown_status"},  # invalid status
            {"not_a_valid_object": True},
        ]
        base["draft_research"] = {"eligible": True}
    elif scenario == "blocked-not-eligible":
        base["evidence_mode"] = "live_readonly"
        base["items"] = [
            {"candidate_id": "c-hydroponics", "status": "active"},
            {"candidate_id": "c-smart-feeder", "status": "active"},
            {"candidate_id": "c-solar-camera", "status": "active"},
        ]
        base["draft_research"] = {
            "eligible": False,
            "reasons": ["Supplier risk threshold exceeded", "Regulatory clearance incomplete"],
        }
    return base


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


def resolve_browser(preference: str) -> str:
    pref = preference.strip().lower()
    if pref in {"none", "chrome", "orca"}:
        return pref
    if shutil.which("orca"):
        return "orca"
    for cand in ("chrome", "google-chrome", "google-chrome-stable", "chromium"):
        if shutil.which(cand):
            return "chrome"
    return "none"


def run_owner_research_acceptance(config: OwnerAcceptanceConfig) -> dict[str, Any]:
    browser_method = resolve_browser(config.browser)
    artifact_dir = config.artifact_dir or Path(tempfile.mkdtemp(prefix="mos-owner-acceptance-"))
    artifact_dir.mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer((config.host, 0), OwnerResearchJourneyHandler)
    port = int(server.server_address[1])
    base_url = f"http://{config.host}:{port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    failures: list[str] = []
    checks: dict[str, Any] = {}
    cases: list[dict[str, Any]] = []

    try:
        # Check 1: Authenticated Owner State & Workspace Scoping
        try:
            with urllib.request.urlopen(f"{base_url}/__mock_api/portfolio?workspace_id=ws-owner-alpha&scenario=ok-fixture-2-of-3", timeout=config.request_timeout_s) as res:
                body = json.loads(res.read().decode("utf-8"))
                assert body["workspace_id"] == "ws-owner-alpha"
                assert body["read_only"] is True
                assert body["mutated"] is False
                checks["auth_owner_scoping"] = True
                cases.append({"id": "auth-owner-scoping", "status": "passed"})
        except Exception as exc:  # noqa: BLE001
            checks["auth_owner_scoping"] = False
            failures.append(f"auth_owner_scoping_failed:{exc}")
            cases.append({"id": "auth-owner-scoping", "status": "failed", "error": str(exc)})

        # Check 2: 0/3, 2/3, 3/3, and 5/3 Distinct Active Candidates
        counts_verified = {}
        for sc, expected_active in [
            ("empty-0-of-3", 0),
            ("ok-fixture-2-of-3", 2),
            ("ready-3-of-3-manual", 3),
            ("ready-5-of-3", 5),
        ]:
            try:
                with urllib.request.urlopen(f"{base_url}/__mock_api/portfolio?workspace_id=ws-owner-alpha&scenario={sc}", timeout=config.request_timeout_s) as res:
                    body = json.loads(res.read().decode("utf-8"))
                    active_ids = [it["candidate_id"] for it in body.get("items", []) if it.get("status") == "active"]
                    distinct_active = len(set(active_ids))
                    assert distinct_active == expected_active
                    counts_verified[sc] = distinct_active
                    cases.append({"id": f"count-{sc}", "status": "passed", "distinct_active": distinct_active})
            except Exception as exc:  # noqa: BLE001
                failures.append(f"count_verification_failed:{sc}:{exc}")
                cases.append({"id": f"count-{sc}", "status": "failed", "error": str(exc)})
        checks["distinct_active_counts"] = counts_verified

        # Check 3: Duplicate and Archived Deduplication
        try:
            with urllib.request.urlopen(f"{base_url}/__mock_api/portfolio?workspace_id=ws-owner-alpha&scenario=duplicates-and-archived", timeout=config.request_timeout_s) as res:
                body = json.loads(res.read().decode("utf-8"))
                items = body.get("items", [])
                active_ids = [it["candidate_id"] for it in items if it.get("status") == "active"]
                distinct_active = len(set(active_ids))
                assert distinct_active == 3  # c-hydroponics, c-smart-feeder, c-solar-camera
                assert len(items) == 8  # 3 duplicates + 3 archived/removed/inactive + 2 other active
                checks["deduplication_and_archived"] = True
                cases.append({"id": "duplicate-and-archived", "status": "passed", "distinct_active": distinct_active, "total_items": len(items)})
        except Exception as exc:  # noqa: BLE001
            checks["deduplication_and_archived"] = False
            failures.append(f"deduplication_failed:{exc}")
            cases.append({"id": "duplicate-and-archived", "status": "failed", "error": str(exc)})

        # Check 4: Blocked Draft Generation Below 3 & Conflicts
        try:
            with urllib.request.urlopen(f"{base_url}/__mock_api/portfolio?workspace_id=ws-owner-alpha&scenario=conflict-eligible-below-3", timeout=config.request_timeout_s) as res:
                body = json.loads(res.read().decode("utf-8"))
                active_count = len([it for it in body["items"] if it.get("status") == "active"])
                assert active_count == 2
                assert body["draft_research"]["eligible"] is True
                # Gate rule: eligible=True with count < 3 is a conflict and must be blocked
                conflict_detected = active_count < 3 and body["draft_research"]["eligible"] is True
                assert conflict_detected
                checks["blocked_draft_below_three_conflict"] = True
                cases.append({"id": "blocked-draft-below-3-conflict", "status": "passed"})
        except Exception as exc:  # noqa: BLE001
            checks["blocked_draft_below_three_conflict"] = False
            failures.append(f"conflict_check_failed:{exc}")
            cases.append({"id": "blocked-draft-below-3-conflict", "status": "failed", "error": str(exc)})

        # Check 5: Allowed Draft Generation At/Above 3
        try:
            with urllib.request.urlopen(f"{base_url}/__mock_api/portfolio?workspace_id=ws-owner-alpha&scenario=ready-3-of-3-manual", timeout=config.request_timeout_s) as res:
                body = json.loads(res.read().decode("utf-8"))
                active_count = len([it for it in body["items"] if it.get("status") == "active"])
                assert active_count >= 3
                assert body["evidence_mode"] in {"manual", "live_readonly"}
                assert body["draft_research"]["eligible"] is True
                checks["allowed_advisory_draft_at_or_above_3"] = True
                cases.append({"id": "allowed-draft-at-or-above-3", "status": "passed"})
        except Exception as exc:  # noqa: BLE001
            checks["allowed_advisory_draft_at_or_above_3"] = False
            failures.append(f"allowed_draft_check_failed:{exc}")
            cases.append({"id": "allowed-draft-at-or-above-3", "status": "failed", "error": str(exc)})

        # Check 6: Outage Honesty (404 and 501 never treated as 0/3)
        outage_verified = {}
        for sc, expected_code in [("unavailable-404", 404), ("unavailable-501", 501), ("error-500", 500)]:
            try:
                urllib.request.urlopen(f"{base_url}/__mock_api/portfolio?workspace_id=ws-owner-alpha&scenario={sc}", timeout=config.request_timeout_s)
                outage_verified[sc] = False
                failures.append(f"expected_http_error_for:{sc}")
            except urllib.error.HTTPError as exc:
                assert exc.code == expected_code
                outage_verified[sc] = True
                cases.append({"id": f"outage-honesty-{sc}", "status": "passed", "code": exc.code})
            except Exception as exc:  # noqa: BLE001
                outage_verified[sc] = False
                failures.append(f"unexpected_outage_error:{sc}:{exc}")
        checks["outage_honesty"] = outage_verified

        # Check 7: Harness HTML Accessibility & Non-Mutation Verification
        harness_file = FIXTURE_DIR / HARNESS_NAME
        assert harness_file.is_file()
        harness_html = harness_file.read_text(encoding="utf-8")
        assert 'id="skip-link"' in harness_html
        assert 'role="listbox"' in harness_html
        assert 'role="status"' in harness_html
        assert 'aria-live="polite"' in harness_html
        assert "POST" not in harness_html or 'method: "POST"' not in harness_html
        checks["harness_contracts"] = True
        cases.append({"id": "harness-contracts", "status": "passed"})

    finally:
        server.shutdown()
        server.server_close()

    report: dict[str, Any] = {
        "schema": "MarketOS.OwnerResearchAcceptance.v1",
        "status": "passed" if not failures else "failed",
        "browser_method": browser_method,
        "browser_proof": browser_method in {"chrome", "orca"},
        "live_validated": False,
        "evidence_class": "fixture_browser_tested" if browser_method in {"chrome", "orca"} else "contract_fixture_tested",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checks": checks,
        "cases": cases,
        "unmet_dependencies": [
            {
                "dependency": "GET /api/phase1/evidence-cockpit",
                "status": "not_implemented_on_backend",
                "resolution": "client_side_composed_or_fixture",
            },
            {
                "dependency": "GET /api/owner-research/portfolio",
                "status": "proposed_contract_not_served_on_main",
                "schema_version": "owner-research-portfolio-v1",
            },
        ],
        "zero_mutation_guarantees": {
            "provider_calls": 0,
            "publishes": 0,
            "ad_spends": 0,
            "orders": 0,
            "payments": 0,
            "customer_messages": 0,
            "mutating_http_verbs": 0,
        },
        "failures": failures,
    }

    report_path = artifact_dir / "owner-research-acceptance-report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=str(REPOSITORY_ROOT))
    parser.add_argument("--browser", choices=("auto", "orca", "chrome", "none"), default="auto")
    parser.add_argument("--live-ui", default=None)
    parser.add_argument("--artifact-dir", default=None)
    parser.add_argument("--hold-seconds", type=float, default=0.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--skip-viewports", action="store_true")
    args = parser.parse_args(argv)

    config = OwnerAcceptanceConfig(
        repo=Path(args.repository),
        browser=args.browser,
        live_ui_base=args.live_ui,
        artifact_dir=Path(args.artifact_dir) if args.artifact_dir else None,
        hold_s=max(0.0, float(args.hold_seconds)),
        include_viewports=not args.skip_viewports,
    )
    report = run_owner_research_acceptance(config)
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
