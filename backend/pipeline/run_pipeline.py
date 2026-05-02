"""run_pipeline — end-to-end signal pipeline: ingest → rank → filter → dedup → hooks → ads."""
from __future__ import annotations
import json
import csv
import os
import time

from backend.signals.ingest import ingest_all_sync
from backend.pipeline.rank import rank_signals
from backend.pipeline.filter import filter_signals, FILTER_KEYWORDS, ENGAGEMENT_THRESHOLD
from backend.pipeline.dedup import dedup_signals
from backend.pipeline.hooks import generate_hooks
from backend.pipeline.ads import format_ads

OUTPUT_JSON = "output_ads.json"
OUTPUT_CSV  = "output_ads.csv"

VALID_SOURCES = {"tiktok", "youtube", "meta", "google", "amazon", "google_trends", "linkedin"}


def run() -> dict:
    _start_time = time.time()

    # 1. Ingest
    all_signals = ingest_all_sync()
    print(f"[ingest]  {len(all_signals)} signals from {len(VALID_SOURCES)} sources")

    # 2. Rank
    ranked = rank_signals(all_signals)

    # 3. Filter
    filtered = filter_signals(ranked)
    print(f"[filter]  {len(filtered)} signals passed ({len(FILTER_KEYWORDS)} keywords, "
          f"engagement >= {ENGAGEMENT_THRESHOLD})")

    # 4. Dedup
    deduped = dedup_signals(filtered)
    print(f"[dedup]   {len(deduped)} signals after dedup (removed {len(filtered) - len(deduped)})")

    # 5. Hooks
    hooks = generate_hooks(deduped)
    print(f"[hooks]   {len(hooks)} hooks generated")

    # 6. Ads
    ads = format_ads(hooks)
    print(f"[ads]     {len(ads)} ads formatted")

    # 7. Write JSON
    output = {
        "meta": {
            "total_signals": len(all_signals),
            "filtered_signals": len(filtered),
            "deduped_signals": len(deduped),
            "hooks": len(hooks),
            "ads": len(ads),
            "sources": sorted(VALID_SOURCES),
            "filter_keywords": FILTER_KEYWORDS,
        },
        "signals": [dict(s) for s in all_signals],
        "filtered": [dict(s) for s in filtered],
        "ads": ads,
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"[output]  {OUTPUT_JSON} written ({os.path.getsize(OUTPUT_JSON):,} bytes)")

    # 8. Write CSV
    if ads:
        fieldnames = list(ads[0].keys())
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(ads)
        print(f"[output]  {OUTPUT_CSV} written ({len(ads)} rows)")

    try:
        from backend.connectors.notion_logger import NotionLogger
        import datetime as _dt
        _end_time = time.time()
        _started_at = _dt.datetime.fromtimestamp(_start_time, tz=_dt.timezone.utc).isoformat()
        _finished_at = _dt.datetime.fromtimestamp(_end_time, tz=_dt.timezone.utc).isoformat()
        NotionLogger().log_run({
            "pipeline_entrypoint": "backend/pipeline/run_pipeline.py",
            "started_at": _started_at,
            "finished_at": _finished_at,
            "duration_seconds": round(_end_time - _start_time, 3),
            "ads_count": len(ads) if ads is not None else None,
            "sources_count": len(all_signals) if all_signals is not None else None,
            "deterministic": None,
            "output_files": [OUTPUT_JSON, OUTPUT_CSV],
        })
    except Exception:
        pass

    return output


if __name__ == "__main__":
    run()
