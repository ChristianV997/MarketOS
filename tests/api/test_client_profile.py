from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.organization import router as organization_router
from backend.security.principal import (
    ClerkTokenVerifier,
    PrincipalVerificationError,
    VerifiedPrincipal,
    get_principal_verifier,
)
from backend.security.workspace_access import get_workspace_repository
from backend.workspaces.postgres_repository import PostgresWorkspaceRepository, WorkspaceAccessDenied


class _UniqueConstraintViolation(RuntimeError):
    code = "23505"


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.filters = []
        self.limit_value = None
        self.upsert_row = None
        self.insert_row = None
        self.update_row = None
        self.conflict = None

    def select(self, _columns):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def upsert(self, row, on_conflict=None):
        self.upsert_row = dict(row)
        self.conflict = on_conflict
        return self

    def insert(self, row):
        self.insert_row = dict(row)
        return self

    def update(self, row):
        self.update_row = dict(row)
        return self

    def execute(self):
        rows = self.client.rows.setdefault(self.table, [])
        if self.insert_row is not None:
            if any(row.get("workspace_id") == self.insert_row.get("workspace_id") for row in rows):
                raise _UniqueConstraintViolation("duplicate workspace profile")
            rows.append(dict(self.insert_row))
            return {"data": [dict(self.insert_row)]}
        if self.update_row is not None:
            updated = []
            for row in rows:
                if all(row.get(field) == value for field, value in self.filters):
                    row.update(self.update_row)
                    updated.append(dict(row))
            return {"data": updated}
        if self.upsert_row is not None:
            key = self.conflict or "workspace_id"
            rows[:] = [row for row in rows if row.get(key) != self.upsert_row.get(key)]
            rows.append(dict(self.upsert_row))
            return {"data": [dict(self.upsert_row)]}
        selected = [
            dict(row)
            for row in rows
            if all(row.get(field) == value for field, value in self.filters)
        ]
        if self.limit_value is not None:
            selected = selected[: self.limit_value]
        return {"data": selected}


class _MemoryPostgres:
    def __init__(self):
        self.rows = {
            "workspace_memberships": [
                {"workspace_id": "ws-owner", "principal_id": "operator-1", "role": "owner"},
                {"workspace_id": "ws-client", "principal_id": "operator-1", "role": "operator"},
                {"workspace_id": "ws-other", "principal_id": "operator-2", "role": "operator"},
                {"workspace_id": "ws-owner", "principal_id": "internal-operator", "role": "operator"},
                {"workspace_id": "ws-client", "principal_id": "viewer-1", "role": "viewer"},
            ],
            "workspaces": [
                {"workspace_id": "ws-owner", "name": "Internal", "metadata": {"workspace_type": "internal"}},
                {"workspace_id": "ws-client", "name": "Client A", "metadata": {"workspace_type": "client_service"}},
                {"workspace_id": "ws-other", "name": "Client B", "metadata": {"workspace_type": "client_service"}},
            ],
            "workspace_profiles": [],
            "owner_portfolios": [],
        }

    def table(self, name):
        return _Query(self, name)


def _profile_row(workspace_id, company_name):
    return {
        "workspace_id": workspace_id,
        "company_name": company_name,
        "business_type": "Retail",
        "segments": ["Outdoor"],
        "markets": ["US"],
        "products_services": [],
        "social_accounts": [{"platform": "instagram", "handle": "@clienta"}],
        "metadata": {},
    }


class OperatorWorkspaceResolverTests(unittest.TestCase):
    def test_operator_profile_scope_uses_the_server_membership_role(self):
        repository = PostgresWorkspaceRepository(client=_MemoryPostgres())

        workspace = repository.resolve_operator_workspace(VerifiedPrincipal("operator-1"))

        self.assertEqual(workspace.workspace_id, "ws-client")
        self.assertEqual(workspace.workspace_type, "client_service")

    def test_profile_repository_round_trips_with_server_resolved_operator_scope(self):
        client = _MemoryPostgres()
        repository = PostgresWorkspaceRepository(client=client)
        principal = VerifiedPrincipal("operator-1")
        profile = {
            "company_name": "Client A",
            "business_type": "Retail",
            "segments": ["Outdoor"],
            "markets": ["US"],
            "products_services": [],
            "social_accounts": [{"platform": "instagram", "handle": "@clienta", "connection_status": "unconnected"}],
            "metadata": {},
        }

        saved = repository.upsert_operator_client_profile(principal, profile)
        reloaded = PostgresWorkspaceRepository(client=client).get_operator_client_profile(principal)

        self.assertEqual(saved.workspace_id, "ws-client")
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.company_name, "Client A")
        self.assertEqual(reloaded.social_accounts[0]["connection_status"], "unconnected")

    def test_non_operator_membership_cannot_read_operator_profile(self):
        repository = PostgresWorkspaceRepository(client=_MemoryPostgres())

        with self.assertRaises(WorkspaceAccessDenied):
            repository.get_operator_client_profile(VerifiedPrincipal("viewer-1"))

    def test_multiple_operator_workspaces_fail_closed_without_a_request_selector(self):
        client = _MemoryPostgres()
        client.rows["workspace_memberships"].extend(
            [
                {"workspace_id": "ws-client", "principal_id": "multi-operator", "role": "operator"},
                {"workspace_id": "ws-other", "principal_id": "multi-operator", "role": "operator"},
            ]
        )

        with self.assertRaises(WorkspaceAccessDenied):
            PostgresWorkspaceRepository(client=client).resolve_operator_workspace(
                VerifiedPrincipal("multi-operator")
            )


