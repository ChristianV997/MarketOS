"""Static contracts: no fallbacks, no secrets handling, no second workspace authority."""
from __future__ import annotations

from pathlib import Path

from backend.identity import repository
from backend.workspaces.client_workspace import WORKSPACE_TYPES as DOMAIN_WORKSPACE_TYPES

PACKAGE = Path(repository.__file__).resolve().parent
SOURCES = {path.name: path.read_text(encoding="utf-8") for path in PACKAGE.glob("*.py")}

FORBIDDEN = [
    "import sqlite3",
    "sqlite3.connect",
    "os.environ",
    "getenv(",
    "open(",
    "write_text",
    "save_json_atomic",
    "state_path",
    "load_json",
    "backend.workspaces",
    "api.routes",
    ".env",
]


def test_package_has_no_file_fallback_env_reads_or_json_write_through():
    hits = [(name, pattern) for name, text in SOURCES.items() for pattern in FORBIDDEN if pattern in text]
    assert hits == []


def test_workspace_type_vocabulary_is_a_subset_of_the_existing_domain_model():
    assert set(repository.WORKSPACE_TYPES) <= set(DOMAIN_WORKSPACE_TYPES)
    assert repository.OWNER_TYPE == "internal" and repository.CLIENT_TYPE == "client_service"


def test_evidence_labels_cannot_claim_live_or_measured_evidence():
    assert not {"live", "measured", "live_sales_validated", "live_order_verified"} & set(repository.EVIDENCE_LABELS)
