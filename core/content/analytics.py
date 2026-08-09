"""core.content.analytics — aggregate hook and angle performance from memory."""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def analyze(memory: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate average engagement per hook and per angle.

    Parameters
    ----------
    memory:
        List of content feature/performance dicts containing ``hook``,
        ``angle``, and ``engagement`` keys.

    Returns
    -------
    dict
        ``{"hooks": {hook: avg_engagement}, "angles": {angle: avg_engagement}}``.
    """
    hooks: dict[str, list[float]] = defaultdict(list)
    angles: dict[str, list[float]] = defaultdict(list)

    for m in memory:
        engagement = float(m.get("engagement", 0.0))
        hook = m.get("hook", "")
        angle = m.get("angle", "")
        if hook:
            hooks[hook].append(engagement)
        if angle:
            angles[angle].append(engagement)

    hook_perf = {k: sum(v) / len(v) for k, v in hooks.items()}
    angle_perf = {k: sum(v) / len(v) for k, v in angles.items()}

    return {"hooks": hook_perf, "angles": angle_perf}
