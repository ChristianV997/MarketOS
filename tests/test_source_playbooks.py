import pytest
from backend.discovery.csv_ingestion import SUPPORTED_PARSERS
from backend.discovery.source_playbooks import get_source_playbook


def test_all_supported_parsers_have_actionable_playbooks():
    for parser in sorted(SUPPORTED_PARSERS - {"local_json_dataset"}):
        item = get_source_playbook(parser)
        assert item["required_fields"] and item["verification_checks"] and item["invalid_claims"]
        assert item["parser_type"] == parser


def test_unknown_playbook_fails_safely():
    with pytest.raises(ValueError): get_source_playbook("unknown")
