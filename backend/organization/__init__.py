"""Governed agentic-company organization primitives."""

from .agent_role import AgentRole
from .department import Department, default_departments
from .org_registry import OrganizationRegistry, get_organization_registry

__all__ = ["AgentRole", "Department", "OrganizationRegistry", "default_departments", "get_organization_registry"]
