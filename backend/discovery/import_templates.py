from __future__ import annotations

import csv
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .import_recommendation import _FIELDS, ImportRecommendationPlan


@dataclass
class ImportTemplate:
    template_id: str
    parser_type: str
    title: str
    description: str
    required_fields: list[str]
    optional_fields: list[str]
    example_rows: list[dict[str, Any]]
    file_path: str
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self) -> dict[str, Any]: return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImportTemplate": return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


def _safe_output(output_dir: str) -> Path:
    root = (Path.cwd() / "data" / "import_templates").resolve()
    candidate = (Path.cwd() / output_dir).resolve() if not Path(output_dir).is_absolute() else Path(output_dir).resolve()
    if candidate != root and root not in candidate.parents: raise ValueError("template_output_path_blocked")
    candidate.mkdir(parents=True, exist_ok=True); return candidate


def create_import_template(parser_type: str, output_dir: str = "data/import_templates", source_name: str | None = None) -> ImportTemplate:
    if parser_type not in _FIELDS: raise ValueError("unsupported_parser_type")
    required, optional = _FIELDS[parser_type]; fields = required + optional
    row = {field: "PLACEHOLDER_TEST_VALUE" for field in fields}; row[required[0]] = "PLACEHOLDER_CATEGORY"
    path = _safe_output(output_dir) / f"{parser_type}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerow(row)
    return ImportTemplate("template_" + uuid.uuid5(uuid.NAMESPACE_URL, str(path)).hex[:16], parser_type, f"{parser_type.replace('_', ' ').title()} template", "Placeholder-only local import template; replace rows with a documented export.", required, optional, [row], str(path), metadata={"source_name": source_name or parser_type, "not_real_market_data": True, "network_required": False})


def create_templates_for_plan(plan: ImportRecommendationPlan, output_dir: str = "data/import_templates") -> list[ImportTemplate]:
    return [create_import_template(item.parser_type, output_dir, item.source_name_suggestion) for item in plan.recommendations]
