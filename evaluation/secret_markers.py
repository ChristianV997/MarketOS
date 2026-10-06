"""Shared secret-marker scanning for untrusted text inputs."""
from __future__ import annotations

import re

# Keep the pre-existing boundary rules as a first scan so normalization never
# weakens detection of URL-escaped or literal newline/tab/carriage-return forms.
_LEGACY_SK_PREFIX = re.compile(r"(?<![a-z0-9])sk-|(?<=%[0-9a-f]{2})sk-|(?<=\\[nrt])sk-")
_BOUNDARY_SK_PREFIX = re.compile(r"(?<![a-z0-9])sk-")
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_OCTAL_DIGITS = frozenset("01234567")
_MAX_DECODE_PASSES = 10
_SIMPLE_ESCAPES = {
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}


def _decode_one_pass(s: str) -> str:
    output: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "%" and i + 2 < n and s[i + 1] in _HEX_DIGITS and s[i + 2] in _HEX_DIGITS:
            output.append(chr(int(s[i + 1 : i + 3], 16)))
            i += 3
            continue
        if s[i] == "\\" and i + 1 < n:
            c = s[i + 1]
            c_low = c.lower()
            if c in _OCTAL_DIGITS:
                j = i + 1
                while j < n and j < i + 4 and s[j] in _OCTAL_DIGITS:
                    j += 1
                if j - (i + 1) == 3 and int(s[i + 1 : j], 8) > 0o377:
                    j -= 1
                output.append(chr(int(s[i + 1 : j], 8)))
                i = j
                continue
            if c_low in _SIMPLE_ESCAPES:
                output.append(_SIMPLE_ESCAPES[c_low])
                i += 2
                continue
            if c_low == "x" and i + 3 < n and s[i + 2] in _HEX_DIGITS and s[i + 3] in _HEX_DIGITS:
                output.append(chr(int(s[i + 2 : i + 4], 16)))
                i += 4
                continue
            if c_low == "u":
                if i + 9 < n and all(ch in _HEX_DIGITS for ch in s[i + 2 : i + 10]):
                    codepoint = int(s[i + 2 : i + 10], 16)
                    output.append(chr(codepoint) if codepoint <= 0x10FFFF else "\ufffd")
                    i += 10
                    continue
                if i + 5 < n and all(ch in _HEX_DIGITS for ch in s[i + 2 : i + 6]):
                    codepoint = int(s[i + 2 : i + 6], 16)
                    output.append(chr(codepoint) if codepoint <= 0x10FFFF else "\ufffd")
                    i += 6
                    continue
        output.append(s[i])
        i += 1
    return "".join(output)


def _canonical_secret_marker_view(value: str) -> tuple[str, bool]:
    """Decode separator escapes into a detection-only view; never return it externally.

    The flag is False when decoding had not converged, which callers treat as suspicious.
    """
    current = value
    for _ in range(_MAX_DECODE_PASSES):
        next_view = _decode_one_pass(current)
        if next_view == current:
            return current, True
        current = next_view
    return current, _decode_one_pass(current) == current


def contains_boundary_prefixed_sk_token(value: str) -> bool:
    """Check the original and canonical views without changing or echoing input."""
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    if _LEGACY_SK_PREFIX.search(lowered) is not None:
        return True
    view, converged = _canonical_secret_marker_view(value)
    if not converged:
        return True  # fail closed on deeply nested encodings
    return _BOUNDARY_SK_PREFIX.search(view.lower()) is not None


__all__ = ["contains_boundary_prefixed_sk_token"]
