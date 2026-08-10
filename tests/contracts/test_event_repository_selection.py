import pytest
from backend.events.repository import JsonlEventRepository
from backend.events.repository_selection import available_event_repository_targets, select_event_repository

def test_selection_is_explicit(tmp_path):
    assert select_event_repository() is None and "supabase_staging" in available_event_repository_targets()
    assert isinstance(select_event_repository("jsonl", jsonl_path=tmp_path / "events.jsonl"), JsonlEventRepository)
    with pytest.raises(ValueError): select_event_repository("supabase_staging")
