"""Shared secret-marker scanning for untrusted text inputs."""
from __future__ import annotations

import re

# Keep the pre-existing boundary rules as a first scan so normalization never
# weakens detection of URL-escaped or literal newline/tab/carriage-return forms.
_LEGACY_SK_PREFIX = re.compile(r"(?<![a-z0-9])sk-|(?<=%[0-9a-f]{2})sk-|(?<=\\[nrt])sk-")
_BOUNDARY_SK_PREFIX = re.compile(r"(?<![a-z0-9])sk-")
_BACKSLASH_ESCAPE = re.compile(r"\\(?:[abfnrtv0]|x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8})$")
_SIMPLE_ESCAPES = {
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "0": "\0",
}
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _decode_backslash_escape(escape: str) -> str:
    body = escape[1:]
    if len(body) == 1:
        return _SIMPLE_ESCAPES[body.lower()]
    try:
        codepoint = int(body[1:], 16)
    except ValueError:
        return "\ufffd"
    if codepoint > 0x10FFFF:
        return "\ufffd"
    return chr(codepoint)


def _canonical_secret_marker_view(value: str) -> str:
    """Decode separator escapes into a detection-only view; never return it externally."""
    output: list[str] = []
    for char in value:
        output.append(char)
        while True:
            if len(output) >= 3 and output[-3] == "%" and output[-2] in _HEX_DIGITS and output[-1] in _HEX_DIGITS:
                byte = int("".join(output[-2:]), 16)
                output[-3:] = [chr(byte)]
                continue
            tail = "".join(output[-10:])
            escape_match = _BACKSLASH_ESCAPE.search(tail)
            if escape_match is None:
                break
            escape = escape_match.group(0)
            del output[-len(escape) :]
            output.append(_decode_backslash_escape(escape))
    return "".join(output)


def contains_boundary_prefixed_sk_token(value: str) -> bool:
    """Check the original and canonical views without changing or echoing input."""
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    if _LEGACY_SK_PREFIX.search(lowered) is not None:
        return True
    return _BOUNDARY_SK_PREFIX.search(_canonical_secret_marker_view(value).lower()) is not None


__all__ = ["contains_boundary_prefixed_sk_token"]