class ClientProfileApiTests(unittest.TestCase):
    def setUp(self):
        self.storage = _MemoryPostgres()
        app = FastAPI()
        app.include_router(organization_router)
        app.dependency_overrides[get_principal_verifier] = lambda: ClerkTokenVerifier(
            lambda token: {"sub": token}
        )
        app.dependency_overrides[get_workspace_repository] = lambda: PostgresWorkspaceRepository(
            client=self.storage
        )
        self.client = TestClient(app)

    def test_profile_route_requires_authentication(self):
        response = self.client.get("/api/organization/client-profile")

        self.assertEqual(response.status_code, 401)

    def test_operator_cannot_access_profile_through_another_membership_role(self):
        response = self.client.get(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer viewer-1"},
        )

        self.assertEqual(response.status_code, 403)

    def test_client_supplied_workspace_id_is_rejected(self):
        attempts = [
            self.client.get(
                "/api/organization/client-profile?workspace_id=ws-owner",
                headers={"Authorization": "Bearer operator-1"},
            ),
            self.client.get(
                "/api/organization/client-profile",
                headers={"Authorization": "Bearer operator-1", "x-workspace-id": "ws-owner"},
            ),
        ]

        self.assertEqual([response.status_code for response in attempts], [400, 400])

    def test_create_rejects_workspace_selectors_in_query_or_header(self):
        attempts = [
            self.client.post(
                "/api/organization/client-profile?workspace_id=ws-other",
                headers={"Authorization": "Bearer operator-1"},
                json={"company_name": "Client Org"},
            ),
            self.client.post(
                "/api/organization/client-profile",
                headers={"Authorization": "Bearer operator-1", "x-marketos-workspace-id": "ws-other"},
                json={"company_name": "Client Org"},
            ),
            self.client.post(
                "/api/organization/client-profile",
                headers={"Authorization": "Bearer operator-1"},
                json={"company_name": "Client Org", "workspace_id": "ws-other"},
            ),
        ]

        self.assertEqual([response.status_code for response in attempts], [400, 400, 422])
        self.assertEqual(self.storage.rows["workspace_profiles"], [])

    def test_get_reads_only_the_operator_role_workspace(self):
        self.storage.rows["workspace_profiles"] = [
            _profile_row("ws-owner", "Internal Org"),
            _profile_row("ws-client", "Client Org"),
        ]

        response = self.client.get(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer operator-1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["company_name"], "Client Org")
        self.assertNotIn("workspace_id", response.json())
        self.assertNotIn("metadata", response.json())
        self.assertEqual(response.json()["social_accounts"][0]["connection_status"], "unconnected")

    def test_get_missing_profile_returns_not_found(self):
        response = self.client.get(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer operator-1"},
        )

        self.assertEqual(response.status_code, 404)

    def test_operator_cannot_resolve_an_internal_own_brand_workspace(self):
        response = self.client.get(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer internal-operator"},
        )

        self.assertEqual(response.status_code, 403)

    def test_each_operator_reads_only_its_server_resolved_client_profile(self):
        self.storage.rows["workspace_profiles"] = [
            _profile_row("ws-client", "Client A CRM"),
            _profile_row("ws-other", "Client B CRM"),
        ]

        response = self.client.get(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer operator-2"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["company_name"], "Client B CRM")
        self.assertNotIn("workspace_id", response.json())

    def test_create_profile_persists_bounded_client_crm_fields(self):
        self.storage.rows["owner_portfolios"] = [
            {"portfolio_id": "owner-brand", "workspace_id": "ws-owner", "title": "Owner brand", "payload": {"brand": "Owner"}}
        ]
        owner_portfolios_before = [dict(row) for row in self.storage.rows["owner_portfolios"]]
        body = {
            "company_name": "Client Org",
            "business_type": "Direct-to-consumer outdoor retail",
            "segments": ["Hikers", "Campers"],
            "target_markets": ["United States", "Canada"],
            "products_services": [
                {"name": "Trail Pack", "kind": "product", "category": "Packs"},
                {"name": "Brand Audit", "kind": "service"},
            ],
            "social_accounts": [{"platform": "instagram", "handle": "@clienta"}],
        }

        response = self.client.post(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer operator-1"},
            json=body,
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["company_name"], "Client Org")
        self.assertEqual(response.json()["target_markets"], ["United States", "Canada"])
        self.assertEqual(response.json()["social_accounts"][0]["connection_status"], "unconnected")
        self.assertNotIn("workspace_id", response.json())
        self.assertNotIn("metadata", response.json())
        self.assertEqual(self.storage.rows["workspace_profiles"][0]["workspace_id"], "ws-client")
        self.assertEqual(self.storage.rows["workspace_profiles"][0]["markets"], ["United States", "Canada"])
        self.assertEqual(self.storage.rows["owner_portfolios"], owner_portfolios_before)

    def test_create_can_start_with_only_required_company_name(self):
        response = self.client.post(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer operator-1"},
            json={"company_name": "New Client"},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["company_name"], "New Client")
        self.assertIsNone(response.json()["business_type"])
        self.assertEqual(response.json()["segments"], [])
        self.assertEqual(response.json()["target_markets"], [])

    def test_create_does_not_overwrite_an_existing_client_profile(self):
        self.storage.rows["workspace_profiles"] = [_profile_row("ws-client", "Existing Client")]

        response = self.client.post(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer operator-1"},
            json={"company_name": "Replacement Client"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.storage.rows["workspace_profiles"][0]["company_name"], "Existing Client")

    def test_create_requires_authentication(self):
        response = self.client.post(
            "/api/organization/client-profile",
            json={"company_name": "Client Org"},
        )

        self.assertEqual(response.status_code, 401)

    def test_ambiguous_operator_roles_fail_closed(self):
        self.storage.rows["workspace_memberships"].extend(
            [
                {"workspace_id": "ws-client", "principal_id": "conflicted-operator", "role": "operator"},
                {"workspace_id": "ws-client", "principal_id": "conflicted-operator", "role": "reader"},
            ]
        )

        response = self.client.get(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer conflicted-operator"},
        )

        self.assertEqual(response.status_code, 403)

    def test_patch_missing_profile_returns_not_found_instead_of_creating(self):
        response = self.client.patch(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer operator-1"},
            json={"company_name": "Client Org"},
        )

        self.assertEqual(response.status_code, 404)

    def test_patch_unauthenticated_requests_return_401(self):
        response = self.client.patch(
            "/api/organization/client-profile",
            json={"company_name": "Client Org", "business_type": "Retail"},
        )

        self.assertEqual(response.status_code, 401)

    def test_invalid_bearer_token_returns_401(self):
        def reject_token(_token):
            raise PrincipalVerificationError("invalid token")

        app = FastAPI()
        app.include_router(organization_router)
        app.dependency_overrides[get_principal_verifier] = lambda: ClerkTokenVerifier(reject_token)

        response = TestClient(app).get(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer invalid"},
        )

        self.assertEqual(response.status_code, 401)

    def test_patch_validates_fields_and_rejects_credentials_or_connected_accounts(self):
        invalid_bodies = [
            {"company_name": "", "business_type": "Retail"},
            {
                "company_name": "Client Org",
                "social_accounts": [{"platform": "instagram", "handle": "@clienta", "connection_status": "connected"}],
            },
            {
                "company_name": "Client Org",
                "social_accounts": [{"platform": "instagram", "handle": "@clienta", "access_token": "test-value"}],
            },
            {"company_name": "Client Org", "business_type": "Retail", "workspace_id": "ws-owner"},
            {"company_name": "Client Org", "business_type": "Retail", "products_services": [{"name": "Pouch", "kind": "product", "inventory_quantity": -1}]},
            {"company_name": "Client Org", "social_accounts": [{"platform": "instagram", "handle": "@clienta", "provider_payload": {"raw": "value"}}]},
            {"company_name": "Client Org", "segments": ["Segment"] * 33},
            {"company_name": "C" * 121},
            {},
        ]
        for body in invalid_bodies:
            with self.subTest(body=body):
                response = self.client.patch(
                    "/api/organization/client-profile",
                    headers={"Authorization": "Bearer operator-1"},
                    json=body,
                )
                self.assertEqual(response.status_code, 422)

    def test_patch_persists_and_reloads_profile_without_touching_other_workspace(self):
        self.storage.rows["workspace_profiles"] = [
            _profile_row("ws-owner", "Internal Org"),
            _profile_row("ws-client", "Client Draft"),
            _profile_row("ws-other", "Other Client"),
        ]
        self.storage.rows["owner_portfolios"] = [
            {"portfolio_id": "owner-brand", "workspace_id": "ws-owner", "title": "Owner brand", "payload": {"brand": "Owner"}}
        ]
        owner_portfolios_before = [dict(row) for row in self.storage.rows["owner_portfolios"]]
        body = {
            "company_name": "Client Org",
            "business_type": "Retail",
            "segments": ["Outdoor"],
            "target_markets": ["US"],
            "products_services": [
                {"name": "Trail Pack", "kind": "product", "category": "Packs"},
                {"name": "Brand Audit", "kind": "service"},
            ],
            "social_accounts": [{"platform": "instagram", "handle": "@clienta"}],
        }

        saved = self.client.patch(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer operator-1"},
            json=body,
        )
        reloaded = self.client.get(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer operator-1"},
        )

        self.assertEqual(saved.status_code, 200)
        self.assertEqual(reloaded.status_code, 200)
        self.assertEqual(reloaded.json()["products_services"][0]["name"], "Trail Pack")
        self.assertEqual(reloaded.json()["social_accounts"][0]["connection_status"], "unconnected")
        self.assertEqual(reloaded.json()["target_markets"], ["US"])
        self.assertEqual(self.storage.rows["workspace_profiles"][0]["company_name"], "Internal Org")
        self.assertEqual(self.storage.rows["workspace_profiles"][1]["company_name"], "Client Org")
        self.assertEqual(self.storage.rows["workspace_profiles"][2]["company_name"], "Other Client")
        self.assertEqual(self.storage.rows["owner_portfolios"], owner_portfolios_before)

        partial = self.client.patch(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer operator-1"},
            json={"target_markets": ["Canada"]},
        )
        reloaded_after_partial = self.client.get(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer operator-1"},
        )
        self.assertEqual(partial.status_code, 200)
        self.assertEqual(reloaded_after_partial.json()["company_name"], "Client Org")
        self.assertEqual(reloaded_after_partial.json()["target_markets"], ["Canada"])

    def test_trustos_rejects_unsafe_input_and_does_not_persist_it(self):
        self.storage.rows["workspace_profiles"] = [_profile_row("ws-client", "Client Org")]
        response = self.client.patch(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer operator-1"},
            json={"company_name": "internal prompt placeholder", "business_type": "Retail"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.storage.rows["workspace_profiles"][0]["company_name"], "Client Org")

    def test_trustos_rejects_credential_shaped_social_metadata(self):
        self.storage.rows["workspace_profiles"] = [_profile_row("ws-client", "Client Org")]
        original_social = list(self.storage.rows["workspace_profiles"][0]["social_accounts"])

        response = self.client.patch(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer operator-1"},
            json={"social_accounts": [{"platform": "instagram", "handle": "credential-placeholder"}]},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.storage.rows["workspace_profiles"][0]["social_accounts"], original_social)

    def test_trustos_rejects_unsafe_stored_output_without_reflecting_it(self):
        self.storage.rows["workspace_profiles"] = [
            _profile_row("ws-client", "internal prompt placeholder"),
        ]

        response = self.client.get(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer operator-1"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertNotIn("internal prompt placeholder", response.text)

    def test_default_authentication_dependency_fails_closed(self):
        app = FastAPI()
        app.include_router(organization_router)

        response = TestClient(app).get(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer test-token"},
        )

        self.assertEqual(response.status_code, 503)

    def test_unconfigured_database_fails_closed_without_a_file_fallback(self):
        app = FastAPI()
        app.include_router(organization_router)
        app.dependency_overrides[get_principal_verifier] = lambda: ClerkTokenVerifier(
            lambda token: {"sub": token}
        )
        app.dependency_overrides[get_workspace_repository] = lambda: PostgresWorkspaceRepository(
            url="", key=""
        )

        response = TestClient(app).get(
            "/api/organization/client-profile",
            headers={"Authorization": "Bearer operator-1"},
        )

        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()