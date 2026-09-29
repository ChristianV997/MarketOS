"""Run deterministic offline consumer-attention intelligence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.adapters.research.consumer_attention import ConsumerAttentionImportError, import_csv, import_json  # noqa: E402
from evaluation.commerce.consumer_attention import ConsumerAttentionEvidence, build_report, collapse_duplicates  # noqa: E402

DEFAULT = ROOT / "tests" / "fixtures" / "consumer_attention" / "google_trends_fixture.json"
SOURCE_PLATFORMS = ("google_trends", "tiktok", "meta", "youtube", "reddit", "amazon", "mercadolibre", "ebay", "shopify", "minea", "dropshipio", "pipiads", "kalodata", "manual")
DEFAULT_SOURCE_FIXTURES = {
    "google_trends": ("google_trends_fixture.json", "google_trends_fixture"),
    "tiktok": ("tiktok_creative_center_snapshot.json", "tiktok_creative_center_snapshot"),
    "meta": ("meta_ad_library_snapshot.json", "meta_ad_library_snapshot"),
    "youtube": ("youtube_search_snapshot.json", "youtube_search_snapshot"),
    "reddit": ("reddit_threads_manual_import.json", "reddit_threads_manual_import"),
    "amazon": ("amazon_reviews_snapshot.json", "amazon_reviews_snapshot"),
    "mercadolibre": ("mercadolibre_reviews_snapshot.json", "mercadolibre_reviews_snapshot"),
    "ebay": ("ebay_reviews_snapshot.json", "ebay_reviews_snapshot"),
    "shopify": ("shopify_reviews_snapshot.json", "shopify_reviews_snapshot"),
}


def markdown(report: dict) -> str:
    lines = ["# Consumer Attention and Creative Evidence", "", f"Evidence mode: `{report['evidence_mode']}` (offline; not ad authorization)", f"Candidates: {report['candidate_count']}", f"Evidence rows: {report['evidence_count']}", f"Platforms: {', '.join(report['platforms_observed']) or 'none'}", f"Freshness: `{report['freshness_status']}` (explicit reference time required)", f"Offering kinds: {', '.join(report['offering_kinds']) or 'unknown'}", f"Geographies: {', '.join(report['geographies']) or 'unspecified'}", f"Languages: {', '.join(report['languages']) or 'unspecified'}", f"Conflicts: {report['conflict_count']}", f"Top candidate: `{report['top_candidate_id'] or 'none'}`", f"Next action: `{report['next_best_action']}`", "", "## Attention scores", "", "| Candidate | Attention | VOC quality | Hook diversity | Objection risk | Recommendation |", "| --- | ---: | ---: | ---: | ---: | --- |"]
    for item in report["candidates"]:
        score = item["score"]
        lines.append(f"| {item['candidate_id']} | {score['overall_consumer_attention']:.0%} | {score['voice_of_customer_quality']:.0%} | {score['creative_hook_diversity']:.0%} | {score['objection_density']:.0%} | `{score['recommendation']}` |")
    lines += ["", "## Creative angles", ""]
    for item in report["candidates"][:5]:
        score = item["score"]
        lines.append(f"- **{item['candidate_id']}**: hooks={', '.join(score['recommended_ad_angles']) or 'none'}; UGC={', '.join(score['recommended_ugc_formats']) or 'none'}.")
    lines += ["", "## Safety", "", "- No network, platform calls, posting, ad launch, or provider mutation occurs.", "- Consumer attention is not supplier proof or launch authorization.", ""]
    lines.extend(f"- {warning}" for warning in report.get("warnings", []))
    return "\n".join(lines) + "\n"


def creative_summary(report: dict) -> str:
    lines = ["# Creative Angle Summary", "", "Deterministic hypotheses from sanitized evidence; not ad-launch instructions.", ""]
    for item in report.get("candidates", []):
        score = item["score"]
        voc = score["voice_of_customer"]
        lines += [f"## {item['candidate_id']}", f"Hooks: {', '.join(hook['hook'] for hook in score['creative_hooks']) or 'none'}", f"Pain points: {', '.join(voc['pain_points']) or 'none'}", f"Desired outcomes: {', '.join(voc['desired_outcomes']) or 'none'}", f"Objections: {', '.join(voc['objections']) or 'none'}", f"Ad angles: {', '.join(score['recommended_ad_angles']) or 'none'}", f"UGC formats: {', '.join(score['recommended_ugc_formats']) or 'none'}", ""]
    return "\n".join(lines)


def _bounded(records: list[ConsumerAttentionEvidence], args: argparse.Namespace) -> list[ConsumerAttentionEvidence]:
    records = collapse_duplicates(records)
    if args.source:
        records = [item for item in records if item.platform == args.source]
    candidates = sorted({item.candidate_id for item in records})[: args.max_candidates]
    return [item for item in records if item.candidate_id in candidates]


def _default_records(source: str | None) -> list[ConsumerAttentionEvidence]:
    """Load only the checked-in synthetic snapshots for deterministic demo mode."""
    root = DEFAULT.parent
    if source and source in DEFAULT_SOURCE_FIXTURES:
        names = (DEFAULT_SOURCE_FIXTURES[source],)
    elif source:
        names = ()
    else:
        names = tuple(DEFAULT_SOURCE_FIXTURES.values())
    records: list[ConsumerAttentionEvidence] = []
    for filename, source_type in names:
        records.extend(import_json(root / filename, platform=next((key for key, value in DEFAULT_SOURCE_FIXTURES.items() if value == (filename, source_type)), "manual"), source_type=source_type))
    return records


def _write_output(directory: str, report: dict, text: str) -> None:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    (target / "consumer_attention_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf8")
    (target / "consumer_attention_report.md").write_text(text, encoding="utf8")
    (target / "creative_angle_summary.md").write_text(creative_summary(report), encoding="utf8")
    (target / "consumer_source_summary.json").write_text(json.dumps({"platforms": report["platforms_observed"], "candidate_count": report["candidate_count"], "evidence_count": report["evidence_count"], "freshness_status": report["freshness_status"], "offering_kinds": report["offering_kinds"], "geographies": report["geographies"], "languages": report["languages"], "conflict_count": report["conflict_count"], "read_only": True, "network_calls": False, "mutated": False}, indent=2, sort_keys=True) + "\n", encoding="utf8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline consumer attention intelligence")
    parser.add_argument("--candidate-seed")
    parser.add_argument("--manual-import")
    parser.add_argument("--source", choices=SOURCE_PLATFORMS)
    parser.add_argument("--max-candidates", type=int, default=10)
    parser.add_argument("--as-of", help="Timezone-aware ISO-8601 reference time for freshness")
    parser.add_argument("--freshness-days", type=int, default=90)
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    if args.max_candidates < 1:
        parser.error("max-candidates must be positive")
    if args.freshness_days < 1:
        parser.error("freshness-days must be positive")
    try:
        if args.manual_import:
            records = import_csv(args.manual_import, platform=args.source or "manual")
        elif args.candidate_seed:
            records = import_json(args.candidate_seed, platform=args.source or "manual", source_type="fixture_demo")
        else:
            records = _default_records(args.source)
        records = _bounded(records, args)
    except (OSError, ValueError, json.JSONDecodeError, ConsumerAttentionImportError) as exc:
        parser.error(str(exc))
    try:
        report = build_report(
            records,
            evidence_mode="manual_import" if args.manual_import else "fixture_demo",
            as_of=args.as_of,
            max_age_days=args.freshness_days,
        ).to_dict()
    except ValueError as exc:
        parser.error(str(exc))
    text = markdown(report)
    if args.output:
        _write_output(args.output, report, text)
    print(text if args.markdown else json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
