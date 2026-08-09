"""Tests for customer onboarding flow."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.onboarding import router as onboarding_router


@pytest.fixture
def client():
    """FastAPI test client with onboarding router."""
    app = FastAPI()
    app.include_router(onboarding_router, prefix="/api/onboarding")
    return TestClient(app)


class TestOnboardingFlow:
    """Test the complete onboarding flow."""

    def test_start_onboarding(self, client):
        """Start a new onboarding session."""
        response = client.post("/api/onboarding/start")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "session_id" in data
        assert data["step"] == 1
        assert data["current_step"] == "Store Setup"

    def test_get_onboarding_step(self, client):
        """Get current step instructions."""
        # Start session
        start = client.post("/api/onboarding/start")
        session_id = start.json()["session_id"]

        # Get step
        response = client.get(f"/api/onboarding/step/{session_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["step"] == 1
        assert data["step_name"] == "Store Setup"
        assert data["progress"]["percent_complete"] == 25

    def test_set_store_info(self, client):
        """Submit store information to move to step 2."""
        start = client.post("/api/onboarding/start")
        session_id = start.json()["session_id"]

        response = client.post(
            "/api/onboarding/step/1/store-info",
            json={
                "session_id": session_id,
                "store_info": {
                    "business_name": "Test Store",
                    "store_type": "shopify",
                    "country": "US",
                    "budget_daily": 100.0,
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["next_step"] == 2
        assert "Welcome, Test Store" in data["message"]

    def test_set_store_info_invalid(self, client):
        """Invalid store info is rejected."""
        start = client.post("/api/onboarding/start")
        session_id = start.json()["session_id"]

        response = client.post(
            "/api/onboarding/step/1/store-info",
            json={
                "session_id": session_id,
                "store_info": {
                    # Missing required fields
                    "business_name": "Test",
                },
            },
        )
        assert response.status_code == 400

    def test_complete_credentials_step(self, client):
        """Move from credentials step to discovery."""
        # Start and setup store (which moves to step 2)
        start = client.post("/api/onboarding/start")
        session_id = start.json()["session_id"]

        response = client.post(
            "/api/onboarding/step/1/store-info",
            json={
                "session_id": session_id,
                "store_info": {
                    "business_name": "Test Store",
                    "store_type": "shopify",
                    "budget_daily": 50.0,
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["next_step"] == 2

        # Now on step 2 (credentials), complete to move to step 3
        response = client.post(f"/api/onboarding/step/{session_id}/complete")
        assert response.status_code == 200
        data = response.json()
        assert data["next_step"] == 3
        assert data["next_step_name"] == "Product Discovery"

    def test_session_not_found(self, client):
        """Non-existent session returns 404."""
        response = client.get("/api/onboarding/step/invalid-session-id")
        assert response.status_code == 404

    def test_step_progression(self, client):
        """Steps must be followed in order."""
        start = client.post("/api/onboarding/start")
        session_id = start.json()["session_id"]

        # Complete step 1 first
        response = client.post(f"/api/onboarding/step/{session_id}/complete")
        assert response.status_code == 200

        # Now on step 2, can advance
        response = client.post(f"/api/onboarding/step/{session_id}/complete")
        assert response.status_code == 200
        assert response.json()["next_step"] == 3

    def test_onboarding_summary(self, client):
        """Get final summary after completing flow."""
        # Start session
        start = client.post("/api/onboarding/start")
        session_id = start.json()["session_id"]

        # Setup store
        client.post(
            "/api/onboarding/step/1/store-info",
            json={
                "session_id": session_id,
                "store_info": {
                    "business_name": "My Test Business",
                    "store_type": "shopify",
                    "budget_daily": 75.0,
                },
            },
        )

        # Get summary
        response = client.get(f"/api/onboarding/step/4/summary/{session_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["completion"]["store_name"] == "My Test Business"
        assert "dashboard_url" in data
        assert "next_steps" in data


class TestOnboardingStepInstructions:
    """Test step instruction retrieval."""

    def test_all_steps_have_instructions(self, client):
        """Each step has complete instructions."""
        start = client.post("/api/onboarding/start")
        session_id = start.json()["session_id"]

        for step in range(1, 5):
            response = client.get(f"/api/onboarding/step/{session_id}")
            assert response.status_code == 200
            data = response.json()
            assert "step_name" in data
            assert "description" in data
            assert "instructions" in data

            # Advance to next step if possible
            if step < 4:
                client.post(f"/api/onboarding/step/{session_id}/complete")
