from backend.organization.agent_role import AgentRole
from backend.organization.department import Department
from backend.organization.org_registry import OrganizationRegistry


def test_registry_round_trip_and_corrupt_file(tmp_path):
    path = tmp_path / "org.json"
    registry = OrganizationRegistry(path)
    department = registry.register_department(Department(name="Product"))
    role = registry.register_agent(AgentRole(name="Researcher", department_id=department.department_id, permissions=["read"]))
    loaded = OrganizationRegistry(path)
    assert loaded.get_department(department.department_id).name == "Product"
    assert loaded.get_agent(role.agent_id).can("read")
    path.write_text("{bad", encoding="utf-8")
    assert OrganizationRegistry(path).list_agents() == []


def test_default_departments_bootstrap(tmp_path):
    registry = OrganizationRegistry(tmp_path / "org.json")
    result = registry.bootstrap_defaults()
    assert result["departments"] == 9
    assert registry.get_department("product") is not None
    assert registry.agents_for_department("product")
