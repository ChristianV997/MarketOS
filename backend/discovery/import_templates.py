from __future__ import annotations

import csv
import io
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .csv_ingestion import PARSERS, load_csv_rows
from .import_recommendation import _FIELDS, ImportRecommendationPlan

DEFAULT_OUTPUT_DIR = "data/import_templates"
MANIFEST_SCHEMA = "marketos-import-template-manifest-v1"
PLACEHOLDER_CATEGORY = "PLACEHOLDER_CATEGORY"
PLACEHOLDER_VALUE = "PLACEHOLDER_TEST_VALUE"
# A real KNOWN_SIGNALS member, so the placeholder row is not silently dropped by the importer.
PLACEHOLDER_SIGNAL = "trend_proxy"
# Pass to normalize_imported_evidence so starter-kit rows stay labelled synthetic; the importer reads only this, not the manifest.
IMPORT_PROVENANCE = MappingProxyType({"type": "synthetic_fixture", "not_real_market_data": True})


class TemplateError(ValueError):
    """Carries a fixed reason code; never echoes a path or file content."""


class TemplateCollisionError(TemplateError):
    """An operator-owned file already occupies a target and overwrite was not requested."""


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


def _resolve_output_dir(output_dir: str) -> Path:
    """Return the output directory inside the approved data/import_templates root, refusing links and escapes."""
    root = Path.cwd() / "data" / "import_templates"
    raw = Path(output_dir)
    if ".." in raw.parts:
        raise TemplateError("template_output_path_blocked")
    requested = raw if raw.is_absolute() else Path.cwd() / raw
    if requested != root and root not in requested.parents:
        raise TemplateError("template_output_path_blocked")
    # Judge the unresolved chain: a symlinked data/ or import_templates/ would otherwise make the approved root itself point elsewhere.
    chain = [Path.cwd() / "data", root, *(root / part for part in requested.relative_to(root).parts)] if requested != root else [Path.cwd() / "data", root]
    for item in chain:
        if item.is_symlink():
            raise TemplateError("template_output_path_blocked")
    requested.mkdir(parents=True, exist_ok=True)
    if root.resolve() != requested.resolve() and root.resolve() not in requested.resolve().parents:
        raise TemplateError("template_output_path_blocked")
    return requested


def _placeholder_row(parser_type: str) -> dict[str, str]:
    required, optional = _FIELDS[parser_type]
    row = {name: PLACEHOLDER_VALUE for name in required + optional}
    row[required[0]] = PLACEHOLDER_CATEGORY
    if "signal_type" in row:
        row["signal_type"] = PLACEHOLDER_SIGNAL
    return row


def _csv_bytes(parser_type: str) -> bytes:
    required, optional = _FIELDS[parser_type]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=required + optional)
    writer.writeheader()
    writer.writerow(_placeholder_row(parser_type))
    return buffer.getvalue().encode("utf-8-sig")


def _manifest_bytes(parser_type: str, records: int) -> bytes:
    required, optional = _FIELDS[parser_type]
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "parser_type": parser_type,
        "file": f"{parser_type}.csv",
        "expected_input": "CSV with one header row; UTF-8 with optional byte-order mark; one record per data row",
        "data_dictionary": [{"field": name, "required": name in required} for name in required + optional],
        "placeholder_values": [PLACEHOLDER_CATEGORY, PLACEHOLDER_VALUE],
        "provenance": {"kind": "placeholder_template", "market_evidence": False, "not_real_market_data": True, "network_required": False},
        "round_trip": {"verified": True, "parser_records": records},
    }
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _round_trip(out_dir: Path, parser_type: str, csv_bytes: bytes) -> int:
    """Parse a staged copy with the importer's own parser and refuse any template that would not parse as advertised."""
    required, optional = _FIELDS[parser_type]
    staged = out_dir / f".{parser_type}.{uuid.uuid4().hex}.staged.csv"
    try:
        with staged.open("xb") as handle:
            handle.write(csv_bytes)
        with staged.open(encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), [])
        if not set(required) <= set(header) or not set(header) <= set(required) | set(optional):
            raise TemplateError("template_round_trip_header_mismatch")
        records = PARSERS[parser_type](load_csv_rows(str(staged)), {"source_name": parser_type, "type": "template"})
        if not records or any(record.provenance.get("parser_type") != parser_type for record in records):
            raise TemplateError("template_round_trip_failed")
        if any(not record.entity_name.startswith("PLACEHOLDER") for record in records):
            raise TemplateError("template_round_trip_failed")
        return len(records)
    finally:
        staged.unlink(missing_ok=True)


