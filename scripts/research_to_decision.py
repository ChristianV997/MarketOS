"""Build the existing client-safe validation report from bounded local evidence.

This is an offline/manual orchestration seam. It adapts sanitized local imports
into the repository's existing marketplace, supplier, consumer, benchmark, and
opportunity authorities; it does not add a scoring model or execution authority.
"""
from __future__ import annotations

import argparse
import csv
import errno
import hashlib
import ipaddress
import json
import os
import re
import stat as stat_module
import sys
import unicodedata
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence
from urllib.parse import unquote, urlparse

# Allow direct ``python scripts/research_to_decision.py`` execution from any cwd.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.adapters.research.consumer_attention import (
    import_csv as import_consumer_csv,
    import_json as import_consumer_json,
)
from backend.adapters.research.marketplace_trends import (
    import_csv as import_marketplace_csv,
    import_json as import_marketplace_json,
)
from backend.adapters.research.supplier_feasibility import (
    import_csv as import_supplier_csv,
    import_json as import_supplier_json,
)
from evaluation.commerce.benchmark_matrix import BenchmarkCandidate, build_benchmark_matrix
from evaluation.commerce.consumer_attention import build_report as build_consumer_report
from evaluation.commerce.marketplace_trends import build_report as build_marketplace_report
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.commerce.product_validation_report import generate as generate_product_report
from evaluation.commerce.public_market_benchmark import (
    build_public_market_benchmark,
    load_public_market_seed,
)
from evaluation.commerce.readiness import build_phase1_readiness
from evaluation.commerce.supplier_feasibility import build_report as build_supplier_report

MAX_FILE_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 128 * 1024
MAX_RECORDS = 100
MAX_INPUT_FILES = 24
MAX_TEXT = 240
MAX_EVIDENCE_DOCUMENT_BYTES = 256 * 1024
SUPPORTED_EVIDENCE_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".txt", ".json", ".png", ".jpg", ".jpeg"})
SUPPORTED_CURRENCIES = frozenset({"AUD", "CAD", "CNY", "EUR", "GBP", "JPY", "MXN", "USD"})
LIFECYCLE_STATES = frozenset({"candidate", "evidence_collected", "research_ready", "hold", "reject", "no_launch"})
PROMOTION_LIFECYCLE_STATES = (
    "discovered",
    "normalized",
    "screened",
    "evidence_incomplete",
    "supplier_claimed",
    "supplier_documented",
    "offer_conflicted",
    "lane_verified",
    "sample_required",
    "direct_ship_required",
    "rma_required",
    "economics_ready",
    "competition_ready",
    "promotion_blocked",
    "launch_candidate",
    "launch_authorized_false",
    "manually_approved",
    "live_validated",
)
DECISION_OUTCOMES = frozenset(
    {"reject", "hold_for_manual_review", "needs_evidence", "deferred", "candidate_only", "launch_candidate"}
)
MAX_TRANSITIONS_PER_CANDIDATE = 24
OFFER_APPROVAL_STATES = (
    "candidate",
    "contacted",
    "information_received",
    "quote_verified",
    "terms_verified",
    "sample_ordered",
    "sample_passed",
    "direct_ship_tested",
    "RMA_tested",
    "approved",
    "suspended",
    "rejected",
)
EVIDENCE_STATES = frozenset({"observed", "manual", "fixture", "assumed", "unavailable", "malformed", "blocked"})
OBSERVATION_KINDS = frozenset({"policy", "reviewed_url", "competition_observation", "social_observation", "catalog", "pdf_derived", "form"})
MARKET_LANE_FIELDS = (
    "origin_country",
    "ship_from_country",
    "warehouse",
    "destination_country",
    "destination_state_region",
    "postal_code_assumption",
    "currency",
    "tax_model",
    "duty_model",
    "brokerage_model",
    "shipping_model",
    "return_destination",
    "return_cost_payer",
    "payment_method",
    "compliance_requirements",
    "customer_support_language",
    "marketplace_eligibility",
    "delivery_promise",
    "evidence_state",
    "confidence",
)
OFFER_FIELDS = frozenset(
    {
        "offer_id",
        "supplier_offer_id",
        "candidate_id",
        "supplier",
        "supplier_product_id",
        "supplier_sku",
        "sku",
        "variant",
        "unit_cost",
        "price",
        "currency",
        "price_valid_until",
        "valid_until",
        "inventory_status",
        "inventory_quantity",
        "stock",
        "warehouse_region",
        "warehouse",
        "destination_region",
        "destination_country",
        "delivery_min_days",
        "delivery_max_days",
        "p50_delivery_days",
        "p95_delivery_days",
        "tracking_available",
        "tracking",
        "blind_shipping",
        "packaging",
        "return_address",
        "return_cost_payer",
        "warranty",
        "rma_process",
        "refund_sla_days",
        "support_owner",
        "support_response_sla_hours",
        "dropshipping_permission",
        "marketplace_permission",
        "sample_state",
        "contract_evidence",
        "policy_evidence",
        "backup_supplier",
        "approval_state",
        "evidence_state",
        "source_type",
        "source",
        "source_url",
        "source_reference",
        "document_reference",
        "extraction_method",
        "captured_at",
        "observed_at",
        "expires_at",
        "source_confidence",
        "confidence",
        "query",
        "supplier_title",
        "supplier_brand",
        "variant_count",
        "moq",
        "shipping_cost",
        "shipping_method",
        "estimated_landed_cost",
        "fulfillment_method",
        "human_confirmed",
        "human_reviewed",
        "field_provenance",
        "warnings",
    }
)
TRUE_TEXT = frozenset({"true", "yes", "y", "1"})
FALSE_TEXT = frozenset({"false", "no", "n", "0"})
SENSITIVE_KEY = re.compile(r"(api[_-]?key|authorization|body|cookie|header|html|password|payload|private[_-]?key|raw|secret|token|trace|log)", re.I)
SENSITIVE_VALUE = re.compile(r"(bearer\s+|sk_(?:live|test)_|gh[pousr]_?|xox[baprs]-|-----BEGIN)", re.I)


class ResearchToDecisionError(ValueError):
    """Raised when a local evidence packet cannot be accepted safely."""


def _text(value: Any, field: str, *, required: bool = False) -> str:
    result = " ".join(str(value or "").split())
    if required and not result:
        raise ResearchToDecisionError(f"{field} is required")
    if len(result) > MAX_TEXT:
        raise ResearchToDecisionError(f"{field} exceeds {MAX_TEXT} characters")
    return result


