"""backend.aws.heartbeat — S3-based liveness heartbeat for the PC/AWS standby pair.

Whichever orchestrator instance is actively ticking (normally the PC)
periodically PUTs a small heartbeat object to S3 (orchestrator/main.py's
_write_checkpoint does this on every checkpoint). The AWS standby instance
(deploy/aws/main.tf) polls the same object's LastModified timestamp and
only starts ticking itself once it goes stale past AWS_TAKEOVER_AFTER_S —
see orchestrator/main.py's _await_takeover().

boto3 is optional and lazily imported: both push and check fail soft
(return False / None, never raise) when it's unavailable or
MARKETOS_HEARTBEAT_BUCKET is unset, since most deployments (a lone PC,
tests, CI) never configure AWS standby at all.
"""
from __future__ import annotations

import json
import logging
import os
import time

_log = logging.getLogger(__name__)

_BUCKET = os.getenv("MARKETOS_HEARTBEAT_BUCKET", "")
_KEY    = os.getenv("MARKETOS_HEARTBEAT_KEY", "orchestrator/heartbeat.json")


def push_heartbeat(node: str = "unknown") -> bool:
    """PUT a small heartbeat object to S3. Best-effort: returns False
    (never raises) if boto3 is missing, no bucket is configured, or the
    PUT fails for any reason."""
    if not _BUCKET:
        return False
    try:
        import boto3  # noqa: PLC0415  lazy import — optional dependency
        boto3.client("s3").put_object(
            Bucket=_BUCKET,
            Key=_KEY,
            Body=json.dumps({"node": node, "ts": time.time()}).encode("utf-8"),
            ContentType="application/json",
        )
        return True
    except Exception as exc:
        _log.debug("heartbeat_push_failed error=%s", exc)
        return False


def heartbeat_age_s() -> float | None:
    """Seconds since the last heartbeat PUT, or None if it can't be
    determined right now (no bucket configured, boto3 missing, object
    missing, or any S3 error).

    Callers must treat None as "unknown", never as "stale" — a transient
    S3/network hiccup must not look identical to the PC actually being
    down, or a standby node would take over during a routine blip.
    """
    if not _BUCKET:
        return None
    try:
        import boto3  # noqa: PLC0415  lazy import — optional dependency
        obj = boto3.client("s3").head_object(Bucket=_BUCKET, Key=_KEY)
        return time.time() - obj["LastModified"].timestamp()
    except Exception as exc:
        _log.debug("heartbeat_check_failed error=%s", exc)
        return None
