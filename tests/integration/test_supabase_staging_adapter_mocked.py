from pathlib import Path
from backend.events.adapters.supabase_staging import build_supabase_staging_repository
from backend.events.supabase_event_validation import event_to_supabase_row
from backend.mvp_commerce.events import commerce_mvp_events
from backend.mvp_commerce.runner import run_commerce_mvp_slice

ROOT = Path(__file__).resolve().parents[2]
class Table:
    def __init__(self): self.rows = []
    def upsert(self, row, **kwargs): self.rows.append(row); return self
    def execute(self): return {"data": self.rows}
class Client:
    def __init__(self): self.table_value = Table()
    def table(self, _): return self.table_value

def test_mocked_adapter_receives_canonical_rows():
    run = run_commerce_mvp_slice(query="portable espresso maker", signal_fixture_path=ROOT / "tests/fixtures/commerce_mvp/public_signals.json")
    events = commerce_mvp_events(run); client = Client()
    repo = build_supabase_staging_repository(client=client, environ={"SUPABASE_URL": "https://test", "SUPABASE_SERVICE_ROLE_KEY": "key", "MARKETOS_SUPABASE_CANONICAL_EVENTS": "1"})
    repo.append_many(events)
    assert client.table_value.rows == [event_to_supabase_row(event) for event in events]
