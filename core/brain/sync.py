"""core.brain.sync — bridge between my_OS execution data and Obsidian vault.

Step 69: Obsidian + Claude Second Brain Integration

The vault is a directory of Markdown files organised as::

    brain/
      raw/           — daily raw notes
      signals/       — scored trend signals
      niches/        — cluster niche summaries
      creatives/     — creative performance records
      ads/           — ad campaign results
      insights/      — synthesised insights
      playbooks/     — reusable playbooks

``export_to_obsidian`` writes structured data as Markdown notes.
``import_from_obsidian`` reads structured notes back into the system.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_VAULT = Path("brain")


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


_JSON_BLOCK_START = "```json\n"
_JSON_BLOCK_START_LEN = len(_JSON_BLOCK_START)


def export_to_obsidian(
    data: dict[str, Any],
    category: str = "raw",
    vault: Path | str = _DEFAULT_VAULT,
) -> Path:
    """Write *data* as a Markdown note under ``<vault>/<category>/``.

    Parameters
    ----------
    data:
        Dict to serialise into the note body.
    category:
        Sub-folder inside the vault (e.g. ``"signals"``, ``"ads"``).
    vault:
        Root path of the Obsidian vault.

    Returns
    -------
    Path
        Path of the written Markdown file.
    """
    vault = Path(vault)
    dest = _ensure_dir(vault / category)
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    filename = dest / f"{ts}.md"
    with filename.open("w", encoding="utf-8") as fh:
        fh.write(f"# {category} — {ts}\n\n")
        fh.write("```json\n")
        fh.write(json.dumps(data, indent=2))
        fh.write("\n```\n")
    return filename


def import_from_obsidian(
    category: str = "raw",
    vault: Path | str = _DEFAULT_VAULT,
) -> list[dict[str, Any]]:
    """Read and parse all Markdown notes under ``<vault>/<category>/``.

    Parameters
    ----------
    category:
        Sub-folder to read from.
    vault:
        Root path of the Obsidian vault.

    Returns
    -------
    list[dict]
        Parsed data objects extracted from JSON code-blocks.
    """
    vault = Path(vault)
    folder = vault / category
    if not folder.exists():
        return []

    results = []
    for md_file in sorted(folder.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        # extract first JSON code-block
        start = text.find(_JSON_BLOCK_START)
        end = text.find("\n```", start + _JSON_BLOCK_START_LEN)
        if start != -1 and end != -1:
            raw = text[start + _JSON_BLOCK_START_LEN: end]
            try:
                results.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
    return results
