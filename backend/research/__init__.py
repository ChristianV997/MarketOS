from backend.research.trend_store import (
    ResearchMetrics,
    ResearchValidationError,
    TrendRecordStore,
    generate_dedupe_key,
    validate_research_record,
)
from backend.research.ingestion_store import IngestionRunStore
from backend.research.topic_intelligence import normalize_topic, rank_opportunity

__all__ = [
    "ResearchMetrics",
    "ResearchValidationError",
    "TrendRecordStore",
    "generate_dedupe_key",
    "validate_research_record",
    "IngestionRunStore",
    "normalize_topic",
    "rank_opportunity",
]
