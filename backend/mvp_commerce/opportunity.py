"""Conservative public-signal-to-candidate transformation."""
from __future__ import annotations
import hashlib
from collections import defaultdict
from backend.signals.public_signal_models import PublicSignal
from .models import OpportunityCandidate


def _product_name(title: str) -> str:
    words = [word.strip(".,:;!?- ") for word in title.split() if word.strip(".,:;!?- ")]
    return " ".join(words[:3]).title() or "Unspecified Product Hypothesis"


def _key(signal: PublicSignal) -> str:
    return " ".join(signal.title.lower().split()[:2]) or signal.signal_id


def build_opportunity_candidates_from_signals(signals: list[PublicSignal], workspace_id: str, query: str, limit: int = 5) -> list[OpportunityCandidate]:
    groups: dict[str, list[PublicSignal]] = defaultdict(list)
    for signal in signals: groups[_key(signal)].append(signal)
    candidates: list[OpportunityCandidate] = []
    for key, rows in sorted(groups.items(), key=lambda item: (-len(item[1]), -sum(x.score for x in item[1]), item[0]))[:max(1, limit)]:
        rows = sorted(rows, key=lambda item: (-item.score, item.rank, item.signal_id))
        local = round(min(100.0, sum(item.score for item in rows) * 35 + len(rows) * 12), 2)
        recency = round(100.0 if len({item.observed_at for item in rows}) > 1 else 50.0, 2)
        confidence = "thin" if len(rows) < 2 else "low"
        identifier = hashlib.sha256((workspace_id + query + key).encode()).hexdigest()[:16]
        candidates.append(OpportunityCandidate(
            f"commerce-candidate-{identifier}", workspace_id, query, _product_name(rows[0].title), "public_signal_hypothesis",
            tuple(item.signal_id for item in rows), tuple(item.title for item in rows), tuple(sorted({item.evidence_url for item in rows})), len(rows), local, recency,
            "weak" if len(rows) < 2 else "moderate", confidence,
            ("Candidate grouping uses public-news title similarity and source-local scores only.",),
            ("Supplier cost, stock, buyer intent, conversion, demand, and viability are unverified.",),
            ("No demand, sales, ROAS, profitability, supplier viability, or launch-readiness claim is supported.",),
            "Collect supplier, price, and customer-problem evidence manually before advancing."))
    return candidates


def score_candidate(candidate: OpportunityCandidate) -> float: return round(min(100.0, candidate.source_local_score * .7 + candidate.recency_score * .3), 2)
def select_candidate(candidates: list[OpportunityCandidate]) -> OpportunityCandidate | None: return sorted(candidates, key=lambda item: (-score_candidate(item), item.candidate_id))[0] if candidates else None
def explain_candidate(candidate: OpportunityCandidate) -> str: return f"{candidate.product_name} is a low-confidence public-signal hypothesis supported by {candidate.source_count} attributed signal(s)."
