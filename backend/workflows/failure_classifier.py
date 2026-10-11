"""Deterministic workflow failure classification and safe operator recovery guidance.

Provides stable, bounded, and non-reflective failure classification for workflow stage
executions. Guarantees that no raw exceptions, filesystem paths, secrets, canaries,
PII, or unvetted caller contexts are reflected in outputs.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Allowed metadata context keys - arbitrary caller context is strictly filtered.
ALLOWED_CONTEXT_KEYS = frozenset(
    {
        "workspace_id",
        "workflow_id",
        "run_id",
        "checkpoint_id",
        "step_order",
        "attempt",
        "retry_count",
        "stage_name",
        "order",
    }
)

SECRET_KEY_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "authorization",
        "auth_token",
        "password",
        "private_key",
        "secret",
        "secret_key",
        "token",
        "credential",
        "credentials",
        "cookie",
        "cookies",
        "cj_api_key",
    }
)

# Regex patterns for scrub targets
_PATH_PATTERNS = re.compile(
    r"(?is)("
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\)[^\s'\",;<>|]+"  # Windows drive/UNC
    r"|(?<![A-Za-z0-9])/(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+"  # POSIX absolute
    r"|(?<![A-Za-z0-9])(?:\.\.[\\/])+[^\s'\",;<>|]*"  # Traversal
    r"|(?<![A-Za-z0-9])~[\\/][^\s'\",;<>|]+"  # Home directory
    r")"
)

_SECRET_SHAPED = re.compile(
    r"(?is)("
    r"-----begin (?:rsa |ec |dsa |openssh )?private key-----"
    r"|ghp[-_][A-Za-z0-9_-]{16,}"
    r"|github_pat[-_][A-Za-z0-9_-]{16,}"
    r"|sk-(?:live|test)?-?[A-Za-z0-9]{12,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|bearer\s+[A-Za-z0-9._-]{10,}"
    r"|(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|secret|token|credential)[=:\s]+[^\s,;]+"
    r")"
)

_CANARY_PATTERNS = re.compile(r"(?i)\b(?:zz-[a-z0-9_-]+|canary-[a-z0-9_-]+|marker-[a-z0-9_-]+)\b")
_TRACEBACK_PATTERNS = re.compile(r"(?is)(?:Traceback \(most recent call last\):.*|File \"[^\"]+\", line \d+.*)")
_EMAIL_PATTERNS = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")

CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "unsafe_path": "an unconfined or unsafe path was rejected by safety policy.",
    "blocked_by_safety": "stage was blocked by offline safety policy.",
    "unsupported_parser": "unsupported evidence parser type requested.",
    "no_evidence": "no evidence files or datasets available for processing.",
    "unavailable_service": "a required local dependency or service module is unavailable.",
    "obsidian_unconfigured": "Obsidian vault path is not configured.",
    "registry_unavailable": "durable entity or workflow registry is unavailable.",
    "artifact_render_failed": "artifact template rendering or packaging failed.",
    "validation_failed": "stage outputs failed validation criteria or gates.",
    "unexpected_exception": "an unexpected internal error occurred.",
}

CATEGORY_NEXT_ACTIONS: dict[str, list[str]] = {
    "unsafe_path": [
        "Inspect configured paths and ensure references stay within allowed directories.",
        "Do not provide unconfined, absolute external, or traversal paths.",
    ],
    "blocked_by_safety": [
        "Verify stage inputs comply with offline execution policy.",
        "Ensure external mutations and live provider actions remain disabled.",
    ],
    "unsupported_parser": [
        "Select a supported evidence parser type (e.g., supplier_catalog_csv, amazon_bestsellers_csv).",
        "Review the stage input payload for supported parser configurations.",
    ],
    "no_evidence": [
        "Provide valid local evidence files or import artifacts for this stage.",
        "Rerun the stage after supplying local dataset paths.",
    ],
    "unavailable_service": [
        "Verify that required local dependencies and service modules are available.",
        "Check stage configuration and retry once the service is available.",
    ],
    "obsidian_unconfigured": [
        "Configure the local Obsidian vault path if note synchronization is desired.",
        "Continue workflow execution without Obsidian synchronization.",
    ],
    "registry_unavailable": [
        "Verify that the durable workflow and entity registries are properly initialized.",
        "Check registry file permissions and storage availability.",
    ],
    "artifact_render_failed": [
        "Check artifact templates and input payload parameters for formatting issues.",
        "Verify template paths and re-run artifact generation.",
    ],
    "validation_failed": [
        "Inspect validation sprint and gate criteria against stage outputs.",
        "Adjust stage parameters or evidence inputs to satisfy validation gates.",
    ],
    "unexpected_exception": [
        "Review stage execution diagnostics and exception type.",
        "Inspect input payload parameters and rerun the stage if safe.",
    ],
}


def sanitize_failure_text(text: str) -> str:
    """Scrub sensitive paths, secrets, canaries, and tracebacks from failure text."""
    if not isinstance(text, str):
        return ""
    cleaned = _TRACEBACK_PATTERNS.sub("", text)
    cleaned = _SECRET_SHAPED.sub("<redacted-secret>", cleaned)
    cleaned = _CANARY_PATTERNS.sub("<redacted-canary>", cleaned)
    cleaned = _PATH_PATTERNS.sub("<redacted-path>", cleaned)
    cleaned = _EMAIL_PATTERNS.sub("<redacted-email>", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned[:256].strip()


def _sanitize_context(context: Mapping[str, Any] | None) -> dict[str, Any]:
    """Sanitize caller context to bounded, safe fields only."""
    if not isinstance(context, Mapping):
        return {}
    sanitized: dict[str, Any] = {}
    for key, val in context.items():
        key_str = str(key).strip().lower().replace("-", "_")
        if key_str not in ALLOWED_CONTEXT_KEYS or key_str in SECRET_KEY_NAMES:
            continue
        if isinstance(val, (int, float, bool)):
            sanitized[key_str] = val
        elif isinstance(val, str):
            clean_val = sanitize_failure_text(val)
            if "<redacted" not in clean_val and len(clean_val) <= 64:
                sanitized[key_str] = clean_val
    return sanitized


def classify_workflow_failure(
    stage_name: str,
    exc_or_error: Any,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify a workflow failure into a deterministic category with safe operator recovery guidance."""
    raw_str = str(exc_or_error or "").lower()
    error_type = exc_or_error.__class__.__name__ if isinstance(exc_or_error, BaseException) else type(exc_or_error).__name__ if not isinstance(exc_or_error, str) else "str"

    # 1. Unsafe path / traversal
    if re.search(
        r"\b(unsafe[_\s]+path|path[_\s]+traversal|unconfined[_\s]+path|outside[_\s]+(import[_\s]+surface|allowed[_\s]+directory)|traversal[_\s]+blocked|path[_\s]+escape)\b",
        raw_str,
    ) or (
        "path" in raw_str
        and any(re.search(rf"\b{w}\b", raw_str) for w in ("unsafe", "traversal", "unconfined", "escape", "rejected", "blocked"))
    ):
        category = "unsafe_path"
        severity = "critical"
        retryable = False
        recoverable = False
        action = True

    # 2. Safety policy blocks / live action / external mutation
    elif re.search(
        r"\b(blocked[_\s]+by[_\s]+safety|safety[_\s]+guard|safety[_\s]+policy|offline[_\s]+policy|live[_\s]+execution|live[_\s]+action|live[_\s]+provider|live[_\s]+credentials|external[_\s]+action|external[_\s]+mutation|mutation[_\s]+payload|unauthorized[_\s]+authority|safety_blocked)\b",
        raw_str,
    ) or (
        re.search(r"\bsafety\b", raw_str) and re.search(r"\b(blocked|guard|violation|policy)\b", raw_str)
    ) or (
        re.search(r"\blive\b", raw_str) and re.search(r"\b(provider|execution|action|credential|credentials|network|blocked|flag|mutation)\b", raw_str)
    ) or (
        re.search(r"\bmutation\b", raw_str) and re.search(r"\b(payload|external|blocked|disallowed|authority)\b", raw_str)
    ):
        category = "blocked_by_safety"
        severity = "critical"
        retryable = False
        recoverable = False
        action = True

    # 3. Unsupported parser
    elif re.search(
        r"\b(unsupported[_\s]+parser|unknown[_\s]+parser|parser[_\s]+not[_\s]+found)\b",
        raw_str,
    ) or (
        re.search(r"\bparser\b", raw_str) and any(re.search(rf"\b{w}\b", raw_str) for w in ("unsupported", "unknown", "invalid", "missing"))
    ) or raw_str.strip() in {"unsupported_parser", "unknown_parser"}:
        category = "unsupported_parser"
        severity = "error"
        retryable = False
        recoverable = True
        action = True

    # 4. No evidence
    elif re.search(
        r"\b(no[_\s]+evidence|missing[_\s]+evidence|evidence[_\s]+not[_\s]+found|evidence[_\s]+missing|no[_\s]+imports[_\s]+provided)\b",
        raw_str,
    ) or (
        re.search(r"\bevidence\b", raw_str) and any(re.search(rf"\b{w}\b", raw_str) for w in ("no", "missing", "no_", "none", "empty", "absent", "available"))
    ):
        category = "no_evidence"
        severity = "warning"
        retryable = True
        recoverable = True
        action = True

    # 5. Unavailable service / module
    elif re.search(
        r"\b(service[_\s]+module[_\s]+unavailable|service[_\s]+unavailable|unavailable[_\s]+service|dependency[_\s]+unavailable|module[_\s]+unavailable)\b",
        raw_str,
    ) or (
        "service_module_unavailable" in raw_str
    ) or (
        re.search(r"\bunavailable\b", raw_str) and any(re.search(rf"\b{w}\b", raw_str) for w in ("service", "module", "dependency", "temporary", "adapter", "provider", "component"))
    ):
        category = "unavailable_service"
        severity = "error"
        retryable = False
        recoverable = True
        action = True

    # 6. Obsidian unconfigured
    elif re.search(
        r"\b(obsidian[_\s]+(not[_\s]+configured|unconfigured|disabled|skipped|sync[_\s]+failed))\b",
        raw_str,
    ) or (
        re.search(r"\bobsidian\b", raw_str) and any(re.search(rf"\b{w}\b", raw_str) for w in ("not configured", "unconfigured", "missing", "skipped", "failed"))
    ):
        category = "obsidian_unconfigured"
        severity = "warning"
        retryable = False
        recoverable = True
        action = False

    # 7. Registry unavailable
    elif re.search(
        r"\b(registry[_\s]+(unavailable|missing|error|not[_\s]+found|failed|corrupt|corrupted|storage))\b",
        raw_str,
    ) or (
        re.search(r"\bregistry\b", raw_str)
        and any(
            re.search(rf"\b{w}\b", raw_str)
            for w in ("unavailable", "missing", "failed", "error", "not found", "corrupted", "corrupt", "storage", "connection")
        )
    ):
        category = "registry_unavailable"
        severity = "error"
        retryable = False
        recoverable = True
        action = True

    # 8. Artifact render failed
    elif re.search(
        r"\b(artifact[_\s]+render|render[_\s]+artifact|template[_\s]+render[_\s]+failed|artifact[_\s]+generation[_\s]+failed)\b",
        raw_str,
    ) or (
        re.search(r"\bartifact\b", raw_str) and any(re.search(rf"\b{w}\b", raw_str) for w in ("render", "template", "generation", "rendering", "failed"))
    ):
        category = "artifact_render_failed"
        severity = "error"
        retryable = False
        recoverable = True
        action = True

    # 9. Validation failed
    elif re.search(
        r"\b(validation[_\s]+failed|validation[_\s]+sprint[_\s]+failed|opportunity[_\s]+gate[_\s]+failed|gate[_\s]+check[_\s]+failed)\b",
        raw_str,
    ) or (
        re.search(r"\bvalidation\b", raw_str) and any(re.search(rf"\b{w}\b", raw_str) for w in ("failed", "failure", "rejected", "error", "sprint"))
    ):
        category = "validation_failed"
        severity = "error"
        retryable = False
        recoverable = True
        action = True

    # 10. Fallback conservative unexpected exception
    else:
        category = "unexpected_exception"
        severity = "error"
        retryable = False
        recoverable = False
        action = True

    # Safety invariant: safety blocks are strictly non-retryable and non-recoverable
    if category in {"blocked_by_safety", "unsafe_path"}:
        retryable = False
        recoverable = False
        severity = "critical"
        action = True

    # Construct stable, sanitized, non-reflective message
    sanitized_text = sanitize_failure_text(str(exc_or_error or ""))
    if sanitized_text and sanitized_text not in {"<redacted-secret>", "<redacted-path>", "<redacted-canary>"}:
        message = sanitized_text
    else:
        message = f"Stage '{stage_name}' failed: {CATEGORY_DESCRIPTIONS.get(category, 'an unexpected error occurred.')}"

    metadata = {
        "stage_name": str(stage_name)[:64],
        "error_type": error_type,
        **_sanitize_context(context),
    }

    return {
        "category": category,
        "severity": severity,
        "retryable": retryable and category not in {"blocked_by_safety", "unsafe_path"},
        "recoverable": recoverable,
        "operator_action_required": action,
        "message": message,
        "next_actions": list(CATEGORY_NEXT_ACTIONS.get(category, CATEGORY_NEXT_ACTIONS["unexpected_exception"])),
        "metadata": metadata,
    }