def _contains_secret(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(SENSITIVE_KEY.search(str(key)) or _contains_secret(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_secret(item) for item in value)
    return bool(SENSITIVE_VALUE.search(str(value))) if value is not None else False


def _reject_html(raw: str) -> None:
    if raw.lstrip().lower().startswith(("<", "<!doctype")):
        raise ResearchToDecisionError("HTML or raw page content is not accepted")


def _is_unsafe_relative_path(text: str) -> bool:
    """True for a rooted, absolute, drive-qualified, UNC or ``..``-traversing path.

    Judged under POSIX *and* Windows rules on every platform: a manifest authored
    on one OS must be accepted or rejected identically on the other. Using the
    host ``Path`` alone let ``..\\outside.json`` through on POSIX (where ``\\`` is an
    ordinary character) while rejecting it on Windows.
    """
    if ".." in text.replace("\\", "/").split("/"):
        return True
    for flavour in (PurePosixPath, PureWindowsPath):
        candidate = flavour(text)
        if candidate.is_absolute() or candidate.drive or candidate.root:
            return True
    return False


def _parse_url(value: str, error: str):
    """``urlparse`` that fails closed: a malformed (e.g. unterminated IPv6) URL raises the module error."""
    try:
        return urlparse(value)
    except ValueError:
        raise ResearchToDecisionError(error) from None


_HOST_LABEL = re.compile(r"[A-Za-z0-9_](?:[A-Za-z0-9_-]*[A-Za-z0-9_])?")


def _resolve_root(path: Path | str, label: str) -> Path:
    """``Path.resolve()`` for an operator-supplied root that fails closed.

    A symlink loop raises a bare RuntimeError (3.11/3.12) whose text echoes the path; an
    over-long or unencodable name raises OSError/ValueError. Neither may escape as-is.
    """
    try:
        return Path(path).resolve()
    except (RuntimeError, OSError, ValueError):
        raise ResearchToDecisionError(f"{label} could not be resolved safely") from None


def _is_well_formed_http_host(hostname: str | None) -> bool:
    """True only for a real DNS name (IDN allowed), a dotted-quad IPv4 or a bracketed IPv6 literal.

    A non-ASCII host is judged by its IDNA form, because that is the host a client connects to:
    ``http://\uff0e\uff0e/x`` folds to ``..``, and soft-hyphen, zero-width and bidi characters are
    dropped or refused rather than hiding in the text. Whitespace, controls, backslash, percent,
    shell and URL punctuation, empty or hyphen-edged labels, and ambiguous numeric hosts such as
    ``0x7f.1`` or ``999.1.1.1`` are malformed.
    """
    if not hostname:
        return False
    # Invisible and format characters (soft hyphen, zero-width, bidi) are dropped by IDNA, so two
    # visibly different strings would name one host; refuse them instead of normalising them away.
    if any(unicodedata.category(char) in {"Cc", "Cf", "Zs", "Zl", "Zp"} for char in hostname):
        return False
    if ":" in hostname:  # urlsplit strips the brackets of an IPv6 literal
        if "%" in hostname:  # IPv6Address would accept a '%zone' scope id; it is never a reference host
            return False
        try:
            ipaddress.IPv6Address(hostname)
        except ValueError:
            return False
        return True
    try:
        ascii_host = hostname.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return False
    labels = ascii_host[:-1].split(".") if ascii_host.endswith(".") else ascii_host.split(".")
    if not all(_HOST_LABEL.fullmatch(label) for label in labels):
        return False
    last = labels[-1].lower()
    if last.isdigit() or last.startswith("0x"):  # numeric-looking: only a strict dotted quad is a host
        try:
            ipaddress.IPv4Address(".".join(labels))
        except ValueError:
            return False
    return True


def _http_authority_is_safe(parsed) -> bool:
    """Well-formed host, a valid port, no userinfo (not even an empty one) and no stray brackets."""
    try:
        port = parsed.port
    except ValueError:
        return False
    if port == 0 or not parsed.netloc or "@" in parsed.netloc:
        return False
    if "[" in parsed.netloc and ":" not in (parsed.hostname or ""):  # only an IPv6 literal may be bracketed
        return False
    return _is_well_formed_http_host(parsed.hostname)


def _url_path_has_traversal(path: str) -> bool:
    """A ``..`` segment in a URL path, however separated, percent-encoded (even twice) or ``;``-suffixed."""
    decoded = path
    for _ in range(3):
        step = unquote(decoded)
        if step == decoded:
            break
        decoded = step
    return any(segment.split(";", 1)[0].strip() == ".." for segment in re.split(r"[/\\]", decoded))


def _reference_text(value: Any, field: str, *, required: bool = True, allow_url_query: bool = False) -> str:
    # CR/LF are rejected on the raw value: _text() would otherwise fold them into a space and
    # let a header-shaped tail ("x\r\nHost: evil") through as ordinary text.
    if isinstance(value, str) and any(char in value for char in "\r\n"):
        raise ResearchToDecisionError(f"{field} must be a safe reference")
    reference = _text(value, field, required=required)
    if not reference:
        return reference
    # Reject NUL before URL query/fragment stripping so hidden unsafe bytes
    # cannot be silently normalized out of an operator-supplied reference.
    if "\x00" in reference:
        raise ResearchToDecisionError(f"{field} must be a safe reference")
    try:
        reference.encode("utf-8")  # a lone surrogate would otherwise escape later, when the reference is hashed
    except UnicodeEncodeError:
        raise ResearchToDecisionError(f"{field} must be a safe reference") from None
    try:
        parsed = urlparse(reference)
        # ``port`` raises ValueError for a non-numeric or out-of-range port, and
        # ``urlparse`` for a malformed bracketed (IPv6) host; both must fail closed
        # as a ResearchToDecisionError, never escape as a bare ValueError.
        if parsed.scheme in {"http", "https"}:
            parsed.port
    except ValueError:
        raise ResearchToDecisionError(f"{field} must be a safe reference") from None
    if parsed.scheme in {"http", "https"}:
        if not _http_authority_is_safe(parsed) or parsed.username or parsed.password:
            raise ResearchToDecisionError(f"{field} must be a safe reference")
        if (parsed.query or parsed.fragment) and not allow_url_query:
            raise ResearchToDecisionError(f"{field} must not contain a query or fragment")
        if allow_url_query:
            reference = parsed._replace(query="", fragment="").geturl()
    elif "://" in reference or (parsed.scheme and parsed.scheme not in {"fixture", "file", "manual"}):
        # Also covers a URL whose scheme text was damaged by whitespace folding (\"ht\ttp://x\"): it no
        # longer parses as a scheme, but a local reference never contains "://".
        raise ResearchToDecisionError(f"{field} must be a safe reference")
    path_text = parsed.path or reference
    if parsed.scheme in {"http", "https"}:
        # A URL path is not a filesystem path: its leading "/" is the URL root, not an
        # absolute local path (host-OS ``Path.is_absolute`` disagreed across platforms).
        # Traversal segments are still rejected, and hostnames like '..' or '.' are rejected.
        unsafe_path = (
            _url_path_has_traversal(path_text)
            or parsed.hostname in {".", ".."}
            or ".." in parsed.netloc.replace("\\", "/").split("/")
            or any(part in {".", ".."} for part in parsed.netloc.split(":"))
        )
    else:
        unsafe_path = _is_unsafe_relative_path(path_text)
    if unsafe_path or any(char in reference for char in "<>\r\n\x00"):
        # \x00 specifically: Path.resolve() raises an unhandled ValueError
        # ("embedded null byte") deep inside posixpath's realpath, not a
        # ResearchToDecisionError -- reproduced via
        # _supplier_document_evidence_bindings -> _resolve -> .resolve().
        # Not a containment bypass (nothing is ever read), but an
        # unhandled exception is not the fail-closed contract every other
        # rejection in this module honors; reject it here instead, before
        # any of this reference's later checks or filesystem calls run.
        raise ResearchToDecisionError(f"{field} must be a safe reference")
    return reference


def _evidence_reference(value: Any, field: str, *, allow_url_query: bool = False) -> str:
    reference = _reference_text(value, field, allow_url_query=allow_url_query)
    return f"evidence:{hashlib.sha256(reference.encode('utf-8')).hexdigest()[:16]}"


def _operator_supplier_confirmations(values: Sequence[Sequence[str]]) -> set[tuple[str, str, str]]:
    if not isinstance(values, (list, tuple)) or len(values) > MAX_RECORDS:
        raise ResearchToDecisionError("operator supplier confirmations must be a bounded list")
    confirmations: set[tuple[str, str, str]] = set()
    for value in values:
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ResearchToDecisionError("operator supplier confirmation requires offer_id, exact_sku, and document_reference")
        offer_id = _text(value[0], "operator_confirmation.offer_id", required=True)
        exact_sku = _text(value[1], "operator_confirmation.exact_sku", required=True)
        reference = _reference_text(value[2], "operator_confirmation.document_reference")
        confirmation = (offer_id, exact_sku, reference)
        if confirmation in confirmations:
            raise ResearchToDecisionError("duplicate operator supplier confirmation")
        confirmations.add(confirmation)
    return confirmations


# Stdlib-only Win32 access (``ctypes`` + ``msvcrt``) -- no ``pywin32``.
# Windows has no ``O_NOFOLLOW``-equivalent ``os.open()`` flag, but
# ``CreateFileW`` with ``FILE_FLAG_OPEN_REPARSE_POINT`` is the documented
# Win32 primitive that plays the same role: it opens a reparse point
# (symlink/junction) *as itself*, atomically, instead of following it, so
# the resulting handle can be inspected and rejected before any bytes are
# read through it. ``FILE_FLAG_BACKUP_SEMANTICS`` is required alongside it
# so the call also succeeds for directory reparse points (junctions),
# which are rejected explicitly below rather than by the open failing.
#
# ``ctypes.wintypes`` is pure Python (plain type aliases) and importable
# on every platform; only ``ctypes.WinDLL`` itself requires real Windows.
# The constants, struct, and function below are therefore defined
# unconditionally so their branching/cleanup logic can be exercised by
# deterministic tests on any platform (via ``_win32_kernel32_dll``, the
# one seam a test replaces) -- only the actual DLL bind is deferred to
# first real use, which happens only when ``_open_verified_evidence_file``
# dispatches to this path on genuine Windows.
import ctypes
from ctypes import wintypes

_WIN32_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_WIN32_GENERIC_READ = 0x80000000
_WIN32_FILE_SHARE_READ = 0x00000001
_WIN32_FILE_SHARE_WRITE = 0x00000002
_WIN32_FILE_SHARE_DELETE = 0x00000004
_WIN32_OPEN_EXISTING = 3
_WIN32_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_WIN32_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_WIN32_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_WIN32_FILE_ATTRIBUTE_DIRECTORY = 0x00000010


class _Win32ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


def _win32_get_last_error() -> int | None:
    """``ctypes.get_last_error()`` is itself Windows-only (undefined on
    POSIX ctypes builds); this indirection is purely diagnostic message
    text and degrades to ``None`` off-Windows so the branching logic
    around it stays exercisable by tests on any platform. Real Windows
    always has the attribute, so production behavior is unaffected."""
    getter = getattr(ctypes, "get_last_error", None)
    return getter() if getter is not None else None


_win32_kernel32_dll_cache: Any = None


def _win32_kernel32_dll() -> Any:
    """Bind and cache the real ``kernel32`` DLL. Isolated in its own
    function -- rather than a module-level ``ctypes.WinDLL(...)`` call --
    so tests on non-Windows platforms (where ``ctypes.WinDLL`` does not
    exist at all) can monkeypatch this one seam and exercise the rest of
    ``_open_verified_evidence_file_windows`` for real, instead of every
    Windows-only line being unreachable/untestable dead code elsewhere."""
    global _win32_kernel32_dll_cache
    if _win32_kernel32_dll_cache is None:
        dll = ctypes.WinDLL("kernel32", use_last_error=True)
        # HANDLE is pointer-sized. Without explicit argtypes/restype,
        # ctypes defaults to a 32-bit ``c_int`` return, which
        # truncates/corrupts real Win64 handle values -- required for
        # correctness, not style, even though only reachable on Windows.
        dll.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        dll.CreateFileW.restype = wintypes.HANDLE
        dll.GetFileInformationByHandle.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_Win32ByHandleFileInformation),
        ]
        dll.GetFileInformationByHandle.restype = wintypes.BOOL
        dll.CloseHandle.argtypes = [wintypes.HANDLE]
        dll.CloseHandle.restype = wintypes.BOOL
        _win32_kernel32_dll_cache = dll
    return _win32_kernel32_dll_cache


