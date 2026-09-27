"""services.category_mapping.taxonomy_loader -- deterministic, offline
loader/parser for the pinned, partial Shopify Product Taxonomy snapshot.

No network access, no dependency on any external package: this module reads
one bundled, versioned text file (or, for tests, an equivalent in-memory
string in the identical format) and fails closed on any malformed, duplicate,
or structurally inconsistent row rather than silently dropping it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .schemas import CategoryTaxonomyError, TaxonomyCategory

_DEFAULT_SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "shopify_product_taxonomy" / "categories.v2026-08.partial.txt"
)

_LINE_RE = re.compile(r"^gid://shopify/TaxonomyCategory/(\S+)\s*:\s*(.+?)\s*$")


@dataclass(frozen=True)
class TaxonomyIndex:
    """An immutable, validated index over the loaded taxonomy snapshot."""

    by_code: dict[str, TaxonomyCategory]

    def get(self, code: str) -> TaxonomyCategory | None:
        return self.by_code.get(code)

    def __len__(self) -> int:
        return len(self.by_code)

    def __iter__(self):
        return iter(self.by_code.values())


def _parse_line(line: str, line_number: int) -> tuple[str, str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    match = _LINE_RE.match(stripped)
    if not match:
        raise CategoryTaxonomyError(f"malformed taxonomy row at line {line_number}: {line!r}")
    code, full_path = match.group(1), match.group(2)
    if not code or "//" in code or code.startswith("-") or code.endswith("-") or "--" in code:
        raise CategoryTaxonomyError(f"malformed taxonomy code at line {line_number}: {code!r}")
    if not full_path:
        raise CategoryTaxonomyError(f"empty taxonomy path at line {line_number} for code {code!r}")
    gid = f"gid://shopify/TaxonomyCategory/{code}"
    return code, gid, full_path


def parse_taxonomy_text(text: str) -> TaxonomyIndex:
    """Parse the pinned snapshot format into a validated :class:`TaxonomyIndex`.

    Fails closed (raises :class:`CategoryTaxonomyError`) on:
    - a data row that does not match the pinned ``{GID} : {path}`` format;
    - a duplicate category code;
    - a category whose declared parent code is not itself present in the
      same snapshot (parent/path consistency);
    - a category whose full path's segment count does not match its code's
      hierarchy depth, or whose path does not end in its own declared name.
    """
    by_code: dict[str, TaxonomyCategory] = {}
    seen_codes: set[str] = set()

    for line_number, line in enumerate(text.splitlines(), start=1):
        parsed = _parse_line(line, line_number)
        if parsed is None:
            continue
        code, gid, full_path = parsed

        if code in seen_codes:
            raise CategoryTaxonomyError(f"duplicate taxonomy code {code!r} at line {line_number}")
        seen_codes.add(code)

        segments = code.split("-")
        level = len(segments)
        path_parts = [part.strip() for part in full_path.split(">")]
        if len(path_parts) != level:
            raise CategoryTaxonomyError(
                f"path depth mismatch for code {code!r} at line {line_number}: "
                f"code implies level {level}, path has {len(path_parts)} segments"
            )
        name = path_parts[-1]
        if not name:
            raise CategoryTaxonomyError(f"empty leaf name for code {code!r} at line {line_number}")

        parent_code = "-".join(segments[:-1]) if level > 1 else None

        by_code[code] = TaxonomyCategory(
            code=code,
            gid=gid,
            name=name,
            full_path=full_path,
            parent_code=parent_code,
            level=level,
        )

    for category in by_code.values():
        if category.parent_code is not None and category.parent_code not in by_code:
            raise CategoryTaxonomyError(
                f"category {category.code!r} declares parent {category.parent_code!r}, "
                "which is not present in this snapshot"
            )
        if category.parent_code is not None:
            parent = by_code[category.parent_code]
            if not category.full_path.startswith(parent.full_path + " > "):
                raise CategoryTaxonomyError(
                    f"category {category.code!r} path {category.full_path!r} is not a child "
                    f"path of its declared parent {category.parent_code!r} ({parent.full_path!r})"
                )

    if not by_code:
        raise CategoryTaxonomyError("taxonomy snapshot contained zero valid category rows")

    return TaxonomyIndex(by_code=by_code)


def load_taxonomy(path: Path | None = None) -> TaxonomyIndex:
    """Load and validate the taxonomy snapshot from disk. Deterministic: the
    same file always produces the same :class:`TaxonomyIndex` contents."""
    snapshot_path = path or _DEFAULT_SNAPSHOT_PATH
    text = snapshot_path.read_text(encoding="utf-8")
    return parse_taxonomy_text(text)


@lru_cache(maxsize=1)
def _cached_default_taxonomy() -> TaxonomyIndex:
    return load_taxonomy()


def default_taxonomy() -> TaxonomyIndex:
    """The bundled snapshot, parsed once and reused. Callers that need an
    isolated/injected taxonomy (tests, or a future alternate snapshot) should
    call :func:`load_taxonomy` or :func:`parse_taxonomy_text` directly instead."""
    return _cached_default_taxonomy()
