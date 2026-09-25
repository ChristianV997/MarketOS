"""Offline validator for the advisory OSS source intake catalog.

The intake catalog is not a source authority. This tool checks its rows and
reports, without fixing, known defects in the canonical source adaptation
registry and the external capability catalog.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INTAKE = REPO_ROOT / "data" / "oss_source_intake.json"
DEFAULT_REGISTRY = REPO_ROOT / "data" / "source_adaptation_registry.json"
DEFAULT_CAPABILITIES = REPO_ROOT / "data" / "external_capability_catalog.json"

VERDICTS = {"integrate", "copy_pattern", "reference_only", "sidecar", "defer", "reject"}
COPY_VERDICTS = {"integrate", "copy_pattern"}
SIDECAR_OR_DEFER = {"sidecar", "defer"}
REQUIRED_PROHIBITED_FLAGS = (
    "no_live_scraping",
    "no_proxy_rotation",
    "no_credentials",
    "no_raw_payloads",
    "no_provider_activation",
)
PROHIBITED_FLAG_ENUM = frozenset(REQUIRED_PROHIBITED_FLAGS)
CONFIDENCE = {"low", "medium", "high"}
FLOATING_REVISIONS = {"main", "master", "latest", "head", "origin/main", "origin/master"}
PLACEHOLDER_PREFIXES = ("e5f6a7b8c9", "1a8b9c0d2e", "3c4d5e6f7a")
LICENSE_FILENAMES = {
    "LICENSE",
    "LICENSE.md",
    "LICENSE.txt",
    "LICENSE.rst",
    "COPYING",
    "COPYING.md",
    "COPYING.txt",
}
FLOATING_LICENSE_MARKERS = (
    "/blob/main/",
    "/blob/master/",
    "/blob/HEAD/",
    "/blob/head/",
    "/blob/latest/",
    "/raw/main/",
    "/raw/master/",
    "/raw/HEAD/",
    "/raw/head/",
    "/raw/latest/",
    "/-/blob/main/",
    "/-/blob/master/",
    "/-/blob/HEAD/",
    "/-/blob/head/",
    "/-/raw/main/",
    "/-/raw/master/",
)
CANDIDATE_CLASSES = {
    "oss_library",
    "platform_sdk",
    "external_api_client",
    "dependency_decision",
    "methodology_reference",
    "unidentified_namesake",
}
REQUIRED_TEXT = (
    "maintenance_evidence",
    "relevant_module",
    "work_order_id",
    "marketos_target_capability",
    "security_tos_risks",
    "duplicate_authority_decision",
)
MAX_CANDIDATES_PER_WORK_ORDER = 5
MAX_ERRORS = 100
SHA40 = re.compile(r"^[0-9a-f]{40}$")
# Exact repository URL on any https forge: https://host/owner/name
# with no .git suffix, trailing slash, query, fragment, or extra path.
REPO_URL = re.compile(r"^https://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?/[A-Za-z0-9_.~-]+/[A-Za-z0-9_.~-]+$")
SOURCE_ID = re.compile(r"^oss-[a-z0-9]+(?:-[a-z0-9]+)*$")
REGISTRY_REF = re.compile(r"^src-[a-z0-9]+(?:-[a-z0-9]+)*$")


def is_all_zero_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"0{40}", value.strip().lower()))


def _has_directional_run(values: list[int], minimum: int) -> bool:
    """True when values contain a long +1 or -1 run modulo 16."""
    if len(values) < minimum:
        return False
    best = 1
    run = 1
    previous_delta: int | None = None
    for index in range(1, len(values)):
        delta = (values[index] - values[index - 1]) % 16
        if delta in (1, 15) and (previous_delta is None or delta == previous_delta):
            run += 1
            previous_delta = delta
            best = max(best, run)
        else:
            run = 1
            previous_delta = None
    return best >= minimum


def is_patterned_placeholder_sha(value: Any) -> bool:
    """Detect ascending or interleaved sequential-hex placeholder SHAs.

    The known registry placeholders start with e5f6a7b8c9, 1a8b9c0d2e, and
    3c4d5e6f7a. A SHA is also patterned when its hex digits, or either
    alternating nibble stream, contain a run of eight steps of +1 or -1.
    """
    if not isinstance(value, str):
        return False
    sha = value.strip().lower()
    if any(sha.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES):
        return True
    if not SHA40.fullmatch(sha):
        return False
    nibbles = [int(character, 16) for character in sha]
    return (
        _has_directional_run(nibbles, 8)
        or _has_directional_run(nibbles[0::2], 8)
        or _has_directional_run(nibbles[1::2], 8)
    )


def is_exact_repository_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if value != value.strip() or value.endswith(".git") or value.endswith("/"):
        return False
    return bool(REPO_URL.fullmatch(value))


def license_blocks_copy(license_name: Any) -> bool:
    """GPL, AGPL, unknown, missing, and unverified classifications block copy or integrate."""
    if not isinstance(license_name, str):
        return True
    text = license_name.strip().lower()
    if text in {"", "unknown", "missing", "n/a", "none", "none_verified", "unlicensed"}:
        return True
    if "unknown" in text or "missing" in text:
        return True
    if "general public license" in text or "affero" in text:
        return True
    if re.search(r"(^|[^a-z])agpl", text) or re.search(r"(^|[^a-z])gpl", text):
        return True
    return False


def _load_json(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"file not found: {path}"
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc.msg}"


def _registry_index(document: Any) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    rows = document if isinstance(document, list) else []
    by_id: dict[str, dict[str, Any]] = {}
    by_url: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_id = row.get("source_id")
        url = row.get("repository_url")
        if isinstance(source_id, str):
            by_id[source_id] = row
        if isinstance(source_id, str) and isinstance(url, str):
            by_url.setdefault(url, []).append(source_id)
    return by_id, by_url


# src-scrapy stores the annotated tag object for 2.12.0 in commit fields.
# That object peels to commit b1f9e56693cd2000ddcea922306f726f3e9339af.
# Reported as a #272 defect. It is not a version conflict, and it is not fixed here.
ANNOTATED_TAG_OBJECT_SHA = "8c85937adef8279f12e35e0ee9a20c52ff6d1648"
ANNOTATED_TAG_OBJECT_SOURCE = "src-scrapy"


def _sha_defect(value: Any, *, source_id: str = "") -> str | None:
    if is_all_zero_sha(value):
        return "all_zero_sha"
    if is_patterned_placeholder_sha(value):
        return "patterned_placeholder_sha"
    if source_id == ANNOTATED_TAG_OBJECT_SOURCE and value == ANNOTATED_TAG_OBJECT_SHA:
        return "annotated_tag_object_sha"
    return None


def collect_registry_defects(document: Any) -> list[dict[str, Any]]:
    defects: list[dict[str, Any]] = []
    rows = document if isinstance(document, list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_id = str(row.get("source_id") or "")
        for field in ("revision", "commit_sha"):
            defect = _sha_defect(row.get(field), source_id=source_id)
            if defect is None:
                continue
            defects.append(
                {
                    "defect": defect,
                    "field": field,
                    "record_id": source_id,
                    "record_kind": "source_adaptation_registry",
                    "value": row.get(field),
                }
            )
    return sorted(defects, key=lambda item: (item["record_id"], item["field"], item["defect"]))


def collect_capability_defects(document: Any) -> list[dict[str, Any]]:
    defects: list[dict[str, Any]] = []
    rows = document if isinstance(document, list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        defect = _sha_defect(row.get("commit_sha"))
        if defect is None:
            continue
        defects.append(
            {
                "capability_id": str(row.get("capability_id") or ""),
                "defect": defect,
                "field": "commit_sha",
                "record_kind": "external_capability_catalog",
                "value": row.get("commit_sha"),
            }
        )
    return sorted(defects, key=lambda item: (item["capability_id"], item["defect"]))


def _license_is_absent(license_name: Any) -> bool:
    if not isinstance(license_name, str):
        return True
    text = license_name.strip().lower()
    return (
        text in {"", "unknown", "missing", "n/a", "none", "none_verified", "unlicensed"}
        or "unknown" in text
        or "missing" in text
    )


def _license_url_error(url: Any, revision: str) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return "primary LICENSE evidence URL is missing"
    if url != url.strip() or not url.startswith("https://"):
        return "primary LICENSE evidence URL is not an exact https URL"
    if any(marker in url for marker in FLOATING_LICENSE_MARKERS):
        return "primary LICENSE evidence URL uses a floating revision"
    if revision not in url:
        return "primary LICENSE evidence URL does not contain the pinned revision"
    filename = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    if filename not in LICENSE_FILENAMES:
        return "primary LICENSE evidence URL does not name a primary LICENSE file"
    return None


def _validate_candidate(
    row: Any,
    index: int,
    seen_ids: set[str],
    registry_by_id: dict[str, dict[str, Any]],
    registry_by_url: dict[str, list[str]],
) -> list[str]:
    label = f"candidate[{index}]"
    if not isinstance(row, dict):
        return [f"{label} is not an object"]
    source_id = row.get("source_id")
    if isinstance(source_id, str) and source_id:
        label = source_id
    errors: list[str] = []
    if not isinstance(source_id, str) or not SOURCE_ID.fullmatch(source_id):
        errors.append(f"{label}: source_id must use the oss- intake prefix")
    elif source_id in seen_ids:
        errors.append(f"{label}: duplicate source_id")
    else:
        seen_ids.add(source_id)

    url = row.get("repository_url")
    identity_unresolved = row.get("identity_unresolved") is True
    if "identity_unresolved" in row and not isinstance(row.get("identity_unresolved"), bool):
        errors.append(f"{label}: identity_unresolved must be boolean")
    verdict = row.get("verdict")
    unresolved_without_repo = url is None and identity_unresolved and verdict in {"reference_only", "reject"}
    if url is None:
        if not unresolved_without_repo:
            errors.append(
                f"{label}: null repository URL requires identity_unresolved and verdict reference_only or reject"
            )
    elif not is_exact_repository_url(url):
        errors.append(f"{label}: repository URL is not exact")

    revision = row.get("revision")
    revision_text = revision.strip() if isinstance(revision, str) else ""
    if unresolved_without_repo and (revision is None or revision_text == ""):
        pass
    elif not isinstance(revision, str) or revision_text == "":
        errors.append(f"{label}: revision is empty")
    elif revision_text.lower() in FLOATING_REVISIONS or revision_text.lower().startswith("refs/"):
        errors.append(f"{label}: revision is floating")
    elif is_all_zero_sha(revision_text):
        errors.append(f"{label}: revision is all-zero")
    elif is_patterned_placeholder_sha(revision_text):
        errors.append(f"{label}: revision is a patterned placeholder")
    elif not SHA40.fullmatch(revision_text) or revision_text != revision_text.lower():
        errors.append(f"{label}: revision is not a 40-character commit SHA")

    version_tag = row.get("version_tag")
    if version_tag is not None and (not isinstance(version_tag, str) or not version_tag.strip()):
        errors.append(f"{label}: version_tag is empty")
    elif isinstance(version_tag, str) and version_tag.strip().lower() in FLOATING_REVISIONS:
        errors.append(f"{label}: version_tag is floating")

    verdict = row.get("verdict")
    registry_ref_present = row.get("registry_ref") is not None
    if registry_ref_present:
        if verdict is not None:
            errors.append(f"{label}: registry_ref row must have a null verdict")
    elif verdict not in VERDICTS:
        errors.append(f"{label}: verdict is not an intake verdict")

    license_name = row.get("license")
    if verdict in COPY_VERDICTS and license_blocks_copy(license_name):
        errors.append(f"{label}: license blocks integrate/copy_pattern ({license_name!r})")
    if unresolved_without_repo and not _license_is_absent(license_name):
        errors.append(f"{label}: identity_unresolved row has no primary LICENSE file")

    pinned_sha = isinstance(revision, str) and bool(SHA40.fullmatch(revision_text)) and revision_text == revision_text.lower()
    if pinned_sha:
        url_error = _license_url_error(row.get("license_evidence_url"), revision_text)
        allow_missing_file = verdict in {"reject", "reference_only"} and _license_is_absent(license_name)
        if url_error and not allow_missing_file:
            errors.append(f"{label}: {url_error}")
    elif verdict in COPY_VERDICTS and row.get("license_evidence_url") not in (None, ""):
        errors.append(f"{label}: primary LICENSE evidence URL does not contain the pinned revision")

    candidate_class = row.get("candidate_class")
    if candidate_class not in CANDIDATE_CLASSES:
        errors.append(f"{label}: candidate_class is not an intake class")
    if verdict is not None and candidate_class == "platform_sdk" and verdict not in SIDECAR_OR_DEFER:
        errors.append(f"{label}: platform_sdk verdict must be sidecar or defer")
    if verdict is not None and candidate_class == "external_api_client" and verdict not in SIDECAR_OR_DEFER:
        errors.append(f"{label}: external_api_client verdict must be sidecar or defer")

    for field in ("prohibited_behavior", "attribution_requirement"):
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label}: {field} is empty")
    flags = row.get("prohibited_behavior_flags")
    if not isinstance(flags, list):
        errors.append(f"{label}: prohibited_behavior_flags must be a list")
    else:
        present: set[str] = set()
        for flag in flags:
            if not isinstance(flag, str) or flag not in PROHIBITED_FLAG_ENUM:
                errors.append(f"{label}: prohibited_behavior_flags has unknown flag {flag!r}")
            else:
                present.add(flag)
        for flag in REQUIRED_PROHIBITED_FLAGS:
            if flag not in present:
                errors.append(f"{label}: prohibited_behavior_flags missing {flag}")
    for field in REQUIRED_TEXT:
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label}: {field} is empty")
    if "unknowns" not in row or not isinstance(row.get("unknowns"), str):
        errors.append(f"{label}: unknowns is missing")
    if row.get("confidence") not in CONFIDENCE:
        errors.append(f"{label}: confidence is not low, medium, or high")
    work_order_id = row.get("work_order_id")
    if not isinstance(work_order_id, str) or not work_order_id.strip():
        errors.append(f"{label}: work_order_id is empty")

    registry_ref = row.get("registry_ref")
    url = row.get("repository_url")
    if registry_ref is not None:
        if not isinstance(registry_ref, str) or not REGISTRY_REF.fullmatch(registry_ref):
            errors.append(f"{label}: registry_ref does not exist")
        elif registry_ref not in registry_by_id:
            errors.append(f"{label}: registry_ref does not exist")
        else:
            recorded_url = registry_by_id[registry_ref].get("repository_url")
            if recorded_url != url:
                errors.append(f"{label}: registry_ref does not match repository URL")
    if isinstance(url, str) and url in registry_by_url:
        owners = registry_by_url[url]
        if registry_ref not in owners:
            errors.append(f"{label}: repository URL is already in the source adaptation registry")
    return errors


def validate_candidates(
    candidates: list[Any],
    registry_by_id: dict[str, dict[str, Any]],
    registry_by_url: dict[str, list[str]],
) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    counts: dict[str, int] = {}
    for index, row in enumerate(candidates):
        errors.extend(_validate_candidate(row, index, seen_ids, registry_by_id, registry_by_url))
        if isinstance(row, dict) and isinstance(row.get("work_order_id"), str):
            counts[row["work_order_id"]] = counts.get(row["work_order_id"], 0) + 1
    for work_order_id in sorted(counts):
        count = counts[work_order_id]
        if count > MAX_CANDIDATES_PER_WORK_ORDER:
            errors.append(f"work order {work_order_id} has more than 5 candidates ({count})")
    return errors


def _work_order_counts(candidates: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in candidates:
        if isinstance(row, dict) and isinstance(row.get("work_order_id"), str):
            counts[row["work_order_id"]] = counts.get(row["work_order_id"], 0) + 1
    return dict(sorted(counts.items()))


def build_report(intake: Any, registry: Any, capabilities: Any, intake_error: str | None = None) -> dict[str, Any]:
    errors: list[str] = []
    candidates: list[Any] = []
    if intake_error:
        errors.append(intake_error)
    elif not isinstance(intake, dict):
        errors.append("intake catalog must be an object with candidates")
    else:
        if intake.get("catalog_status") != "advisory_intake_only":
            errors.append("catalog_status must be advisory_intake_only")
        if intake.get("authority") != "none":
            errors.append("authority must be none")
        raw_candidates = intake.get("candidates")
        if not isinstance(raw_candidates, list):
            errors.append("candidates must be a list")
        else:
            candidates = raw_candidates
    registry_by_id, registry_by_url = _registry_index(registry)
    if isinstance(candidates, list):
        errors.extend(validate_candidates(candidates, registry_by_id, registry_by_url))
    errors = sorted(set(errors))
    truncated = len(errors) > MAX_ERRORS
    if truncated:
        errors = errors[:MAX_ERRORS]
        errors.append(f"error list truncated at {MAX_ERRORS}")
    registry_defects = collect_registry_defects(registry)
    capability_defects = collect_capability_defects(capabilities)
    canonical = json.dumps(intake, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return {
        "authority": "none",
        "candidate_count": len(candidates),
        "capability_catalog_defects": capability_defects,
        "catalog_status": "advisory_intake_only",
        "error_count": len(errors),
        "errors": errors,
        "errors_truncated": truncated,
        "registry_defects": registry_defects,
        "stable_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "valid": not errors,
        "work_order_counts": _work_order_counts(candidates),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# OSS source intake validation",
        "",
        "Advisory intake check. This report does not modify the canonical registry or the capability catalog.",
        "",
        f"- Valid: {'yes' if report['valid'] else 'no'}",
        f"- Candidates: {report['candidate_count']}",
        f"- Errors: {report['error_count']}",
        f"- Stable hash: {report['stable_hash']}",
        "",
        "## Work orders",
        "",
    ]
    counts = report["work_order_counts"]
    if counts:
        for work_order_id, count in counts.items():
            lines.append(f"- {work_order_id}: {count}")
    else:
        lines.append("- none")
    lines.extend(["", "## Intake errors", ""])
    if report["errors"]:
        lines.extend(f"- {error}" for error in report["errors"])
    else:
        lines.append("- none")
    lines.extend(["", "## Canonical registry defects (reported, not fixed)", ""])
    if report["registry_defects"]:
        for defect in report["registry_defects"]:
            lines.append(
                f"- {defect['record_id']} {defect['field']}: {defect['defect']} `{defect['value']}`"
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Capability catalog defects (reported, not fixed)", ""])
    if report["capability_catalog_defects"]:
        for defect in report["capability_catalog_defects"]:
            lines.append(
                f"- {defect['capability_id']} {defect['field']}: {defect['defect']} `{defect['value']}`"
            )
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def validate_paths(intake_path: Path, registry_path: Path, capability_path: Path) -> tuple[dict[str, Any], int]:
    if not intake_path.is_file():
        report = build_report(None, None, None, intake_error=f"file not found: {intake_path}")
        report["valid"] = False
        return report, 2
    intake, intake_error = _load_json(intake_path)
    registry, registry_error = _load_json(registry_path)
    capabilities, capability_error = _load_json(capability_path)
    report = build_report(intake, registry if registry_error is None else None, capabilities if capability_error is None else None, intake_error)
    if registry_error:
        report["registry_defects"] = [
            {
                "defect": "unreadable",
                "field": "",
                "record_id": "",
                "record_kind": "source_adaptation_registry",
                "value": registry_error,
            }
        ]
    if capability_error:
        report["capability_catalog_defects"] = [
            {
                "capability_id": "",
                "defect": "unreadable",
                "field": "commit_sha",
                "record_kind": "external_capability_catalog",
                "value": capability_error,
            }
        ]
    return report, 0 if report["valid"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the advisory OSS source intake catalog.")
    parser.add_argument("--intake", default=str(DEFAULT_INTAKE), help="Path to data/oss_source_intake.json")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY), help="Path to the canonical source adaptation registry")
    parser.add_argument("--capability-catalog", default=str(DEFAULT_CAPABILITIES), help="Path to the external capability catalog")
    parser.add_argument("--json", action="store_true", help="Print the deterministic JSON report")
    parser.add_argument("--markdown", action="store_true", help="Print the deterministic Markdown report")
    args = parser.parse_args(argv)
    report, status = validate_paths(Path(args.intake), Path(args.registry), Path(args.capability_catalog))
    # --json wins when both flags are set so stdout stays a single document.
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_markdown(report), end="")
    return status


if __name__ == "__main__":
    sys.exit(main())
