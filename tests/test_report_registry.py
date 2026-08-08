from backend.organization.commercial_report import CommercialReport
from backend.organization.report_registry import ReportRegistry


def report(report_id, workspace="w1", service="product_research", proposal="p1", status="completed", created=1.0):
    return CommercialReport(report_id, workspace, proposal, "", service, "Report", "Summary", status=status, created_at=created)


def test_missing_and_corrupt_registry_are_empty(tmp_path):
    path = tmp_path / "reports.json"
    assert ReportRegistry(path).list_reports() == []
    path.write_text("bad-json", encoding="utf-8")
    assert ReportRegistry(path).list_reports() == []


def test_register_filters_and_latest(tmp_path):
    registry = ReportRegistry(tmp_path / "reports.json")
    registry.register(report("a", created=1)); registry.register(report("b", workspace="w2", service="unit_economics", proposal="p2", status="blocked", created=3))
    assert registry.get("a").report_id == "a"
    assert [item.report_id for item in registry.list_reports(workspace_id="w1")] == ["a"]
    assert registry.list_reports(service_name="unit_economics")[0].report_id == "b"
    assert registry.list_reports(proposal_id="p1")[0].report_id == "a"
    assert registry.list_reports(status="blocked")[0].report_id == "b"
    assert registry.latest().report_id == "b"


def test_blocked_report_round_trip(tmp_path):
    registry = ReportRegistry(tmp_path / "reports.json"); registry.register(report("blocked", status="unavailable"))
    assert ReportRegistry(tmp_path / "reports.json").get("blocked").status == "unavailable"