def _plan_publish(target: Path, content: bytes, *, overwrite: bool) -> str:
    if target.is_symlink():
        raise TemplateError("template_target_is_symlink")
    if target.is_dir():
        raise TemplateError("template_target_is_directory")
    if not target.exists():
        return "written"
    if target.read_bytes() == content:
        return "unchanged"
    if overwrite:
        return "written"
    raise TemplateCollisionError("template_exists_operator_file_preserved")


def _publish(target: Path, content: bytes, *, state: str, overwrite: bool) -> None:
    if state == "unchanged":
        return
    staged = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with staged.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(staged, target)
            return
        try:
            os.link(staged, target)  # atomic no-clobber: fails if the name appeared since the plan step
        except FileExistsError:
            raise TemplateCollisionError("template_exists_operator_file_preserved") from None
        except OSError:  # hard links unsupported here: fail closed rather than rename over a possible operator file
            raise TemplateError("template_publish_unsupported") from None
    finally:
        staged.unlink(missing_ok=True)


def _template(parser_type: str, csv_path: Path, source_name: str | None, *, records: int | None, status: str) -> ImportTemplate:
    required, optional = _FIELDS[parser_type]
    return ImportTemplate(
        "template_" + uuid.uuid5(uuid.NAMESPACE_URL, str(csv_path)).hex[:16],
        parser_type,
        f"{parser_type.replace('_', ' ').title()} template",
        "Placeholder-only local import template; replace rows with a documented export.",
        list(required),
        list(optional),
        [_placeholder_row(parser_type)],
        str(csv_path),
        metadata={
            "source_name": source_name or parser_type,
            "not_real_market_data": True,
            "network_required": False,
            "placeholder_only": True,
            "market_evidence": False,
            "manifest_file": f"{parser_type}.manifest.json",
            "import_provenance": dict(IMPORT_PROVENANCE),
            "round_trip_records": records,
            "publish": status,
        },
    )


def create_import_template(parser_type: str, output_dir: str = DEFAULT_OUTPUT_DIR, source_name: str | None = None, *, overwrite: bool = False) -> ImportTemplate:
    if parser_type not in _FIELDS or parser_type not in PARSERS:
        raise ValueError("unsupported_parser_type")
    out_dir = _resolve_output_dir(output_dir)
    csv_path = out_dir / f"{parser_type}.csv"
    manifest_path = out_dir / f"{parser_type}.manifest.json"
    csv_bytes = _csv_bytes(parser_type)
    records = _round_trip(out_dir, parser_type, csv_bytes)
    manifest_bytes = _manifest_bytes(parser_type, records)
    csv_state = _plan_publish(csv_path, csv_bytes, overwrite=overwrite)
    manifest_state = _plan_publish(manifest_path, manifest_bytes, overwrite=overwrite)
    _publish(csv_path, csv_bytes, state=csv_state, overwrite=overwrite)
    _publish(manifest_path, manifest_bytes, state=manifest_state, overwrite=overwrite)
    return _template(parser_type, csv_path, source_name, records=records, status=csv_state)


def create_templates_for_plan(plan: ImportRecommendationPlan, output_dir: str = DEFAULT_OUTPUT_DIR, *, overwrite: bool = False) -> list[ImportTemplate]:
    templates: list[ImportTemplate] = []
    for item in plan.recommendations:
        try:
            templates.append(create_import_template(item.parser_type, output_dir, item.source_name_suggestion, overwrite=overwrite))
        except TemplateCollisionError:
            # An operator-owned file is preserved as-is; the plan still points at it.
            csv_path = _resolve_output_dir(output_dir) / f"{item.parser_type}.csv"
            templates.append(_template(item.parser_type, csv_path, item.source_name_suggestion, records=None, status="preserved_existing_operator_file"))
    return templates
