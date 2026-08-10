from backend.events.query_models import EventQuery
from backend.events.supabase_query_service import query_supabase_canonical_events

class Query:
    def __init__(self, rows): self.rows = rows
    def select(self, *_): return self
    def eq(self, *_): return self
    def gte(self, *_): return self
    def lte(self, *_): return self
    def order(self, *_ , **__): return self
    def range(self, *_): return self
    def execute(self): return {"data": self.rows}
class Client:
    def __init__(self, rows): self.rows = rows; self.writes = 0
    def table(self, name): assert name == "canonical_events"; return Query(self.rows)

def test_supabase_reader_uses_fake_select_only():
    row = {"event_id":"event-1","workspace_id":"demo","aggregate_type":"signal","aggregate_id":"signal-1","event_type":"public_signal_observed","schema_version":1,"occurred_at":1.0,"causation_id":None,"correlation_id":"c","experiment_id":None,"actor":None,"source":"backend.signals","payload":{},"metadata":{"dry_run":True,"advisory":True}}
    client = Client([row]); report = query_supabase_canonical_events(EventQuery(workspace_id="demo"), client=client)
    assert report["timeline"]["events"][0]["event_id"] == "event-1" and client.writes == 0
