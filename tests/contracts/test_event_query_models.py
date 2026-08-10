import pytest
from backend.events.query_models import EventQuery

def test_query_model_bounds_and_serialization():
    assert EventQuery(workspace_id="demo", limit=5).to_dict()["workspace_id"] == "demo"
    with pytest.raises(ValueError): EventQuery(limit=501)
