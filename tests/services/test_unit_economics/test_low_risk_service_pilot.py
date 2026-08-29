"""Low-risk supervised pilot tests for services.unit_economics.

Offline, deterministic, planning-only coverage for the service pilot lane.
"""
from __future__ import annotations

import math

import backend.core.persistence as pers
import pytest
from backend.workspaces.client_workspace import ClientWorkspace
from services.unit_economics.analyzer import run_unit_economics


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


class TestUnitEconomicsLowRiskPilot:
  def test_valid_deterministic_calculation(self):
      first, env_a = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0, shipping_cost=2.0)
      second, env_b = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0, shipping_cost=2.0)

      assert first.verdict in {"profitable", "breakeven", "loss"}
      assert first.break_even_cac > 0
      assert env_a.status == "completed"
      assert first.deterministic_fingerprint() == second.deterministic_fingerprint()
      assert env_a.experiment_id != env_b.experiment_id

  def test_empty_product_name_is_blocked_without_margin_math(self):
      result, envelope = run_unit_economics("", supplier_cost=10.0, retail_price=40.0)

      assert result.verdict == "invalid_input"
      assert result.base_margin == {}
      assert envelope.status == "blocked"
      assert "product_name must be a non-empty string" in envelope.blocked_reasons

  def test_negative_supplier_cost_is_blocked(self):
      result, envelope = run_unit_economics("Widget", supplier_cost=-1.0, retail_price=40.0)

      assert result.verdict == "invalid_input"
      assert envelope.status == "blocked"
      assert any("supplier_cost" in reason for reason in envelope.blocked_reasons)

  def test_malformed_non_numeric_input_is_blocked(self):
      result, envelope = run_unit_economics("Widget", supplier_cost="10", retail_price=40.0)  # type: ignore[arg-type]

      assert result.verdict == "invalid_input"
      assert envelope.status == "blocked"

  def test_boundary_zero_retail_price_completes_as_loss(self):
      result, envelope = run_unit_economics("Free Sample", supplier_cost=5.0, retail_price=0.0)

      assert envelope.status == "completed"
      assert result.verdict == "loss"

  def test_duplicate_input_produces_distinct_runs_same_fingerprint(self):
      ws = ClientWorkspace(name="pilot-dup")
      first, env_a = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0, workspace=ws)
      second, env_b = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0, workspace=ws)

      assert env_a.experiment_id != env_b.experiment_id
      assert first.deterministic_fingerprint() == second.deterministic_fingerprint()

  def test_stale_or_unavailable_ledger_evidence_degrades_without_execution(self):
      from services.unit_economics.analyzer import from_ledger

      ws = ClientWorkspace(name="pilot-ledger-empty")
      result, envelope = from_ledger(
          "Widget",
          workspace=ws,
          supplier_cost=10.0,
          retail_price=40.0,
      )

      assert envelope.status == "completed"
      assert result.base_margin
      assert result.dry_run is True
      assert envelope.proposed_spend == 0.0
      assert envelope.actual_spend == 0.0

  def test_unsafe_margin_calculator_failure_never_raises(self, monkeypatch):
      def _boom(*_args, **_kwargs):
          raise RuntimeError("boom")

      monkeypatch.setattr("backend.validation.margin_calculator.calculate_margin", _boom)
      result, envelope = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0)

      assert envelope.status == "failed"
      assert result.base_margin == {}

  def test_execution_and_external_mutation_remain_disabled(self):
      result, envelope = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0)

      assert result.dry_run is True
      assert envelope.mode == "dry_run"
      assert envelope.proposed_spend == 0.0
      assert envelope.actual_spend == 0.0
      assert envelope.status == "completed"

  def test_fingerprint_changes_when_inputs_change(self):
      baseline, _ = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0)
      changed, _ = run_unit_economics("Widget", supplier_cost=12.0, retail_price=40.0)

      assert baseline.deterministic_fingerprint() != changed.deterministic_fingerprint()

  def test_nan_input_is_blocked(self):
      result, envelope = run_unit_economics("Widget", supplier_cost=math.nan, retail_price=40.0)

      assert result.verdict == "invalid_input"
      assert envelope.status == "blocked"

  def test_infinite_input_is_blocked(self):
      result, envelope = run_unit_economics("Widget", supplier_cost=math.inf, retail_price=40.0)

      assert result.verdict == "invalid_input"
      assert envelope.status == "blocked"
      assert "supplier_cost must be finite" in result.validation_errors

  def test_boolean_input_is_blocked(self):
      result, envelope = run_unit_economics("Widget", supplier_cost=True, retail_price=40.0)  # type: ignore[arg-type]

      assert result.verdict == "invalid_input"
      assert envelope.status == "blocked"
      assert any("supplier_cost must be numeric" in reason for reason in envelope.blocked_reasons)

  def test_calculator_failure_is_not_reported_as_completed(self, monkeypatch):
      def _boom(*_args, **_kwargs):
          raise RuntimeError("boom")

      monkeypatch.setattr("backend.validation.margin_calculator.calculate_margin", _boom)
      result, envelope = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0)

      assert result.verdict == "calculation_failed"
      assert "base_margin_calculation_failed" in result.calculation_errors
      assert envelope.status == "failed"
      assert envelope.blocked_reasons[0] == "base_margin_calculation_failed"
