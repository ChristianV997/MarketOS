"""Tests for services.sales_automation.simulate."""
import backend.core.persistence as pers
import pytest
from backend.workspaces.artifact_store import ArtifactStore
from services.sales_automation.schemas import AppointmentHandoff, ChatSession
from services.sales_automation.simulate import run_sales_bot_simulation, run_simulated_conversation


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


class TestRunSimulatedConversation:
    def test_drives_scripted_messages_through_the_flow(self):
        session = run_simulated_conversation("real_estate", [
            "I'm looking to buy a house in Austin", "asap, budget is $500,000",
        ])
        assert isinstance(session, ChatSession)
        assert session.slots.intent == "buying"

    def test_stops_early_once_handed_off(self):
        session = run_simulated_conversation("clinic_wellness", [
            "I have a problem, this is broken",
            "this message should never be processed",
        ])
        lead_turns = [t for t in session.turns if t.speaker == "lead"]
        assert len(lead_turns) == 1


class TestRunSalesBotSimulation:
    def test_returns_all_four_outputs_with_completed_envelope(self):
        session, handoff, flow, envelope = run_sales_bot_simulation(
            "real_estate", ["I'm looking to buy a house in Austin", "asap, budget is $500,000"],
        )
        assert isinstance(session, ChatSession)
        assert isinstance(handoff, AppointmentHandoff)
        assert flow
        assert envelope.service_name == "sales_automation"
        assert envelope.status == "completed"
        assert envelope.outputs["real_handoff"] is None
        assert envelope.outputs["commercial_status"] in {"needs_credentials", "ready_for_client_service"}

    def test_saved_to_artifact_store(self):
        _, _, _, envelope = run_sales_bot_simulation("ecommerce_brand", ["hi"])
        store = ArtifactStore()
        saved = store.load(envelope.workspace_id, envelope.experiment_id, "result.json")
        assert "session" in saved and "handoff" in saved

    def test_explicit_attempt_without_configured_chatwoot_stays_simulation_only(self):
        _, _, _, envelope = run_sales_bot_simulation(
            "car_sales", ["hi"], attempt_real_handoff=True,
        )
        assert envelope.outputs["real_handoff"] is None
