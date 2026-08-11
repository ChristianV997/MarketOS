"""Knowledge-source contracts for a future company brain; no indexing."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

SOURCE_TYPES = frozenset({"internal_doc", "client_doc", "commerce_report", "launch_draft", "site_draft", "accounting_record", "sales_record", "policy_doc", "web_research", "manual_import", "vector_index"})


@dataclass(frozen=True)
class KnowledgeSource:
    source_id: str
    name: str
    source_type: str
    department_owner: str
    access_level: str
    freshness_policy: str
    citation_required: bool
    allowed_agents: tuple[str, ...]
    forbidden_agents: tuple[str, ...]
    retention_policy: str
    privacy_classification: str


@dataclass(frozen=True)
class KnowledgeCollection:
    collection_id: str
    name: str
    source_ids: tuple[str, ...]
    retrieval_profile_id: str
    indexing_status: str


@dataclass(frozen=True)
class RetrievalProfile:
    profile_id: str
    top_k: int
    rerank: bool
    citation_required: bool
    filters: tuple[str, ...]


@dataclass(frozen=True)
class EmbeddingPolicy:
    policy_id: str
    provider_candidate: str
    model_candidate: str
    pii_allowed: bool
    network_required: bool


@dataclass(frozen=True)
class CitationPolicy:
    policy_id: str
    required_for_types: tuple[str, ...]
    missing_citation_action: str


@dataclass(frozen=True)
class AccessPolicy:
    policy_id: str
    allowed_departments: tuple[str, ...]
    denied_classes: tuple[str, ...]
    human_approval_required: bool


@dataclass(frozen=True)
class KnowledgeFreshnessPolicy:
    policy_id: str
    max_age: str
    stale_action: str
    manual_review: bool


@dataclass(frozen=True)
class DepartmentMemoryScope:
    department: str
    allowed_collection_ids: tuple[str, ...]
    forbidden_source_types: tuple[str, ...]
    citation_mode: str


@dataclass(frozen=True)
class KnowledgeRegistryReport:
    report_version: str
    generated_at: str
    sources: tuple[KnowledgeSource, ...]
    collections: tuple[KnowledgeCollection, ...]
    retrieval_profiles: tuple[RetrievalProfile, ...]
    embedding_policies: tuple[EmbeddingPolicy, ...]
    citation_policies: tuple[CitationPolicy, ...]
    access_policies: tuple[AccessPolicy, ...]
    freshness_policies: tuple[KnowledgeFreshnessPolicy, ...]
    department_scopes: tuple[DepartmentMemoryScope, ...]
    indexing_performed: bool
    policy: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_knowledge_registry(*, generated_at: str = "offline-deterministic", seed: Mapping[str, Any] | None = None) -> KnowledgeRegistryReport:
    specs = (("companyos-docs", "CompanyOS documentation", "internal_doc", "management", "internal"), ("commerce-reports", "Commerce evidence reports", "commerce_report", "intelligence", "internal"), ("launch-drafts", "Launch draft packages", "launch_draft", "launch", "internal"), ("site-drafts", "Website/store/funnel drafts", "site_draft", "website_store_funnel", "internal"), ("accounting-seeds", "Accounting ledger seeds", "accounting_record", "accounting", "confidential"), ("sales-seeds", "Sales pipeline seeds", "sales_record", "sales", "confidential"), ("policy-docs", "Policy documents", "policy_doc", "risk_approval", "confidential"))
    sources = tuple(KnowledgeSource(source_id, name, source_type, department, "department", "review_on_change", source_type not in {"internal_doc"}, (f"{department}-manager",), ("external_action_agent",), "retain_per_policy", privacy) for source_id, name, source_type, department, privacy in specs)
    profile = RetrievalProfile("companyos-cited-retrieval", 5, False, True, ("department", "privacy_classification", "freshness"))
    collection = KnowledgeCollection("companyos-knowledge", "CompanyOS knowledge", tuple(item.source_id for item in sources), profile.profile_id, "not_indexed")
    scopes = tuple(DepartmentMemoryScope(department, (collection.collection_id,), ("client_doc",) if department not in {"sales", "management"} else (), "citation_required") for department in ("management", "finance", "accounting", "sales", "intelligence", "supplier", "launch", "website_store_funnel", "risk_approval"))
    return KnowledgeRegistryReport("companyos-knowledge-registry-v1", generated_at, sources, (collection,), (profile,), (EmbeddingPolicy("no-indexing-yet", "supabase_pgvector_or_local", "TBD", False, False),), (CitationPolicy("companyos-citation", ("commerce_report", "launch_draft", "site_draft", "accounting_record", "sales_record", "policy_doc"), "mark unavailable and request source"),), (AccessPolicy("companyos-access", ("management", "finance", "accounting", "sales", "intelligence", "supplier", "launch", "website_store_funnel", "risk_approval"), ("private_unapproved", "secret",), True),), (KnowledgeFreshnessPolicy("companyos-freshness", "review_on_change", "warn_and_degrade", True),), scopes, False, "Schema only. No documents are indexed, embedded, retrieved, or exported.")


__all__ = ["SOURCE_TYPES", "KnowledgeSource", "KnowledgeCollection", "RetrievalProfile", "EmbeddingPolicy", "CitationPolicy", "AccessPolicy", "KnowledgeFreshnessPolicy", "DepartmentMemoryScope", "KnowledgeRegistryReport", "build_knowledge_registry"]
