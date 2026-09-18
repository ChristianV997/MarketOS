"""Evidence-truth invariants not yet covered by
``test_commercial_dry_run_replay_integration.py`` (mission
COMMERCIAL-REPLAY-INTEGRATION-V3, section F):

  - an executed-but-failed check must never be silently reported as merely
    "unavailable" (a materially weaker, "we couldn't check" claim);
  - "unavailable" must never be reported as a pass;
  - a supplier catalog listing / fixture supplier evidence must never grant
    order-creation approval.

These reuse the existing canonical authorities (``backend.adapters.coderos_readonly``,
``evaluation.trustos.gate_runner``) rather than inventing a new status
vocabulary or a second gate.
"""
from __future__ import annotations

import stat

from backend.adapters.coderos_readonly import CoderOSAdapterConfig, probe
from evaluation.trustos.gate_runner import evaluate_action


def _executable_script(tmp_path, body: str):
    path = tmp_path / "coderos"
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_missing_executable_is_unavailable_never_a_silent_pass(tmp_path):
    config = CoderOSAdapterConfig(coderos_root=str(tmp_path), mode="probe")
    report = probe(config)
    assert report.probe_result.state == "unavailable"
    assert report.probe_result.state != "available"


def test_executed_failure_nonzero_exit_is_blocked_not_downgraded_to_unavailable(tmp_path):
    _executable_script(tmp_path, "exit 1")
    config = CoderOSAdapterConfig(coderos_root=str(tmp_path), mode="probe")
    report = probe(config)
    # The probe genuinely ran and failed -- this is a stronger, more specific
    # claim than "we could not check at all", and must not be collapsed into
    # the same "unavailable" bucket a missing executable produces above.
    assert report.probe_result.state == "blocked"
    assert report.probe_result.state != "unavailable"
    assert report.probe_result.state != "available"


def test_executed_failure_malformed_output_is_malformed_not_downgraded_to_unavailable(tmp_path):
    _executable_script(tmp_path, "echo 'not json'")
    config = CoderOSAdapterConfig(coderos_root=str(tmp_path), mode="probe")
    report = probe(config)
    assert report.probe_result.state == "malformed"
    assert report.probe_result.state != "unavailable"
    assert report.probe_result.state != "available"


def test_a_clean_successful_probe_is_available_distinct_from_every_failure_state(tmp_path):
    _executable_script(tmp_path, "echo '{}'")
    config = CoderOSAdapterConfig(coderos_root=str(tmp_path), mode="probe")
    report = probe(config)
    assert report.probe_result.state == "available"


def test_supplier_catalog_evidence_never_grants_order_creation_approval():
    # Even a maximally favorable, fully-supplied supplier evidence context
    # must not turn a "create_order" gate check into an allow: a catalog
    # listing (fixture/manual import) is sourcing evidence, not an
    # authorized purchase decision.
    gate = evaluate_action("create_order", context={"provider_registered": True, "credential_reference_exists": True, "approval_recorded": True, "budget_cap_set": True})
    assert gate.decision == "hard_block"
    assert gate.decision != "allow"