def _open_verified_evidence_file_windows(resolved: Path, *, label: str) -> tuple[int, os.stat_result]:
    """Windows counterpart of the POSIX open in
    ``_open_verified_evidence_file``, using the same single-handle
    contract: one ``CreateFileW`` call backs both the reparse-point/
    directory rejection and the bytes that get hashed, so nothing between
    the check and the read can swap what was checked.

    UNVERIFIED ON REAL WINDOWS: this repository has no Windows CI runner
    (every workflow under ``.github/workflows/`` runs on ``ubuntu-latest``
    only, confirmed by direct inspection) and this development environment
    is Linux-only, so this function has never actually executed against
    the real Win32 API in this project. It is written strictly from
    documented ``CreateFileW`` / ``GetFileInformationByHandle`` semantics
    (reparse points are opened, not followed, when
    ``FILE_FLAG_OPEN_REPARSE_POINT`` is set; the resulting handle's
    attributes reveal that fact). Treat this as a reviewed-but-execution-
    unverified implementation, not a proven one, until it runs on a real
    Windows host. Only ``_win32_kernel32_dll`` and the platform's
    ``msvcrt`` module are Windows-only; everything else in this function
    is plain Python and is exercised directly by tests on any platform via
    those two seams.
    """
    import msvcrt

    kernel32 = _win32_kernel32_dll()
    handle = kernel32.CreateFileW(
        str(resolved),
        _WIN32_GENERIC_READ,
        _WIN32_FILE_SHARE_READ | _WIN32_FILE_SHARE_WRITE | _WIN32_FILE_SHARE_DELETE,
        None,
        _WIN32_OPEN_EXISTING,
        _WIN32_FILE_FLAG_BACKUP_SEMANTICS | _WIN32_FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle is None or handle == _WIN32_INVALID_HANDLE_VALUE:
        error_code = _win32_get_last_error()
        raise ResearchToDecisionError(f"{label} could not be opened: Win32 error {error_code}")
    fd = -1
    try:
        info = _Win32ByHandleFileInformation()
        # ``ctypes.pointer(info)`` (not the lighter ``byref(info)``) so the
        # same call is dereferenceable from a plain-Python fake in tests,
        # not only when routed through a real C call.
        if not kernel32.GetFileInformationByHandle(handle, ctypes.pointer(info)):
            error_code = _win32_get_last_error()
            raise ResearchToDecisionError(f"{label} could not be inspected: Win32 error {error_code}")
        if info.dwFileAttributes & _WIN32_FILE_ATTRIBUTE_REPARSE_POINT:
            raise ResearchToDecisionError(f"{label} must not be a symlink")
        if info.dwFileAttributes & _WIN32_FILE_ATTRIBUTE_DIRECTORY:
            raise ResearchToDecisionError(f"{label} must be a regular file")
        # Windows' attribute model has no direct equivalent of POSIX
        # S_ISREG; "not a directory and not a reparse point" is the
        # closest available same-handle approximation of "regular file"
        # and is the same test a caller could not bypass by racing the
        # path, since it reads the handle, not the path.
        # os.O_BINARY (Windows-only; absent on this Linux sandbox, hence
        # getattr) is passed explicitly rather than relying on
        # _open_osfhandle's CRT-documented binary-unless-O_TEXT default:
        # hashed evidence bytes must never go through CRLF/Ctrl-Z text-mode
        # translation, and this removes any doubt rather than depending on
        # an unverified-on-real-Windows default.
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        # open_osfhandle takes ownership of the Win32 handle once it
        # succeeds; CloseHandle must not also run below, or the fd's
        # eventual os.close() would double-close the same handle.
        handle = None
        file_stat = os.fstat(fd)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        elif handle is not None:
            kernel32.CloseHandle(handle)
        raise
    return fd, file_stat


def _open_verified_evidence_file(resolved: Path, *, label: str) -> tuple[int, os.stat_result]:
    """Open ``resolved`` exactly once and validate the *same open file
    descriptor* that will be hashed -- never a separate stat-by-path call
    followed by a separate open-by-path call. That split is the actual
    TOCTOU gap: two filesystem accesses to the same path string, with no
    guarantee the second one still sees what the first one measured. This
    function performs a single open and derives every subsequent check
    (regular-file status, size) from that resulting descriptor, so nothing
    between the check and the read can change what was checked -- both
    operate on the same open kernel object, not on the path.

    On POSIX, ``os.O_NOFOLLOW`` is additionally included, which makes the
    open itself atomically fail (``ELOOP``) if the final path component is
    a symlink at the instant of the call -- closing the window between the
    caller's earlier per-component symlink walk and this open.

    On Windows, ``os.open()`` exposes no ``O_NOFOLLOW``-equivalent flag at
    all (Python does not define ``os.O_NOFOLLOW`` there), so this function
    instead uses ``CreateFileW`` with ``FILE_FLAG_OPEN_REPARSE_POINT``
    directly via ``ctypes`` (stdlib-only, no ``pywin32``) -- see
    ``_open_verified_evidence_file_windows``. That closes the same
    final-component race POSIX closes, by the same shape of mechanism: one
    handle, opened without following a terminal reparse point, inspected
    and read through itself. It is, however, UNVERIFIED BY EXECUTION ON
    REAL WINDOWS in this project (no Windows CI runner exists in this
    repository, and this sandbox is Linux-only) -- see that function's
    docstring for the precise scope of that caveat.

    On every platform, the caller's pre-open per-component symlink/
    reparse-point walk remains the only mitigation for an *intermediate*
    directory being swapped for a reparse point mid-walk; Python's
    standard library exposes no portable ``openat``-style relative open to
    close that structurally distinct race, and it stays disclosed, not
    fixed (see ``_supplier_document_evidence_bindings`` for the full
    disclosure). This function's guarantee is narrowly about the *final*
    path component tested against the *same* handle used to read.
    """
    if sys.platform == "win32":
        return _open_verified_evidence_file_windows(resolved, label=label)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    nonblocking = hasattr(os, "O_NONBLOCK")
    if nonblocking:
        # A plain blocking open() on a FIFO with no writer on the other
        # end hangs forever -- a real denial-of-service the moment a
        # caller places a named pipe inside the evidence root (confirmed
        # by direct reproduction). O_NONBLOCK makes the open return
        # immediately instead; the descriptor is then confirmed to be a
        # regular file (a FIFO fails that check and is rejected) and the
        # flag is cleared again below before any read happens, since
        # nonblocking mode has no defined effect on a genuine regular file.
        flags |= os.O_NONBLOCK
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        fd = os.open(resolved, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ResearchToDecisionError(f"{label} must not be a symlink") from exc
        raise ResearchToDecisionError(f"{label} could not be opened: {exc.strerror or exc}") from exc
    try:
        file_stat = os.fstat(fd)
        if not stat_module.S_ISREG(file_stat.st_mode):
            raise ResearchToDecisionError(f"{label} must be a regular file")
        if nonblocking:
            import fcntl

            current_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, current_flags & ~os.O_NONBLOCK)
    except BaseException:
        os.close(fd)
        raise
    return fd, file_stat


def _supplier_document_evidence_bindings(
    values: Sequence[Sequence[str]],
    *,
    evidence_root: Path | None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Bind a manual document reference to real, on-disk evidence bytes.

    This proves document *byte integrity* only: that the file at
    ``reference`` (resolved under ``evidence_root``, never outside it)
    hashes to the operator-supplied digest. It is deliberately a separate,
    additional signal from ``_operator_supplier_confirmations``'s
    ``human_confirmed`` attestation -- a verified digest never sets
    ``human_confirmed`` by itself, and ``human_confirmed`` never implies a
    verified digest. Neither implies supplier identity or live validation;
    both remain local, offline claims about evidence the operator supplied.
    Raw document content is read only to hash it and is never retained,
    logged, or included in any returned structure.

    Secure-read guarantee: the file is opened exactly once
    (``_open_verified_evidence_file``), and the regular-file check, size
    cap, and hashed bytes all come from that single open descriptor --
    there is no separate stat-then-open sequence against the path string
    for the file itself. On POSIX this additionally uses ``O_NOFOLLOW``,
    so a symlink swapped in for the final path component between the
    walk-check below and the open fails the open itself rather than being
    silently followed. On Windows, the same final-component race is closed
    by a different, stdlib-only mechanism (``ctypes``-based ``CreateFileW``
    with ``FILE_FLAG_OPEN_REPARSE_POINT``; no ``pywin32``) that opens a
    reparse point as itself rather than following it and inspects/reads
    that same handle -- see ``_open_verified_evidence_file_windows``. That
    Windows path is reviewed against documented Win32 semantics but is
    UNVERIFIED BY EXECUTION ON REAL WINDOWS: this repository has no
    Windows CI runner (every workflow runs on ``ubuntu-latest``) and this
    development sandbox is Linux-only, so treat the Windows final-
    component guarantee as designed-and-reviewed, not proven, until it
    runs on a real Windows host. This is still NOT "race-free" in an
    unqualified sense on either platform: the per-component walk-check
    below for *intermediate* directories (a symlinked parent) has its own,
    structurally unavoidable race without ``openat``-style relative opens,
    which Python's standard library does not portably expose on either
    platform -- disclosed, not fixed. What IS eliminated for the final
    file itself, on both POSIX (by kernel enforcement) and Windows (by a
    same-handle check that is correct by design but not yet executed on
    real Windows), is the split between "checked via the path" and "read
    via the path", which was the concrete, reproduced gap.
    """
    if not isinstance(values, (list, tuple)) or len(values) > MAX_RECORDS:
        raise ResearchToDecisionError("supplier document evidence bindings must be a bounded list")
    if not values:
        return {}
    if evidence_root is None:
        raise ResearchToDecisionError("supplier document evidence bindings require an evidence root")
    root = _resolve_root(evidence_root, "supplier evidence root")
    if not root.is_dir():
        raise ResearchToDecisionError("supplier evidence root does not exist or is not a directory")
    bindings: dict[tuple[str, str], dict[str, Any]] = {}
    for value in values:
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            raise ResearchToDecisionError("supplier document evidence binding requires offer_id, exact_sku, reference, and digest")
        offer_id = _text(value[0], "document_evidence.offer_id", required=True)
        exact_sku = _text(value[1], "document_evidence.exact_sku", required=True)
        # ``reference`` must be byte-identical to the offer's own declared
        # source_reference/document_reference (the same string
        # --confirm-supplier-document matches against) so a verified digest
        # binds to the *specific reference the offer claims*, not merely a
        # same-named file. It goes through the same _reference_text safety
        # checks as that existing confirmation path (fixture/file/manual
        # scheme allowlist, no absolute path, no "..", no control chars),
        # then the scheme prefix (if any) is stripped to resolve a real,
        # bounded local file under evidence_root.
        reference = _reference_text(value[2], "document_evidence.reference")
        expected_digest = _text(value[3], "document_evidence.digest", required=True).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
            raise ResearchToDecisionError("document_evidence.digest must be a 64-character hex sha256 digest")
        key = (offer_id, exact_sku)
        if key in bindings:
            raise ResearchToDecisionError(f"duplicate supplier document evidence binding for offer {offer_id}/{exact_sku}")
        relative_path = urlparse(reference).path or reference
        # An http(s) reference is accepted by _reference_text with an absolute URL path ("/bin/x.pdf");
        # as a local evidence path that must be rejected *before* the walk below, which would
        # otherwise call is_symlink() on host paths outside the evidence root (an existence oracle).
        if _is_unsafe_relative_path(relative_path):
            raise ResearchToDecisionError("document_evidence.reference must remain relative to the manifest")
        # Checked on the *unresolved* path, walking every component: once
        # _resolve() calls Path.resolve() it follows symlinks and returns
        # the real target, which is never itself a symlink -- so a symlink
        # check after resolving would be a no-op. This must run first.
        walked = root
        for part in Path(relative_path).parts:
            walked = walked / part
            try:
                symlink = walked.is_symlink()
            except OSError:  # e.g. a multibyte component over 255 bytes; the platform error echoes the path
                raise ResearchToDecisionError("document_evidence.reference could not be resolved safely") from None
            if symlink:
                raise ResearchToDecisionError("document_evidence.reference must not be a symlink")
        resolved = _resolve(root, relative_path, label="document_evidence.reference")
        if resolved.suffix.lower() not in SUPPORTED_EVIDENCE_DOCUMENT_EXTENSIONS:
            raise ResearchToDecisionError(f"document_evidence.reference has an unsupported format: {resolved.suffix or 'none'}")
        # Open exactly once; every check below (regular-file, size, and the
        # bytes that get hashed) comes from that same descriptor -- see
        # _open_verified_evidence_file's docstring for the exact guarantee
        # and its disclosed Windows/intermediate-symlink limitations.
        fd, file_stat = _open_verified_evidence_file(resolved, label="document_evidence.reference")
        try:
            if file_stat.st_size > MAX_EVIDENCE_DOCUMENT_BYTES:
                raise ResearchToDecisionError(f"document_evidence.reference exceeds {MAX_EVIDENCE_DOCUMENT_BYTES} bytes")
            with os.fdopen(fd, "rb") as evidence_file:
                fd = -1  # evidence_file now owns the descriptor; do not close it twice
                document_bytes = evidence_file.read(MAX_EVIDENCE_DOCUMENT_BYTES + 1)
        finally:
            if fd >= 0:
                os.close(fd)
        if len(document_bytes) > MAX_EVIDENCE_DOCUMENT_BYTES:
            raise ResearchToDecisionError(f"document_evidence.reference exceeds {MAX_EVIDENCE_DOCUMENT_BYTES} bytes")
        size = len(document_bytes)
        actual_digest = hashlib.sha256(document_bytes).hexdigest()
        if actual_digest != expected_digest:
            raise ResearchToDecisionError(f"document_evidence.reference content digest mismatch for offer {offer_id}/{exact_sku}")
        bindings[key] = {"reference": reference, "document_digest": actual_digest, "document_size_bytes": size}
    return bindings


def _warning_values(value: Any, field: str) -> list[str]:
    if value in (None, ""):
        return []
    values = value if isinstance(value, list) else [value]
    if not all(isinstance(item, str) for item in values):
        raise ResearchToDecisionError(f"{field} must be a bounded list of strings")
    if len(values) > 12:
        raise ResearchToDecisionError(f"{field} has too many entries")
    return sorted({_text(item, field, required=True) for item in values})


def _parse_timezone(value: Any, field: str) -> str:
    result = _text(value, field, required=True)
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchToDecisionError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ResearchToDecisionError(f"{field} must include a timezone")
    return result


def _parse_capture_time(value: Any) -> str:
    return _parse_timezone(value, "captured_at")


def _number(value: Any, field: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ResearchToDecisionError(f"{field} must be numeric") from exc
    if minimum is not None and result < minimum or maximum is not None and result > maximum:
        raise ResearchToDecisionError(f"{field} is outside its allowed range")
    return result


def _text_list(value: Any, field: str, *, required: bool = False) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        values = []
    if required and not values:
        raise ResearchToDecisionError(f"{field} is required")
    if len(values) > 12 or not all(isinstance(item, str) for item in values):
        raise ResearchToDecisionError(f"{field} must be a bounded list of strings")
    return [_text(item, field) for item in values]


def _resolve(base_dir: Path, value: Any, *, label: str) -> Path:
    raw = _text(value, label, required=True)
    if "\x00" in raw:
        # Path.resolve() below raises an unhandled ValueError ("embedded
        # null byte") deep inside posixpath's realpath rather than the
        # ResearchToDecisionError every other rejection in this module
        # produces -- reproduced via supplier_inputs.path,
        # observation_inputs.path, and document_evidence.reference, all
        # three of which share this function. Not a containment bypass
        # (nothing is ever read before this point), but an unhandled
        # exception is not this module's fail-closed contract.
        raise ResearchToDecisionError(f"{label} must not contain a NUL byte")
    if _is_unsafe_relative_path(raw):
        raise ResearchToDecisionError(f"{label} must remain relative to the manifest")
    candidate = Path(raw)
    try:
        resolved = (base_dir / candidate).resolve()
        resolved_base = base_dir.resolve()
        inside = resolved_base in resolved.parents
        is_file = inside and resolved.is_file()
    except (RuntimeError, OSError, ValueError):
        # A symlink loop (RuntimeError), an over-long component (OSError, e.g. a multibyte name
        # over 255 bytes) or a lone surrogate (UnicodeEncodeError) must fail closed with this
        # module's error, not escape bare. Never echo the path: the platform error text does.
        raise ResearchToDecisionError(f"{label} could not be resolved safely") from None
    if not inside:
        raise ResearchToDecisionError(f"{label} escapes the manifest directory")
    if not is_file:
        raise ResearchToDecisionError(f"{label} does not exist")
    return resolved


def _raw_records(path: Path) -> tuple[list[Mapping[str, Any]], str]:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ResearchToDecisionError(f"input exceeds {MAX_FILE_BYTES} bytes")
    raw_text = path.read_text(encoding="utf-8-sig")
    _reject_html(raw_text)
    if path.suffix.lower() == ".csv":
        rows = list(csv.DictReader(raw_text.splitlines()))
        return [row for row in rows if isinstance(row, Mapping)], "csv"
    try:
        value = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ResearchToDecisionError(f"malformed JSON input: {path.name}") from exc
    if _contains_secret(value):
        raise ResearchToDecisionError(f"secret-like input rejected: {path.name}")
    if isinstance(value, list):
        rows = value
    elif isinstance(value, Mapping):
        rows = next((value[key] for key in ("records", "items", "products", "offers", "results", "reviews", "comments", "ads") if isinstance(value.get(key), list)), [value])
    else:
        raise ResearchToDecisionError("JSON input must be an object or array")
    if not all(isinstance(row, Mapping) for row in rows):
        raise ResearchToDecisionError(f"input rows must be objects: {path.name}")
    return list(rows), "json"


def _candidate_id(row: Mapping[str, Any]) -> str:
    return _text(row.get("candidate_id") or row.get("product_id") or row.get("item_id") or row.get("sku"), "candidate_id")


def _validate_rows(rows: list[Mapping[str, Any]], *, label: str, role: str) -> None:
    if len(rows) > MAX_RECORDS:
        raise ResearchToDecisionError(f"{label} exceeds {MAX_RECORDS} records")
    seen: set[str] = set()
    for row in rows:
        if _contains_secret(row):
            raise ResearchToDecisionError(f"secret-like row rejected: {label}")
        candidate_id = _candidate_id(row)
        if not candidate_id:
            raise ResearchToDecisionError(f"missing candidate_id in {label}")
        discriminator = str(
            row.get("supplier_sku") or row.get("sku") or row.get("source_url") or row.get("url") or row.get("content_title") or row.get("hook") or row.get("price") or "row"
        )
        identity = f"{candidate_id}:{discriminator}" if role in {"supplier", "marketplace", "consumer_attention"} else json.dumps(row, sort_keys=True)
        if identity in seen:
            raise ResearchToDecisionError(f"duplicate evidence identity in {label}: {candidate_id}")
        seen.add(identity)


def _currency(value: Any) -> str:
    currency = _text(value, "lane.currency", required=True).upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise ResearchToDecisionError(f"unsupported currency: {currency}")
    return currency


def _lane(manifest: Mapping[str, Any]) -> dict[str, Any]:
    lane = manifest.get("lane")
    if not isinstance(lane, Mapping):
        raise ResearchToDecisionError("lane is required")
    missing = [field for field in MARKET_LANE_FIELDS if field not in lane]
    if missing:
        raise ResearchToDecisionError(f"lane is missing required fields: {', '.join(missing)}")
    destination = _text(lane.get("destination_country"), "lane.destination_country", required=True)
    if destination.lower() in {"unknown", "unsupported", "n/a", "none"}:
        raise ResearchToDecisionError("lane.destination is unsupported")
    evidence_state = _text(lane.get("evidence_state"), "lane.evidence_state", required=True)
    if evidence_state not in EVIDENCE_STATES:
        raise ResearchToDecisionError(f"unsupported lane evidence_state: {evidence_state}")
    result: dict[str, Any] = {
        "origin_country": _text(lane.get("origin_country"), "lane.origin_country", required=True),
        "ship_from_country": _text(lane.get("ship_from_country"), "lane.ship_from_country", required=True),
        "warehouse": _text(lane.get("warehouse"), "lane.warehouse", required=True),
        "destination_country": destination,
        "destination_state_region": _text(lane.get("destination_state_region"), "lane.destination_state_region", required=True),
        "postal_code_assumption": _text(lane.get("postal_code_assumption"), "lane.postal_code_assumption", required=True),
        "currency": _currency(lane.get("currency")),
        "tax_model": _text(lane.get("tax_model"), "lane.tax_model", required=True),
        "duty_model": _text(lane.get("duty_model"), "lane.duty_model", required=True),
        "brokerage_model": _text(lane.get("brokerage_model"), "lane.brokerage_model", required=True),
        "shipping_model": _text(lane.get("shipping_model"), "lane.shipping_model", required=True),
        "return_destination": _text(lane.get("return_destination"), "lane.return_destination", required=True),
        "return_cost_payer": _text(lane.get("return_cost_payer"), "lane.return_cost_payer", required=True),
        "payment_method": _text(lane.get("payment_method"), "lane.payment_method", required=True),
        "compliance_requirements": _text_list(lane.get("compliance_requirements"), "lane.compliance_requirements", required=True),
        "customer_support_language": _text_list(lane.get("customer_support_language"), "lane.customer_support_language", required=True),
        "marketplace_eligibility": _text_list(lane.get("marketplace_eligibility"), "lane.marketplace_eligibility", required=True),
        "delivery_promise": _text(lane.get("delivery_promise"), "lane.delivery_promise", required=True),
        "evidence_state": evidence_state,
        "confidence": _number(lane.get("confidence"), "lane.confidence", minimum=0.0, maximum=1.0),
    }
    return result


def _metadata(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    values = manifest.get("candidates", [])
    if not isinstance(values, list) or len(values) > MAX_RECORDS:
        raise ResearchToDecisionError("candidates must be a bounded list")
    result: dict[str, dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, Mapping):
            raise ResearchToDecisionError("candidate metadata must be objects")
        if set(item) - {"candidate_id", "title", "category", "lifecycle_state", "target_sell_price", "retailer_penalty", "evidence_expiry"}:
            raise ResearchToDecisionError("unknown candidate metadata field")
        candidate_id = _text(item.get("candidate_id"), "candidate.candidate_id", required=True)
        if candidate_id in result:
            raise ResearchToDecisionError(f"duplicate candidate metadata: {candidate_id}")
        lifecycle = _text(item.get("lifecycle_state") or "evidence_collected", "candidate.lifecycle_state")
        if lifecycle not in LIFECYCLE_STATES:
            raise ResearchToDecisionError(f"unsupported lifecycle_state: {lifecycle}")
        expiry = item.get("evidence_expiry")
        result[candidate_id] = {
            "title": _text(item.get("title") or candidate_id, "candidate.title"),
            "category": _text(item.get("category") or "unknown", "candidate.category"),
            "lifecycle_state": lifecycle,
            "target_sell_price": item.get("target_sell_price"),
            "retailer_penalty": item.get("retailer_penalty"),
            "evidence_expiry": _parse_timezone(expiry, "candidate.evidence_expiry") if expiry else None,
        }
    return result


def _validate_manifest(manifest: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, Any]], str]:
    if not isinstance(manifest, Mapping):
        raise ResearchToDecisionError("manifest root must be an object")
    allowed = {"captured_at", "client_name", "lane", "candidates", "supplier_inputs", "marketplace_inputs", "consumer_attention_inputs", "public_market_seed", "observation_inputs"}
    unknown = sorted(set(manifest) - allowed)
    if unknown:
        raise ResearchToDecisionError(f"unknown manifest fields: {unknown}")
    return _lane(manifest), _metadata(manifest), _parse_capture_time(manifest.get("captured_at"))


def _input_entries(manifest: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    values = manifest.get(key, [])
    if not isinstance(values, list):
        raise ResearchToDecisionError(f"{key} must be a list")
    result = []
    for item in values:
        if not isinstance(item, Mapping):
            raise ResearchToDecisionError(f"{key} entries must be objects")
        if set(item) - {"path", "label", "supplier", "source_type", "marketplace", "platform", "kind", "candidate_ids", "source_reference", "extraction_method", "warnings"}:
            raise ResearchToDecisionError(f"unknown fields in {key} entry")
        if "candidate_ids" in item and (not isinstance(item["candidate_ids"], list) or not all(isinstance(value, str) and value for value in item["candidate_ids"])):
            raise ResearchToDecisionError(f"{key}.candidate_ids must be a list of strings")
        if "source_reference" in item:
            _reference_text(item["source_reference"], f"{key}.source_reference")
        if "extraction_method" in item:
            _text(item["extraction_method"], f"{key}.extraction_method", required=True)
        _warning_values(item.get("warnings"), f"{key}.warnings")
        result.append(item)
    return result


def _check_lane(records: list[Any], lane: Mapping[str, Any], *, label: str) -> list[str]:
    warnings: list[str] = []
    for record in records:
        currency = str(getattr(record, "currency", "") or "").upper()
        if currency and currency != lane["currency"]:
            raise ResearchToDecisionError(f"currency mismatch in {label}: {currency} != {lane['currency']}")
        destination = str(getattr(record, "destination_region", "") or "").strip()
        if destination and destination.lower() != lane["destination_country"].lower():
            raise ResearchToDecisionError(f"destination mismatch in {label}: {destination}")
        if not destination and hasattr(record, "destination_region"):
            warnings.append(f"destination_missing:{label}")
        source_url = str(getattr(record, "source_url", "") or "")
        if source_url:
            parsed = _parse_url(source_url, f"unsafe source_url in {label}")
            if (
                any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in source_url)  # urlparse strips tab/CR/LF
                or parsed.scheme not in {"http", "https"}
                or not _http_authority_is_safe(parsed)
                or parsed.query
                or parsed.fragment
            ):
                raise ResearchToDecisionError(f"unsafe source_url in {label}")
    return sorted(set(warnings))


def _record_conflict_key(record: Any, role: str) -> tuple[str, ...]:
    candidate_id = str(getattr(record, "candidate_id", ""))
    if role == "supplier":
        identity = str(
            getattr(record, "supplier_product_id", "")
            or getattr(record, "supplier_sku", "")
            or getattr(record, "source_url", "")
        )
        return (role, candidate_id, str(getattr(record, "supplier", "")), identity)
    if role == "marketplace":
        return (role, candidate_id, str(getattr(record, "marketplace", "")), str(getattr(record, "source_type", "")), str(getattr(record, "source_url", "")))
    return (role, candidate_id, str(getattr(record, "platform", "")), str(getattr(record, "source", "")), str(getattr(record, "content_title", "") or getattr(record, "hook", "")))


def _check_record_conflicts(
    records: list[Any], role: str, seen: dict[tuple[str, ...], str], *, allow_supplier_conflicts: bool = False
) -> set[tuple[str, ...]]:
    conflicts: set[tuple[str, ...]] = set()
    for record in records:
        candidate_id = str(getattr(record, "candidate_id", ""))
        if role == "supplier":
            key = _record_conflict_key(record, role)
            value = json.dumps({"unit_cost": getattr(record, "unit_cost", None), "shipping_cost": getattr(record, "shipping_cost", None), "currency": getattr(record, "currency", ""), "destination": getattr(record, "destination_region", "")}, sort_keys=True)
        elif role == "marketplace":
            key = _record_conflict_key(record, role)
            value = json.dumps({"price": getattr(record, "price", None), "currency": getattr(record, "currency", ""), "availability": getattr(record, "availability", "")}, sort_keys=True)
        else:
            key = _record_conflict_key(record, role)
            value = json.dumps({"content": getattr(record, "content_text_excerpt", ""), "objection": getattr(record, "objection", "")}, sort_keys=True)
        previous = seen.get(key)
        if previous is not None and previous != value:
            if role == "supplier" and allow_supplier_conflicts:
                conflicts.add(key)
            else:
                raise ResearchToDecisionError(f"conflicting duplicate evidence: {candidate_id}")
        seen[key] = value
    return conflicts


def _row_value(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _offer_text(row: Mapping[str, Any], names: tuple[str, ...], field: str, issues: list[str]) -> str:
    value = _row_value(row, *names)
    if value in (None, ""):
        issues.append(f"{field}_missing")
        return "unknown"
    return _text(value, f"supplier_offer.{field}")


def _bool_field(row: Mapping[str, Any], names: tuple[str, ...], field: str) -> bool:
    """Fail-closed boolean: absent means False, and only recognized text/bool
    forms are accepted -- anything else is a malformed value, not a guess."""
    value = _row_value(row, *names)
    if value in (None, ""):
        return False
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in TRUE_TEXT:
        return True
    if text in FALSE_TEXT:
        return False
    raise ResearchToDecisionError(f"{field} must be a boolean")


def _offer_number(row: Mapping[str, Any], names: tuple[str, ...], field: str, issues: list[str]) -> float | None:
    value = _row_value(row, *names)
    if value in (None, ""):
        issues.append(f"{field}_missing")
        return None
    if isinstance(value, str) and value.strip().lower() in {"unknown", "unavailable", "n/a", "none"}:
        issues.append(f"{field}_unknown")
        return None
    return _number(value, f"supplier_offer.{field}", minimum=0.0)


def _normalize_supplier_offer(
    row: Mapping[str, Any],
    *,
    lane: Mapping[str, Any],
    captured_at: str,
    source_label: str,
    source_reference: Any = None,
    extraction_method: Any = None,
    input_warnings: Any = None,
    import_evidence_state: str,
    operator_confirmations: set[tuple[str, str, str]],
    document_evidence_bindings: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    candidate_id = _text(row.get("candidate_id"), "supplier_offer.candidate_id", required=True)
    offer_id_value = _row_value(row, "offer_id", "supplier_offer_id", "supplier_product_id")
    exact_sku_value = _row_value(row, "supplier_sku", "sku")
    if not offer_id_value or not exact_sku_value:
        raise ResearchToDecisionError("supplier offer identity requires offer_id and exact supplier_sku")
    offer_id = _text(offer_id_value, "supplier_offer.offer_id", required=True)
    exact_sku = _text(exact_sku_value, "supplier_offer.exact_sku", required=True)
    malformed_nested = [key for key, value in row.items() if key in OFFER_FIELDS - {"field_provenance", "warnings"} and isinstance(value, (Mapping, list, tuple))]
    if malformed_nested:
        raise ResearchToDecisionError(f"malformed nested supplier offer fields: {', '.join(sorted(malformed_nested))}")
    issues: list[str] = []
    currency = _currency(_row_value(row, "currency", "price_currency"))
    if currency != lane["currency"]:
        raise ResearchToDecisionError(f"currency mismatch in supplier offer: {currency} != {lane['currency']}")
    destination = _offer_text(row, ("destination_region", "destination_country", "destination"), "destination", issues)
    if destination != "unknown" and destination.lower() != lane["destination_country"].lower():
        raise ResearchToDecisionError(f"destination mismatch in supplier offer: {destination}")
    observed_at = _parse_timezone(_row_value(row, "captured_at", "observed_at") or captured_at, "supplier_offer.captured_at")
    expires_value = _row_value(row, "price_valid_until", "valid_until", "expires_at")
    expires_at = _parse_timezone(expires_value, "supplier_offer.expires_at") if expires_value else None
    if expires_at and datetime.fromisoformat(expires_at.replace("Z", "+00:00")) < datetime.fromisoformat(observed_at.replace("Z", "+00:00")):
        issues.append("offer_expired")
    source = _offer_text(row, ("source_type", "source"), "source", issues) or source_label
    explicit_reference = _row_value(row, "source_reference", "document_reference") or source_reference
    if explicit_reference:
        explicit_reference = _reference_text(explicit_reference, "supplier_offer.source_reference")
    document_reference_provided = bool(explicit_reference)
    reference_value = explicit_reference or source_label
    reference_id = _evidence_reference(reference_value, "supplier_offer.source_reference")
    method_value = _row_value(row, "extraction_method") or extraction_method or "manual_import"
    method = _text(method_value, "supplier_offer.extraction_method", required=True)
    source_claimed_human_confirmation = _bool_field(row, ("human_confirmed", "human_reviewed"), "supplier_offer.human_confirmed")
    human_confirmed = bool(
        explicit_reference
        and (offer_id, exact_sku, explicit_reference) in operator_confirmations
    )
    document_binding = (document_evidence_bindings or {}).get((offer_id, exact_sku))
    document_bytes_confirmed = bool(
        document_binding
        and explicit_reference
        and document_binding["reference"] == explicit_reference
    )
    evidence_warnings = _warning_values(_row_value(row, "warnings") or input_warnings, "supplier_offer.warnings")
    source_claimed_state = _offer_text(row, ("evidence_state",), "evidence_state", issues)
    if source_claimed_state != "unknown" and source_claimed_state not in EVIDENCE_STATES:
        raise ResearchToDecisionError(f"unsupported supplier offer evidence_state: {source_claimed_state}")
    evidence_state = import_evidence_state
    confidence_value = _row_value(row, "confidence", "source_confidence")
    confidence = 0.0 if confidence_value in (None, "") else _number(confidence_value, "supplier_offer.confidence", minimum=0.0, maximum=1.0)
    if confidence_value in (None, ""):
        issues.append("confidence_missing")
    price = _offer_number(row, ("unit_cost", "price", "supplier_price"), "price", issues)
    shipping_cost = _offer_number(row, ("shipping_cost", "shipping"), "shipping_cost", issues)
    shipping_method = _offer_text(row, ("shipping_method", "fulfillment_method", "fulfillment"), "shipping_method", issues)
    inventory = _offer_text(row, ("inventory_status", "stock_status", "availability"), "stock", issues)
    p50 = _offer_number(row, ("p50_delivery_days", "delivery_min_days", "min_delivery_days"), "p50_delivery_days", issues)
    p95 = _offer_number(row, ("p95_delivery_days", "delivery_max_days", "max_delivery_days"), "p95_delivery_days", issues)
    approval_state = _offer_text(row, ("approval_state",), "approval_state", issues)
    if approval_state != "unknown" and approval_state not in OFFER_APPROVAL_STATES:
        raise ResearchToDecisionError(f"unsupported supplier offer approval_state: {approval_state}")
    offer = {
        "offer_id": _text(offer_id, "supplier_offer.offer_id", required=True),
        "candidate_id": candidate_id,
        "supplier": _offer_text(row, ("supplier", "provider"), "supplier", issues),
        "exact_sku": _text(exact_sku, "supplier_offer.exact_sku", required=True),
        "variant": _offer_text(row, ("variant", "variant_name"), "variant", issues),
        "price": {"amount": price, "currency": currency, "valid_until": expires_at},
        "shipping": {"cost": shipping_cost, "model": lane["shipping_model"], "method": shipping_method},
        "stock": {"status": inventory, "quantity": _row_value(row, "inventory_quantity", "stock")},
        "warehouse": _offer_text(row, ("warehouse_region", "warehouse"), "warehouse", issues),
        "destination": destination,
        "delivery": {"p50_days": p50, "p95_days": p95},
        "tracking": _offer_text(row, ("tracking_available", "tracking"), "tracking", issues),
        "blind_shipping": _offer_text(row, ("blind_shipping",), "blind_shipping", issues),
        "packaging": _offer_text(row, ("packaging",), "packaging", issues),
        "returns": {"address": _offer_text(row, ("return_address",), "return_address", issues), "cost_payer": _offer_text(row, ("return_cost_payer",), "return_cost_payer", issues)},
        "warranty": _offer_text(row, ("warranty",), "warranty", issues),
        "rma": _offer_text(row, ("rma_process", "rma"), "rma", issues),
        "refund_sla_days": _offer_number(row, ("refund_sla_days",), "refund_sla_days", issues),
        "support": {"owner": _offer_text(row, ("support_owner",), "support_owner", issues), "response_sla_hours": _offer_number(row, ("support_response_sla_hours",), "support_response_sla_hours", issues)},
        "permissions": {"dropshipping": _offer_text(row, ("dropshipping_permission",), "dropshipping_permission", issues), "marketplace": _offer_text(row, ("marketplace_permission",), "marketplace_permission", issues)},
        "sample_state": _offer_text(row, ("sample_state",), "sample_state", issues),
        "terms_evidence": _offer_text(row, ("contract_evidence", "terms_evidence"), "terms_evidence", issues),
        "policy_evidence": _offer_text(row, ("policy_evidence",), "policy_evidence", issues),
        "backup_supplier": _offer_text(row, ("backup_supplier",), "backup_supplier", issues),
        "approval_state": approval_state,
        "evidence": {
            "captured_at": observed_at,
            "expires_at": expires_at,
            "source": source,
            "reference_id": reference_id,
            "document_reference_provided": document_reference_provided,
            "extraction_method": method,
            "state": evidence_state,
            "source_claimed_state": source_claimed_state,
            "confidence": confidence,
            "human_confirmed": human_confirmed,
            "human_confirmation_source": "operator_input" if human_confirmed else "none",
            "supplier_claimed_human_confirmation": source_claimed_human_confirmation,
            "document_bytes_confirmed": document_bytes_confirmed,
            "document_digest": document_binding["document_digest"] if document_bytes_confirmed else None,
            "document_size_bytes": document_binding["document_size_bytes"] if document_bytes_confirmed else None,
            "warnings": evidence_warnings,
        },
        "unknown_fields": sorted(set(row) - OFFER_FIELDS),
    }
    if approval_state == "approved" and any(offer[key] in {"unknown", None} for key in ("sample_state", "rma")):
        issues.append("approval_not_earned")
        offer["approval_state"] = "candidate"
    offer["status"] = "quarantined" if issues else "accepted"
    offer["issues"] = sorted(set(issues))
    return offer


def _load_import(
    path: Path,
    entry: Mapping[str, Any],
    role: str,
    *,
    lane: Mapping[str, Any],
    captured_at: str,
    operator_confirmations: set[tuple[str, str, str]],
    document_evidence_bindings: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    rows, fmt = _raw_records(path)
    label = _text(entry.get("label") or path.name, f"{role}.label")
    _validate_rows(rows, label=label, role=role)
    if role == "supplier":
        supplier = _text(entry.get("supplier") or ("manual" if fmt == "csv" else "cj"), "supplier")
        source_type = _text(entry.get("source_type") or ("manual_csv_import" if fmt == "csv" else "fixture_demo"), "source_type")
        records = import_supplier_csv(path, supplier=supplier, source_type=source_type) if fmt == "csv" else import_supplier_json(path, supplier=supplier, source_type=source_type)
    elif role == "marketplace":
        marketplace = _text(entry.get("marketplace") or "amazon", "marketplace")
        records = import_marketplace_csv(path, marketplace=marketplace) if fmt == "csv" else import_marketplace_json(path, marketplace=marketplace, source_type=entry.get("source_type"))
    elif role == "consumer_attention":
        platform = _text(entry.get("platform") or ("manual" if fmt == "csv" else "manual"), "platform")
        source_type = _text(entry.get("source_type") or ("manual_csv_import" if fmt == "csv" else "fixture_demo"), "source_type")
        records = import_consumer_csv(path, platform=platform, source_type=source_type) if fmt == "csv" else import_consumer_json(path, platform=platform, source_type=source_type)
    else:
        raise ResearchToDecisionError(f"unsupported import role: {role}")
    supplier_offers = []
    if role == "supplier":
        supplier_offers = [
            _normalize_supplier_offer(
                row,
                lane=lane,
                captured_at=captured_at,
                source_label=label,
                source_reference=entry.get("source_reference"),
                extraction_method=entry.get("extraction_method") or ("manual_csv_import" if fmt == "csv" else "manual_json_import"),
                input_warnings=entry.get("warnings"),
                import_evidence_state="manual" if fmt == "csv" else "fixture",
                operator_confirmations=operator_confirmations,
                document_evidence_bindings=document_evidence_bindings,
            )
            for row in rows
        ]
    selected = set(entry.get("candidate_ids", []))
    if selected:
        records = [record for record in records if getattr(record, "candidate_id", "") in selected]
        supplier_offers = [offer for offer in supplier_offers if offer["candidate_id"] in selected]
    selected_rows = rows if not selected else [row for row in rows if _candidate_id(row) in selected]
    candidate_evidence_refs: dict[str, list[str]] = {}
    if role == "supplier":
        for offer in supplier_offers:
            candidate_evidence_refs.setdefault(offer["candidate_id"], []).append(offer["evidence"]["reference_id"])
    else:
        default_reference = entry.get("source_reference") or path.name
        for row in selected_rows:
            candidate_id = _candidate_id(row)
            reference_value = row.get("source_reference") or row.get("document_reference") or row.get("source_url") or row.get("url") or default_reference
            reference_id = _evidence_reference(reference_value, f"{role}.source_reference", allow_url_query=bool(row.get("source_url") or row.get("url")))
            candidate_evidence_refs.setdefault(candidate_id, []).append(reference_id)
    return records, {
        "label": label,
        "role": role,
        "format": fmt,
        "records_seen": len(rows),
        "records_accepted": len(records),
        "supplier_offers_seen": len(supplier_offers),
        "supplier_offers_accepted": sum(offer["status"] == "accepted" for offer in supplier_offers),
        "supplier_offers_quarantined": sum(offer["status"] == "quarantined" for offer in supplier_offers),
        "supplier_offer_issues": sorted({issue for offer in supplier_offers for issue in offer["issues"]}),
        "supplier_offers": supplier_offers,
        "evidence_refs": sorted({ref for refs in candidate_evidence_refs.values() for ref in refs}),
        "extraction_methods": sorted({entry.get("extraction_method") or ("manual_csv_import" if fmt == "csv" else f"manual_{role}_import")}),
        "warnings": _warning_values(entry.get("warnings"), f"{role}.warnings"),
        "candidate_evidence_refs": {key: sorted(set(value)) for key, value in sorted(candidate_evidence_refs.items())},
        "status": "accepted" if records else "needs_evidence",
    }


def _load_observation(path: Path, entry: Mapping[str, Any], *, lane: Mapping[str, Any]) -> dict[str, Any]:
    kind = _text(entry.get("kind"), "observation.kind", required=True)
    if kind not in OBSERVATION_KINDS:
        raise ResearchToDecisionError(f"unsupported observation kind: {kind}")
    rows, fmt = _raw_records(path)
    label = _text(entry.get("label") or path.name, "observation.label")
    _validate_rows(rows, label=label, role="observation")
    evidence_refs: set[str] = set()
    extraction_methods: set[str] = set()
    warnings: set[str] = set(_warning_values(entry.get("warnings"), "observation.warnings"))
    candidate_evidence_refs: dict[str, list[str]] = {}
    for row in rows:
        url = row.get("url") or row.get("source_url")
        if kind == "reviewed_url":
            reviewed = _parse_url(url, f"reviewed_url requires an http(s) URL: {label}") if isinstance(url, str) else None
            if reviewed is None or reviewed.scheme not in {"http", "https"} or not reviewed.netloc:
                raise ResearchToDecisionError(f"reviewed_url requires an http(s) URL: {label}")
            _reference_text(url, "reviewed_url.url", allow_url_query=True)
        reference_value = row.get("source_reference") or row.get("document_reference") or (url if kind == "reviewed_url" else row.get("source")) or entry.get("source_reference") or label
        reference_id = _evidence_reference(reference_value, f"{kind}.source_reference", allow_url_query=kind == "reviewed_url")
        method = _text(row.get("extraction_method") or entry.get("extraction_method") or ("operator_reviewed_url" if kind == "reviewed_url" else "manual_document_review"), f"{kind}.extraction_method", required=True)
        row_warnings = _warning_values(row.get("warnings") or entry.get("warnings"), f"{kind}.warnings")
        warnings.update(row_warnings)
        evidence_refs.add(reference_id)
        extraction_methods.add(method)
        candidate_evidence_refs.setdefault(_candidate_id(row), []).append(reference_id)
        if kind in {"pdf_derived", "form"}:
            required = ("source", "captured_at", "expires_at", "evidence_state", "confidence", "terms", "returns", "warranty", "support", "delivery", "permissions", "supplier_sku", "destination_country", "currency", "extraction_method")
            missing = [field for field in required if row.get(field) in (None, "")]
            if missing:
                raise ResearchToDecisionError(f"{kind} evidence is missing required fields: {', '.join(missing)}")
            _parse_timezone(row.get("captured_at"), f"{kind}.captured_at")
            _parse_timezone(row.get("expires_at"), f"{kind}.expires_at")
            _text(row.get("supplier_sku"), f"{kind}.supplier_sku", required=True)
            destination = _text(row.get("destination_country"), f"{kind}.destination_country", required=True)
            if destination.lower() != lane["destination_country"].lower():
                raise ResearchToDecisionError(f"destination mismatch in {kind}: {destination}")
            currency = _currency(row.get("currency"))
            if currency != lane["currency"]:
                raise ResearchToDecisionError(f"currency mismatch in {kind}: {currency} != {lane['currency']}")
            evidence_state = _text(row.get("evidence_state"), f"{kind}.evidence_state")
            if evidence_state not in EVIDENCE_STATES:
                raise ResearchToDecisionError(f"unsupported {kind} evidence_state: {evidence_state}")
            _number(row.get("confidence"), f"{kind}.confidence", minimum=0.0, maximum=1.0)
    return {
        "label": label,
        "role": "observation",
        "kind": kind,
        "format": fmt,
        "records_seen": len(rows),
        "records_accepted": len(rows),
        "evidence_refs": sorted(evidence_refs),
        "extraction_methods": sorted(extraction_methods),
        "warnings": sorted(warnings),
        "candidate_evidence_refs": {key: sorted(set(value)) for key, value in sorted(candidate_evidence_refs.items())},
        "status": "accepted",
    }


def _best(mapping: Mapping[str, Any], candidate_id: str) -> Mapping[str, Any]:
    return next((item for item in mapping.get("candidates", []) if item.get("candidate_id") == candidate_id), {})


def _promotion_evidence_state(lane: Mapping[str, Any], offers: list[dict[str, Any]]) -> str:
    states = [offer.get("evidence", {}).get("state") for offer in offers]
    states = [state for state in states if state in EVIDENCE_STATES]
    if not states:
        return lane.get("evidence_state", "unavailable") if lane.get("evidence_state") in EVIDENCE_STATES else "unavailable"
    return states[0] if len(set(states)) == 1 else "unavailable"


def _promotion_transition(
    *,
    candidate_id: str,
    prior_state: str,
    next_state: str,
    reason_code: str,
    evidence_ids: list[str],
    evidence_state: str,
    captured_at: str,
    blocking_conditions: list[str],
) -> dict[str, Any]:
    transition = {
        "candidate_id": candidate_id,
        "prior_state": prior_state,
        "next_state": next_state,
        "reason_code": reason_code,
        "evidence_ids": sorted(set(evidence_ids)),
        "evidence_state": evidence_state,
        "actor_source": "scripts.research_to_decision.py",
        "timestamp": captured_at,
        "blocking_conditions": sorted(set(blocking_conditions)),
    }
    transition["replay_identity"] = hashlib.sha256(
        json.dumps(transition, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return transition


def _decision_outcome(
    *,
    lifecycle_state: str,
    decision: str,
    evidence_gaps: list[str],
    transitions: list[dict[str, Any]],
) -> str:
    normalized = decision.strip().lower()
    if lifecycle_state in {"reject", "no_launch"} or "reject" in normalized:
        return "reject"
    if "defer" in normalized:
        return "deferred"
    if evidence_gaps:
        return "needs_evidence"
    if transitions and transitions[-1]["next_state"] == "launch_candidate":
        return "launch_candidate"
    if "hold" in normalized or lifecycle_state == "hold":
        return "hold_for_manual_review"
    return "candidate_only"


def _promotion_lifecycle(
    *,
    candidate_id: str,
    meta: Mapping[str, Any],
    lane: Mapping[str, Any],
    offers: list[dict[str, Any]],
    market_item: Mapping[str, Any],
    supplier_score: Mapping[str, Any],
    market_score: Mapping[str, Any],
    hard_gates: list[str],
    evidence_refs: list[str],
    captured_at: str,
    decision: str,
) -> tuple[list[dict[str, Any]], str, list[str]]:
    evidence_state = _promotion_evidence_state(lane, offers)
    offer_issues = sorted({issue for offer in offers for issue in offer.get("issues", [])})
    market_evidence = market_item.get("evidence", [])
    blockers = set(hard_gates)
    if not market_evidence:
        blockers.add("competition_evidence_missing")
    if lane.get("evidence_state") != "observed":
        blockers.add("lane_not_verified")
    blockers.update(f"supplier_offer:{issue}" for issue in offer_issues)
    evidence_gaps = {
        blocker
        for blocker in blockers
        if blocker == "supplier_offer_evidence_missing"
        or blocker == "competition_evidence_missing"
        or blocker.startswith("supplier_offer:")
        or blocker == "lane_not_verified" and lane.get("evidence_state") in {"unavailable", "malformed", "blocked"}
    }
    transitions: list[dict[str, Any]] = []
    prior_state = "unavailable"

    def add(next_state: str, reason_code: str, *, state: str = evidence_state, conditions: list[str] | None = None) -> None:
        nonlocal prior_state
        transitions.append(
            _promotion_transition(
                candidate_id=candidate_id,
                prior_state=prior_state,
                next_state=next_state,
                reason_code=reason_code,
                evidence_ids=evidence_refs,
                evidence_state=state,
                captured_at=captured_at,
                blocking_conditions=conditions if conditions is not None else sorted(blockers),
            )
        )
        prior_state = next_state

    add("discovered", "candidate_declared", conditions=[])
    add("normalized", "evidence_normalized", conditions=[])
    add("screened", "screening_completed")
    if offers:
        add("supplier_claimed", "supplier_offer_observed")
        # Only manual-import evidence can reach supplier_documented, and then
        # only when an out-of-payload operator input matches every offer's
        # exact offer ID, SKU, and explicit reference. Supplier-file booleans
        # and references remain claims, not operator attestations.
        terms_and_policy_present = all(
            offer.get("terms_evidence") not in {None, "unknown"} and offer.get("policy_evidence") not in {None, "unknown"}
            for offer in offers
        )
        documented = all(
            offer.get("evidence", {}).get("document_reference_provided") is True
            and offer.get("evidence", {}).get("human_confirmed") is True
            and offer.get("evidence", {}).get("state") == "manual"
            for offer in offers
        )
        if terms_and_policy_present and documented:
            add("supplier_documented", "supplier_terms_and_policy_present")
        elif terms_and_policy_present:
            blockers.add("supplier_offer:human_review_or_document_reference_missing")
        if "conflicting_offer" in offer_issues:
            add("offer_conflicted", "conflicting_supplier_offers_quarantined")
    if evidence_gaps:
        add("evidence_incomplete", "required_evidence_missing", state="unavailable", conditions=sorted(evidence_gaps))
    if lane.get("evidence_state") == "observed":
        add("lane_verified", "lane_evidence_observed")
    if offers and not all(offer.get("sample_state") == "sample_passed" for offer in offers):
        add("sample_required", "sample_not_passed")
    if offers and not all("direct" in str(offer.get("shipping", {}).get("method", "")).lower() for offer in offers):
        add("direct_ship_required", "direct_ship_not_tested")
    if offers and not all(offer.get("rma") not in {None, "unknown"} for offer in offers):
        add("rma_required", "rma_route_missing")
    economics = supplier_score.get("economics") or {}
    if economics and not any(
        value is None or isinstance(value, str) and value in {"unknown", "unavailable"}
        for value in economics.values()
    ):
        add("economics_ready", "economics_observed")
    if market_evidence and not any("missing" in str(reason) or "unknown" in str(reason) or "unavailable" in str(reason) for reason in market_score.get("reasons", [])):
        add("competition_ready", "competition_evidence_observed")
    if blockers:
        add("promotion_blocked", "promotion_requirements_incomplete")
    add("launch_authorized_false", "launch_authority_not_granted")
    if len(transitions) > MAX_TRANSITIONS_PER_CANDIDATE:
        raise ResearchToDecisionError("promotion lifecycle exceeds transition cap")
    outcome = _decision_outcome(
        lifecycle_state=str(meta.get("lifecycle_state", "evidence_collected")),
        decision=decision,
        evidence_gaps=sorted(evidence_gaps),
        transitions=transitions,
    )
    return transitions, outcome, sorted(evidence_gaps)


def _benchmark_candidates(
    candidate_ids: set[str], metadata: Mapping[str, Mapping[str, Any]], marketplace: Mapping[str, Any], supplier: Mapping[str, Any], lane: Mapping[str, str]
) -> list[BenchmarkCandidate]:
    values: list[BenchmarkCandidate] = []
    for candidate_id in sorted(candidate_ids):
        market = _best(marketplace, candidate_id)
        supplier_item = _best(supplier, candidate_id)
        market_score = market.get("score", {})
        supplier_score = supplier_item.get("score", {})
        offers = supplier_item.get("offers", [])
        market_evidence = market.get("evidence", [])
        observed_fields = []
        if offers:
            first = offers[0]
            observed_fields = [
                name for name, value in (("price", first.get("unit_cost")), ("sku", first.get("supplier_sku")), ("inventory", first.get("inventory_status")), ("variant", first.get("variant_count")), ("shipping", first.get("shipping_cost")), ("delivery", first.get("delivery_max_days"))) if value not in (None, "")
            ]
        economics = supplier_score.get("economics") or {}
        assumptions = sorted({name for name in ("price", "sku", "inventory", "variant", "shipping", "delivery") if name not in observed_fields})
        meta = metadata.get(candidate_id, {})
        values.append(BenchmarkCandidate(
            candidate_id=candidate_id,
            title=str(meta.get("title") or market.get("query") or supplier_item.get("query") or candidate_id),
            query=str(market.get("query") or supplier_item.get("query") or candidate_id),
            category=str(meta.get("category") or "unknown"),
            source="manual_import",
            supplier_evidence={"source_type": (offers[0].get("source_type") if offers else "unavailable"), "observed_fields": observed_fields, "confidence": supplier_score.get("overall_supplier_feasibility", 0.0), "credential_status": "not_configured"},
            competition_evidence={"observed_offers": len(market_evidence), "pricing_coverage": market.get("score", {}).get("price_confidence", 0.0), "sources": sorted({item.get("marketplace", "") for item in market_evidence if item.get("marketplace")}), "availability_observed": any(item.get("availability") for item in market_evidence), "reviews_observed": any(item.get("review_count") is not None for item in market_evidence), "confidence": market_score.get("overall_marketplace_opportunity", 0.0)},
            opportunity_score=market_score.get("overall_marketplace_opportunity", 0.0),
            commerce_run={"gross_margin": (float(economics["gross_margin_percent"]) / 100 if economics.get("gross_margin_percent") is not None else None), "assumption_ratio": len(assumptions) / 6},
            assumptions=tuple(assumptions),
            warnings=(f"lane_currency:{lane['currency']}",),
        ))
    return values


def _candidate_audit(
    candidate_ids: set[str],
    metadata: Mapping[str, Mapping[str, Any]],
    marketplace: Mapping[str, Any],
    supplier: Mapping[str, Any],
    synthesis: Mapping[str, Any],
    lane: Mapping[str, Any],
    supplier_offers: Mapping[str, list[dict[str, Any]]],
    evidence_refs_by_candidate: Mapping[str, set[str]],
    captured_at: str,
) -> list[dict[str, Any]]:
    rows = []
    synthesis_items = {item.get("candidate_id"): item for item in synthesis.get("candidates", [])}
    for candidate_id in sorted(candidate_ids):
        supplier_item = _best(supplier, candidate_id)
        market_item = _best(marketplace, candidate_id)
        supplier_score = supplier_item.get("score", {})
        market_score = market_item.get("score", {})
        meta = metadata.get(candidate_id, {})
        offers = sorted(supplier_offers.get(candidate_id, []), key=lambda item: item["offer_id"])
        offer_issues = sorted({issue for offer in offers for issue in offer["issues"]})
        hard_gates = ["manual_evidence_is_not_live_supplier_proof", "no_launch_or_spend_authority"]
        if not offers:
            hard_gates.append("supplier_offer_evidence_missing")
        if offer_issues:
            hard_gates.extend(f"supplier_offer:{issue}" for issue in offer_issues)
        evidence_refs = sorted(evidence_refs_by_candidate.get(candidate_id, set()))
        if any("offer_expired" in issue for issue in offer_issues):
            freshness = "expired"
        elif offers and all(offer["evidence"].get("expires_at") for offer in offers):
            freshness = "current"
        elif offers:
            freshness = "unknown"
        else:
            freshness = "unavailable"
        risk_state = "blocked" if any(gate.startswith("supplier_offer:") or gate == "supplier_offer_evidence_missing" for gate in hard_gates) else "hold"
        decision = (synthesis_items.get(candidate_id) or {}).get("next_best_action", "hold_for_manual_review")
        promotion_lifecycle, decision_outcome, evidence_gaps = _promotion_lifecycle(
            candidate_id=candidate_id,
            meta=meta,
            lane=lane,
            offers=offers,
            market_item=market_item,
            supplier_score=supplier_score,
            market_score=market_score,
            hard_gates=hard_gates,
            evidence_refs=evidence_refs,
            captured_at=captured_at,
            decision=decision,
        )
        rows.append({
            "candidate_id": candidate_id,
            "title": meta.get("title", candidate_id),
            "lifecycle_state": meta.get("lifecycle_state", "evidence_collected"),
            "evidence_expiry": meta.get("evidence_expiry"),
            "lane": {"destination_country": lane["destination_country"], "currency": lane["currency"], "warehouse": lane["warehouse"]},
            "supplier_offers": offers,
            "economics": supplier_score.get("economics") or {},
            "observed_values": {"supplier_offer_count": len(offers), "marketplace_evidence_count": len(market_item.get("evidence", [])), "currency": lane["currency"], "destination_country": lane["destination_country"]},
            "assumptions": sorted({*supplier_score.get("reasons", []), *market_score.get("reasons", [])}),
            "missing_evidence": sorted({item for item in (supplier_score.get("reasons", []) + market_score.get("reasons", [])) if "missing" in item or "unknown" in item or "unavailable" in item}),
            "evidence_refs": evidence_refs,
            "extraction_methods": sorted({offer["evidence"].get("extraction_method", "") for offer in offers if offer["evidence"].get("extraction_method")}),
            "freshness": freshness,
            "conflicts": sorted({issue for issue in offer_issues if "conflict" in issue}),
            "risk_state": risk_state,
            "confidence": {"supplier": supplier_score.get("overall_supplier_feasibility", 0.0), "marketplace": market_score.get("overall_marketplace_opportunity", 0.0)},
            "decision": decision,
            "decision_outcome": decision_outcome,
            "next_action": decision,
            "action": decision,
            "hard_gates": sorted(set(hard_gates)),
            "evidence_gaps": evidence_gaps,
            "promotion_lifecycle": promotion_lifecycle,
            "safety_classification": "offline_manual_evidence_only",
            "retailer_penalty": meta.get("retailer_penalty"),
            "comparability": "comparable" if market_item and supplier_item else "incomplete",
        })
    return rows


def build_research_to_decision(
    manifest: Mapping[str, Any],
    *,
    base_dir: str | Path,
    operator_confirmed_supplier_documents: Sequence[Sequence[str]] = (),
    supplier_evidence_root: str | Path | None = None,
    confirmed_supplier_document_evidence: Sequence[Sequence[str]] = (),
) -> dict[str, Any]:
    """Build the existing report; confirmations must come from outside imports.

    Operator confirmations are local attestations, not authenticated identity
    or supplier/document verification. ``confirmed_supplier_document_evidence``
    (``[offer_id, exact_sku, reference, sha256_digest]`` rows, resolved only
    under ``supplier_evidence_root``) additionally proves that the bytes at
    ``reference`` match ``sha256_digest`` -- document *byte integrity*, still
    not supplier identity, human review, or live validation. Both parameters
    are optional and additive; omitting them reproduces prior behavior
    exactly (see #279's ``run_commercial_replay_integration.py``, which calls
    this function without either).
    """
    lane, metadata, captured_at = _validate_manifest(manifest)
    operator_confirmations = _operator_supplier_confirmations(operator_confirmed_supplier_documents)
    evidence_root = _resolve_root(supplier_evidence_root, "supplier evidence root") if supplier_evidence_root else None
    document_evidence_bindings = _supplier_document_evidence_bindings(confirmed_supplier_document_evidence, evidence_root=evidence_root)
    base = _resolve_root(base_dir, "manifest base directory")
    entries_total = sum(len(manifest.get(key, []) or []) for key in ("supplier_inputs", "marketplace_inputs", "consumer_attention_inputs", "observation_inputs")) + (1 if manifest.get("public_market_seed") else 0)
    if entries_total > MAX_INPUT_FILES:
        raise ResearchToDecisionError(f"manifest exceeds {MAX_INPUT_FILES} input files")
    supplier_records: list[Any] = []
    marketplace_records: list[Any] = []
    consumer_records: list[Any] = []
    seen_records: dict[tuple[str, ...], str] = {}
    input_audit: list[dict[str, Any]] = []
    supplier_offers_by_candidate: dict[str, list[dict[str, Any]]] = {}
    evidence_refs_by_candidate: dict[str, set[str]] = {}
    supplier_conflict_keys: set[tuple[str, ...]] = set()
    warnings: list[str] = []
    candidate_ids = set(metadata)
    for key, role, destination in (("supplier_inputs", "supplier", supplier_records), ("marketplace_inputs", "marketplace", marketplace_records), ("consumer_attention_inputs", "consumer_attention", consumer_records)):
        for entry in _input_entries(manifest, key):
            path = _resolve(base, entry.get("path"), label=f"{key}.path")
            records, audit = _load_import(
                path,
                entry,
                role,
                lane=lane,
                captured_at=captured_at,
                operator_confirmations=operator_confirmations,
                document_evidence_bindings=document_evidence_bindings,
            )
            supplier_conflict_keys.update(
                _check_record_conflicts(records, role, seen_records, allow_supplier_conflicts=role == "supplier")
            )
            if role == "supplier":
                quarantined = {(offer["candidate_id"], offer["exact_sku"]) for offer in audit.get("supplier_offers", []) if offer["status"] == "quarantined"}
                original_count = len(records)
                records = [record for record in records if (getattr(record, "candidate_id", ""), getattr(record, "supplier_sku", "")) not in quarantined]
                audit["records_accepted"] = len(records)
                audit["records_quarantined"] = original_count - len(records)
            destination.extend(records)
            candidate_ids.update(getattr(record, "candidate_id", "") for record in records)
            if role == "supplier":
                for offer in audit.get("supplier_offers", []):
                    supplier_offers_by_candidate.setdefault(offer["candidate_id"], []).append(offer)
                warnings.extend(f"supplier_offer:{issue}" for issue in audit.get("supplier_offer_issues", []))
            for candidate_id, refs in audit.get("candidate_evidence_refs", {}).items():
                evidence_refs_by_candidate.setdefault(candidate_id, set()).update(refs)
            input_audit.append(audit)
            if not records:
                warnings.append(f"no_accepted_records:{audit['label']}")
            if role in {"supplier", "marketplace", "consumer_attention"}:
                warnings.extend(_check_lane(records, lane, label=audit["label"]))
    for entry in _input_entries(manifest, "observation_inputs"):
        audit = _load_observation(_resolve(base, entry.get("path"), label="observation_inputs.path"), entry, lane=lane)
        input_audit.append(audit)
        for candidate_id, refs in audit.get("candidate_evidence_refs", {}).items():
            evidence_refs_by_candidate.setdefault(candidate_id, set()).update(refs)

    public_market_report: dict[str, Any] = {}
    if manifest.get("public_market_seed"):
        path = _resolve(base, manifest.get("public_market_seed"), label="public_market_seed")
        rows, _ = _raw_records(path)
        if len(rows) > MAX_RECORDS:
            raise ResearchToDecisionError("public_market_seed exceeds the record cap")
        candidates, seed_warnings = load_public_market_seed(path)
        public_market_report = build_public_market_benchmark(candidates, allow_network=False).to_dict()
        warnings.extend(seed_warnings)
        input_audit.append({"label": path.name, "role": "public_market_seed", "format": "json", "records_seen": len(candidates), "records_accepted": len(candidates), "status": "accepted" if candidates else "needs_evidence"})

    if supplier_conflict_keys:
        for audit in input_audit:
            if audit.get("role") != "supplier":
                continue
            for offer in audit.get("supplier_offers", []):
                key = ("supplier", offer["candidate_id"], offer["supplier"], offer["exact_sku"])
                if key in supplier_conflict_keys:
                    offer["issues"] = sorted(set(offer["issues"] + ["conflicting_offer"]))
                    offer["status"] = "quarantined"
            audit["supplier_offers_accepted"] = sum(offer["status"] == "accepted" for offer in audit.get("supplier_offers", []))
            audit["supplier_offers_quarantined"] = sum(offer["status"] == "quarantined" for offer in audit.get("supplier_offers", []))
            audit["supplier_offer_issues"] = sorted({issue for offer in audit.get("supplier_offers", []) for issue in offer["issues"]})
            audit["records_accepted"] = audit["supplier_offers_accepted"]
            audit["records_quarantined"] = audit["supplier_offers_quarantined"]
        supplier_records = [record for record in supplier_records if _record_conflict_key(record, "supplier") not in supplier_conflict_keys]
        warnings.append("supplier_offer:conflicting_offer")

    supplier_report = build_supplier_report(supplier_records, evidence_mode="manual_import", target_sell_prices={key: value.get("target_sell_price") for key, value in metadata.items() if value.get("target_sell_price") is not None}).to_dict()
    marketplace_report = build_marketplace_report(marketplace_records, evidence_mode="manual_import").to_dict()
    consumer_report = build_consumer_report(consumer_records, evidence_mode="manual_import", supplier_proof_by_candidate={key: bool(_best(supplier_report, key)) for key in candidate_ids}).to_dict()
    benchmark_candidates = _benchmark_candidates(candidate_ids, metadata, marketplace_report, supplier_report, lane)
    benchmark_report = build_benchmark_matrix(candidates=benchmark_candidates).to_dict()
    synthesis_report = build_product_opportunity_synthesis(marketplace_report, supplier_report, consumer_report).to_dict()
    readiness_report = build_phase1_readiness(benchmark_report=benchmark_report, public_market_benchmark_report=public_market_report, generated_at="deterministic", environ={}).to_dict()
    report = generate_product_report(
        client_name=_text(manifest.get("client_name") or "", "client_name"),
        benchmark=benchmark_report,
        public_market=public_market_report,
        readiness=readiness_report,
        marketplace_trends=marketplace_report,
        supplier_feasibility=supplier_report,
        consumer_attention=consumer_report,
        opportunity_synthesis=synthesis_report,
    ).to_dict()
    validation_warnings = sorted(set(warnings + ["manual_evidence_is_not_live_supplier_proof", "no_launch_or_spend_authority"]))
    if not supplier_records:
        validation_warnings.append("supplier_evidence_missing")
    if not marketplace_records:
        validation_warnings.append("marketplace_evidence_missing")
    if not consumer_records:
        validation_warnings.append("consumer_attention_evidence_missing")
    if report.get("overall_recommendation") == "advance_to_launch_draft":
        report["overall_recommendation"] = "hold_for_manual_review"
        validation_warnings.append("manual_evidence_cannot_authorize_launch")
    appendix = {
        "research_to_decision_version": "v1",
        "captured_at": captured_at,
        "market_lane": lane,
        "lane": lane,
        "input_audit": sorted(input_audit, key=lambda item: (item["role"], item["label"])),
        "validation": {"status": "hold_for_manual_review" if validation_warnings else "ready_for_operator_review", "warnings": sorted(set(validation_warnings)), "read_only": True, "network_calls": False, "credentials_used": False, "provider_calls": False, "orders_or_spend": False},
        "supplier_offers": sorted((offer for offers in supplier_offers_by_candidate.values() for offer in offers), key=lambda item: (item["candidate_id"], item["offer_id"])),
        "candidate_audit": _candidate_audit(candidate_ids, metadata, marketplace_report, supplier_report, synthesis_report, lane, supplier_offers_by_candidate, evidence_refs_by_candidate, captured_at),
        "promotion_lifecycle_contract": {
            "version": "research-to-decision-promotion-lifecycle-v1",
            "states": list(PROMOTION_LIFECYCLE_STATES),
            "transition_identity": "sha256(canonical transition fields)",
            "live_validation_requires": "genuine live evidence; fixture/manual/assumed evidence cannot emit live_validated",
        },
        "client_safe_projection": {
            "version": "research-to-decision-client-safe-v1",
            "candidates": [],
            "read_only": True,
            "launch_authorized": False,
            "provider_calls": False,
            "network_calls": False,
            "mutated": False,
        },
        "integration_contract": {
            "authority": "scripts.research_to_decision.py",
            "cockpit": "appendix.client_safe_projection",
            "commerce_cycle_dry_run": "existing source_reports and economics",
            "report_export": "product-validation-report-v1",
            "replay": "appendix.replay_fingerprint",
            "promotion_lifecycle": "appendix.candidate_audit[].promotion_lifecycle",
        },
        "source_authorities": {"supplier": "evaluation.commerce.supplier_feasibility", "marketplace": "evaluation.commerce.marketplace_trends", "consumer_attention": "evaluation.commerce.consumer_attention", "synthesis": "evaluation.commerce.opportunity_synthesis", "packet": "evaluation.commerce.product_validation_report"},
    }
    appendix["client_safe_projection"]["candidates"] = [
        {
            "candidate_id": item["candidate_id"],
            "title": item["title"],
            "decision": item["decision"],
            "decision_outcome": item["decision_outcome"],
            "next_action": item["next_action"],
            "risk_state": item["risk_state"],
            "freshness": item["freshness"],
            "confidence": item["confidence"],
            "missing_evidence": item["missing_evidence"],
            "evidence_gaps": item["evidence_gaps"],
            "hard_gates": item["hard_gates"],
            "evidence_refs": item["evidence_refs"],
            "promotion_state": item["promotion_lifecycle"][-1]["next_state"],
        }
        for item in appendix["candidate_audit"]
    ]
    fingerprint_input = {"report": report, "appendix": appendix}
    appendix["replay_fingerprint"] = hashlib.sha256(json.dumps(fingerprint_input, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    report["appendix"] = appendix
    report["source_reports"] = {**report.get("source_reports", {}), "research_to_decision": "supplied"}
    report["overall_recommendation"] = "hold_for_manual_review" if validation_warnings else report.get("overall_recommendation", "hold_for_manual_review")
    return report


def load_manifest(path: str | Path) -> tuple[dict[str, Any], Path]:
    candidate = Path(path)
    if candidate.stat().st_size > MAX_MANIFEST_BYTES:
        raise ResearchToDecisionError(f"manifest exceeds {MAX_MANIFEST_BYTES} bytes")
    raw = candidate.read_text(encoding="utf-8")
    _reject_html(raw)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ResearchToDecisionError("malformed manifest JSON") from exc
    if _contains_secret(value):
        raise ResearchToDecisionError("secret-like manifest rejected")
    if not isinstance(value, Mapping):
        raise ResearchToDecisionError("manifest root must be an object")
    return dict(value), candidate.resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="relative-input manifest JSON")
    parser.add_argument(
        "--confirm-supplier-document",
        action="append",
        nargs=3,
        default=[],
        metavar=("OFFER_ID", "EXACT_SKU", "REFERENCE"),
        help="local operator attestation after review; must match one manually imported offer exactly",
    )
    parser.add_argument(
        "--supplier-evidence-root",
        help="local directory that --confirm-supplier-document-digest references may resolve under; required only if that flag is used",
    )
    parser.add_argument(
        "--confirm-supplier-document-digest",
        action="append",
        nargs=4,
        default=[],
        metavar=("OFFER_ID", "EXACT_SKU", "REFERENCE", "SHA256_DIGEST"),
        help="bind a manual document reference to real evidence bytes under --supplier-evidence-root; proves document byte integrity only, not supplier identity or human review",
    )
    parser.add_argument("--json", action="store_true", help="emit the existing report as JSON")
    parser.add_argument("--output", help="optional output file; no file is written by default")
    args = parser.parse_args(argv)
    try:
        manifest, base_dir = load_manifest(args.manifest)
        report = build_research_to_decision(
            manifest,
            base_dir=base_dir,
            operator_confirmed_supplier_documents=args.confirm_supplier_document,
            supplier_evidence_root=args.supplier_evidence_root,
            confirmed_supplier_document_evidence=args.confirm_supplier_document_digest,
        )
    except (OSError, ResearchToDecisionError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, sort_keys=True))
        return 2
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n" if args.json else json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        target = Path(args.output)
        target.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
