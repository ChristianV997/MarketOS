from backend.research.trend_store import (
    ResearchMetrics,
    ResearchValidationError,
    TrendRecordStore,
    generate_dedupe_key,
    validate_research_record,
)
from backend.research.ingestion_store import IngestionRunStore
from backend.research.topic_intelligence import normalize_topic, rank_opportunity
from backend.research.credentials import CredentialLoadStatus, credential_status, load_research_credentials
from backend.research.readiness import SOURCE_SPECS, all_source_readiness, source_readiness
from backend.research.swarm import (
    EvidenceEnvelope,
    EvidenceRecord,
    SwarmJobSpec,
    SwarmJobStore,
    SwarmRunner,
    SwarmValidationError,
    canonical_json,
    register_swarm_job,
    sha256_json,
    swarm_readiness,
)
from backend.research.swarm_adapters import (
    AgentReachSensorAdapter,
    DeerFlowRuntimeAdapter,
    HermesRuntimeAdapter,
    SidecarAdapterError,
    benchmark_runtimes,
    build_default_swarm_runtimes,
)

__all__ = [
    "ResearchMetrics",
    "ResearchValidationError",
    "TrendRecordStore",
    "generate_dedupe_key",
    "validate_research_record",
    "IngestionRunStore",
    "normalize_topic",
    "rank_opportunity",
    "CredentialLoadStatus",
    "credential_status",
    "load_research_credentials",
    "SOURCE_SPECS",
    "all_source_readiness",
    "source_readiness",
    "EvidenceEnvelope",
    "EvidenceRecord",
    "SwarmJobSpec",
    "SwarmJobStore",
    "SwarmRunner",
    "SwarmValidationError",
    "canonical_json",
    "register_swarm_job",
    "sha256_json",
    "swarm_readiness",
    "AgentReachSensorAdapter",
    "DeerFlowRuntimeAdapter",
    "HermesRuntimeAdapter",
    "SidecarAdapterError",
    "benchmark_runtimes",
    "build_default_swarm_runtimes",
]
