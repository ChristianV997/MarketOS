from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .commercial_report import CommercialReport
from .portfolio_report import PortfolioReport


class ReportRegistry:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path or os.getenv("MARKETOS_REPORT_STATE", "state/report_registry.json"))
        self.reports: dict[str, CommercialReport] = {}
        self.portfolio_reports: dict[str, PortfolioReport] = {}
        self._lock = threading.RLock()
        self.load()

    def register(self, report: CommercialReport) -> CommercialReport:
        with self._lock:
            self.reports[report.report_id] = report
            self.save()
        return report

    def get(self, report_id: str) -> CommercialReport | None: return self.reports.get(report_id)

    def list_reports(self, workspace_id: str | None = None, service_name: str | None = None,
                     proposal_id: str | None = None, experiment_id: str | None = None,
                     status: str | None = None, limit: int = 50) -> list[CommercialReport]:
        limit = max(0, min(int(limit), 500))
        items = [report for report in self.reports.values()
                 if (workspace_id is None or report.workspace_id == workspace_id)
                 and (service_name is None or report.service_name == service_name)
                 and (proposal_id is None or report.proposal_id == proposal_id)
                 and (experiment_id is None or report.experiment_id == experiment_id)
                 and (status is None or report.status == status)]
        return sorted(items, key=lambda report: (report.created_at, report.report_id), reverse=True)[:limit]

    def latest(self, workspace_id: str | None = None, service_name: str | None = None) -> CommercialReport | None:
        items = self.list_reports(workspace_id=workspace_id, service_name=service_name, limit=1)
        return items[0] if items else None

    def register_portfolio_report(self, report: PortfolioReport) -> PortfolioReport:
        with self._lock:
            self.portfolio_reports[report.portfolio_report_id] = report
            self.save()
        return report

    def get_portfolio_report(self, portfolio_report_id: str) -> PortfolioReport | None:
        return self.portfolio_reports.get(portfolio_report_id)

    def list_portfolio_reports(self, workspace_id: str | None = None, limit: int = 50) -> list[PortfolioReport]:
        limit = max(0, min(int(limit), 500))
        items = [report for report in self.portfolio_reports.values() if workspace_id is None or report.workspace_id == workspace_id]
        return sorted(items, key=lambda report: (report.created_at, report.portfolio_report_id), reverse=True)[:limit]

    def latest_portfolio_report(self, workspace_id: str | None = None) -> PortfolioReport | None:
        items = self.list_portfolio_reports(workspace_id, 1)
        return items[0] if items else None

    def clear_for_tests(self) -> None:
        self.reports.clear(); self.portfolio_reports.clear(); self.save()

    def to_dict(self) -> dict[str, Any]:
        return {"reports": {key: value.to_dict() for key, value in self.reports.items()},
                "portfolio_reports": {key: value.to_dict() for key, value in self.portfolio_reports.items()}}

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: str | os.PathLike[str] | None = None) -> "ReportRegistry":
        registry = cls(path)
        try:
            registry.reports = {key: CommercialReport.from_dict(value) for key, value in data.get("reports", {}).items() if isinstance(value, dict)}
            registry.portfolio_reports = {key: PortfolioReport.from_dict(value) for key, value in data.get("portfolio_reports", {}).items() if isinstance(value, dict)}
        except Exception:
            registry.reports, registry.portfolio_reports = {}, {}
        return registry

    def load(self) -> None:
        try:
            if not self.path.exists(): return
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.reports = {key: CommercialReport.from_dict(value) for key, value in raw.get("reports", {}).items() if isinstance(value, dict)}
            self.portfolio_reports = {key: PortfolioReport.from_dict(value) for key, value in raw.get("portfolio_reports", {}).items() if isinstance(value, dict)}
        except Exception:
            self.reports, self.portfolio_reports = {}, {}

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
            temp.replace(self.path)
        except Exception:
            pass


_singleton: ReportRegistry | None = None
_singleton_lock = threading.Lock()


def get_report_registry() -> ReportRegistry:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None: _singleton = ReportRegistry()
    return _singleton
