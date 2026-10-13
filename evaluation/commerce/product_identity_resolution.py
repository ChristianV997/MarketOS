"""Conservative, deterministic cross-source product identity resolution.

Links marketplace listings, supplier offers, and consumer-attention observations
to stable product candidate keys when identifiers are strong and non-conflicting.

This module does **not**:
  * create a second product catalog, evidence authority, or scorer
  * treat event IDs or workspace-scoped IDs as global product identity
  * treat seller SKUs as globally unique
  * auto-merge on name/similarity alone
  * invent GTINs / manufacturer identifiers
  * upgrade fixture/manual evidence to live
  * join across workspace / client boundaries

Reuse existing ``evaluation.contracts.ProductCandidate`` for candidate summaries.
Opportunity synthesis and pillar scorers remain authoritative for scoring.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from evaluation.contracts import DataQuality, ProductCandidate

MATCH_STATES: tuple[str, ...] = (
    "exact_match",
    "possible_match",
    "ambiguous",
    "conflict",
    "unmatched",
)

SOURCE_KINDS: tuple[str, ...] = (
    "marketplace",
    "supplier",
    "consumer_attention",
)

EVIDENCE_MODES: tuple[str, ...] = (
    "fixture",
    "manual_import",
    "observed",
    "derived",
    "live_readonly",
    "assumed",
    "unknown",
)

_CONTROL = re.compile(r"[\x00-\x1f]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_DIGITS = re.compile(r"\D+")

# Retail GTIN forms: normalize digits; pad UPC-12 → EAN-13. Pattern guidance
# from public identifier-normalization practice; no third-party code copied.
_GTIN_LENGTHS = {8, 12, 13, 14}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if _CONTROL.search(text):
        raise ValueError("text fields must not contain control characters")
    return text


def _norm_token(value: Any) -> str:
    return _NON_ALNUM.sub("", _clean_text(value).lower())


def normalize_gtin(value: Any) -> str:
    """Normalize GTIN/UPC/EAN to a canonical digit string, or empty if weak.

    Does not invent identifiers. Length + digit shape only (no check-digit
    gate — real catalogs often carry off-by-one rows).
    """
    digits = _DIGITS.sub("", _clean_text(value))
    if not digits or not digits.isdigit():
        return ""
    if len(digits) == 12:
        digits = "0" + digits
    if len(digits) == 14 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) not in _GTIN_LENGTHS:
        return ""
    return digits


def normalize_asin(value: Any) -> str:
    text = _clean_text(value).upper()
    if len(text) == 10 and text.isalnum():
        return text
    return ""


@dataclass(frozen=True)
class ProductObservation:
    """One source-attributed observation that may refer to a product.

    ``observation_id``, ``event_id``, and ``workspace_id`` are provenance /
    tenancy fields — never product identity by themselves.
    """

    observation_id: str
    workspace_id: str
    source_kind: str
    source_system: str
    source_record_id: str
    title: str = ""
    brand: str = ""
    model: str = ""
    gtin: str = ""
    asin: str = ""
    mpn: str = ""
    seller_sku: str = ""
    seller_id: str = ""
    pack_size: str = ""
    variant_size: str = ""
    variant_color: str = ""
    currency: str = ""
    observed_at: str = ""
    evidence_mode: str = "fixture"
    event_id: str = ""
    candidate_id_hint: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_id", _clean_text(self.observation_id))
        object.__setattr__(self, "workspace_id", _clean_text(self.workspace_id))
        if not self.observation_id:
            raise ValueError("observation_id is required")
        if not self.workspace_id:
            raise ValueError("workspace_id is required")
        kind = _clean_text(self.source_kind)
        if kind not in SOURCE_KINDS:
            raise ValueError(f"unsupported source_kind: {kind}")
        object.__setattr__(self, "source_kind", kind)
        object.__setattr__(self, "source_system", _clean_text(self.source_system))
        object.__setattr__(self, "source_record_id", _clean_text(self.source_record_id))
        if not self.source_system or not self.source_record_id:
            raise ValueError("source_system and source_record_id are required")
        mode = _clean_text(self.evidence_mode) or "unknown"
        if mode not in EVIDENCE_MODES:
            raise ValueError(f"unsupported evidence_mode: {mode}")
        object.__setattr__(self, "evidence_mode", mode)
        object.__setattr__(self, "title", _clean_text(self.title))
        object.__setattr__(self, "brand", _clean_text(self.brand))
        object.__setattr__(self, "model", _clean_text(self.model))
        object.__setattr__(self, "gtin", normalize_gtin(self.gtin))
        object.__setattr__(self, "asin", normalize_asin(self.asin))
        object.__setattr__(self, "mpn", _clean_text(self.mpn))
        object.__setattr__(self, "seller_sku", _clean_text(self.seller_sku))
        object.__setattr__(self, "seller_id", _clean_text(self.seller_id))
        object.__setattr__(self, "pack_size", _clean_text(self.pack_size))
        object.__setattr__(self, "variant_size", _clean_text(self.variant_size))
        object.__setattr__(self, "variant_color", _clean_text(self.variant_color))
        object.__setattr__(self, "currency", _clean_text(self.currency))
        object.__setattr__(self, "observed_at", _clean_text(self.observed_at))
        object.__setattr__(self, "event_id", _clean_text(self.event_id))
        object.__setattr__(self, "candidate_id_hint", _clean_text(self.candidate_id_hint))

    @property
    def normalized_title(self) -> str:
        return _norm_token(self.title)

    @property
    def brand_mpn_key(self) -> str:
        brand = _norm_token(self.brand)
        mpn = _norm_token(self.mpn)
        if brand and mpn:
            return f"{brand}|{mpn}"
        return ""

    @property
    def seller_sku_key(self) -> str:
        sku = _norm_token(self.seller_sku)
        seller = _norm_token(self.seller_id)
        system = _norm_token(self.source_system)
        if sku and seller and system:
            return f"{system}|{seller}|{sku}"
        return ""

    @property
    def source_record_key(self) -> str:
        return f"{self.source_kind}|{self.source_system}|{self.source_record_id}"

    @property
    def candidate_hint_key(self) -> str:
        """Workspace-local candidate hint — never a strong exact-match basis."""
        return _norm_token(self.candidate_id_hint)

    @property
    def variant_fingerprint(self) -> tuple[str, str, str]:
        return (
            _norm_token(self.pack_size),
            _norm_token(self.variant_size),
            _norm_token(self.variant_color),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "workspace_id": self.workspace_id,
            "source_kind": self.source_kind,
            "source_system": self.source_system,
            "source_record_id": self.source_record_id,
            "title": self.title,
            "brand": self.brand,
            "model": self.model,
            "gtin": self.gtin,
            "asin": self.asin,
            "mpn": self.mpn,
            "seller_sku": self.seller_sku,
            "seller_id": self.seller_id,
            "pack_size": self.pack_size,
            "variant_size": self.variant_size,
            "variant_color": self.variant_color,
            "currency": self.currency,
            "observed_at": self.observed_at,
            "evidence_mode": self.evidence_mode,
            "event_id": self.event_id,
            "candidate_id_hint": self.candidate_id_hint,
        }


@dataclass(frozen=True)
class ProductIdentityLink:
    observation_id: str
    workspace_id: str
    candidate_key: str
    match_state: str
    source_kind: str
    source_system: str
    source_record_id: str
    evidence_mode: str
    match_basis: tuple[str, ...] = ()
    conflict_reasons: tuple[str, ...] = ()
    suggested_peer_ids: tuple[str, ...] = ()
    currency: str = ""
    observed_at: str = ""
    gtin: str = ""
    asin: str = ""
    brand: str = ""
    model: str = ""
    mpn: str = ""
    title: str = ""

    def __post_init__(self) -> None:
        if self.match_state not in MATCH_STATES:
            raise ValueError(f"unsupported match_state: {self.match_state}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "workspace_id": self.workspace_id,
            "candidate_key": self.candidate_key,
            "match_state": self.match_state,
            "source_kind": self.source_kind,
            "source_system": self.source_system,
            "source_record_id": self.source_record_id,
            "evidence_mode": self.evidence_mode,
            "match_basis": list(self.match_basis),
            "conflict_reasons": list(self.conflict_reasons),
            "suggested_peer_ids": list(self.suggested_peer_ids),
            "currency": self.currency,
            "observed_at": self.observed_at,
            "gtin": self.gtin,
            "asin": self.asin,
            "brand": self.brand,
            "model": self.model,
            "mpn": self.mpn,
            "title": self.title,
        }


@dataclass(frozen=True)
class ProductIdentityResolutionReport:
    schema_version: str = "product-identity-resolution-v1"
    links: tuple[ProductIdentityLink, ...] = ()
    candidates: tuple[dict[str, Any], ...] = ()
    evidence_modes_seen: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    pillar_separation: Mapping[str, bool] = field(
        default_factory=lambda: {
            "consumer_attention_is_not_supplier_proof": True,
            "consumer_attention_is_not_marketplace_price_proof": True,
            "fixture_manual_never_upgraded_to_live": True,
            "product_identity_is_not_attention_evidence": True,
            "product_identity_is_not_marketplace_price_proof": True,
            "product_identity_is_not_supplier_proof": True,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "links": [link.to_dict() for link in self.links],
            "candidates": [dict(item) for item in self.candidates],
            "evidence_modes_seen": list(self.evidence_modes_seen),
            "warnings": list(self.warnings),
            "pillar_separation": dict(self.pillar_separation),
        }


def to_opportunity_synthesis_handoff(
    report: ProductIdentityResolutionReport,
) -> dict[str, Any]:
    """Stable, tested handoff for opportunity-synthesis consumers (#483).

    Does not import or mutate ``opportunity_synthesis``. Callers may attach
    ``candidate_key`` / ``match_state`` onto pillar evidence; they must not
    treat identity links as attention, price, supplier, or launch authority.
    """
    exact_links = tuple(link for link in report.links if link.match_state == "exact_match")
    conflict_links = tuple(link for link in report.links if link.match_state == "conflict")
    review_links = tuple(
        link for link in report.links if link.match_state in {"possible_match", "ambiguous"}
    )
    by_observation = {
        link.observation_id: {
            "candidate_key": link.candidate_key,
            "match_state": link.match_state,
            "match_basis": list(link.match_basis),
            "conflict_reasons": list(link.conflict_reasons),
            "source_kind": link.source_kind,
            "evidence_mode": link.evidence_mode,
            "workspace_id": link.workspace_id,
        }
        for link in report.links
    }
    return {
        "contract_version": "product-identity-synthesis-handoff-v1",
        "schema_version": report.schema_version,
        "exact_match_observation_ids": [link.observation_id for link in exact_links],
        "conflict_observation_ids": [link.observation_id for link in conflict_links],
        "review_only_observation_ids": [link.observation_id for link in review_links],
        "by_observation_id": by_observation,
        "candidates": [dict(item) for item in report.candidates],
        "auto_merge_allowed_states": ["exact_match"],
        "never_auto_merge_states": ["possible_match", "ambiguous", "conflict", "unmatched"],
        "candidate_id_hint_is_not_exact_basis": True,
        "pillar_separation": dict(report.pillar_separation),
        "warnings": list(report.warnings),
        "integration_notes": [
            "Consume only exact_match candidate_key joins for automatic fusion.",
            "possible_match/ambiguous require human review; conflict blocks merge.",
            "candidate_id_hint never authorizes exact_match by itself.",
            "Identity links are not attention, marketplace price, or supplier proof.",
        ],
    }


def _stable_key(workspace_id: str, namespace: str, material: str) -> str:
    digest = uuid.uuid5(uuid.NAMESPACE_URL, f"{workspace_id}|{namespace}|{material}").hex
    return f"pid:{workspace_id}:{namespace}:{digest[:16]}"


def _variant_compatible(a: ProductObservation, b: ProductObservation) -> bool:
    for left, right in zip(a.variant_fingerprint, b.variant_fingerprint, strict=True):
        if left and right and left != right:
            return False
    return True


def _brand_model_compatible(a: ProductObservation, b: ProductObservation) -> bool:
    brand_a, brand_b = _norm_token(a.brand), _norm_token(b.brand)
    model_a, model_b = _norm_token(a.model), _norm_token(b.model)
    if brand_a and brand_b and brand_a != brand_b:
        return False
    if model_a and model_b and model_a != model_b:
        return False
    return True


def _attribute_conflict(a: ProductObservation, b: ProductObservation) -> tuple[str, ...]:
    reasons: list[str] = []
    if not _variant_compatible(a, b):
        reasons.append("variant_or_pack_size_conflict")
    if not _brand_model_compatible(a, b):
        reasons.append("brand_or_model_conflict")
    if a.gtin and b.gtin and a.gtin != b.gtin:
        reasons.append("gtin_conflict")
    if a.asin and b.asin and a.asin != b.asin:
        reasons.append("asin_conflict")
    bmpn_a, bmpn_b = a.brand_mpn_key, b.brand_mpn_key
    if bmpn_a and bmpn_b and bmpn_a != bmpn_b:
        reasons.append("brand_mpn_conflict")
    return tuple(reasons)


class _UnionFind:
    def __init__(self, items: Iterable[str]) -> None:
        material = list(items)
        self.parent = {item: item for item in material}
        self.rank = {item: 0 for item in material}

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, a: str, b: str) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a == root_b:
            return
        if self.rank[root_a] < self.rank[root_b]:
            self.parent[root_a] = root_b
        elif self.rank[root_a] > self.rank[root_b]:
            self.parent[root_b] = root_a
        else:
            self.parent[root_b] = root_a
            self.rank[root_a] += 1


def _index_by(
    observations: Sequence[ProductObservation],
    key_fn: Callable[[ProductObservation], str],
) -> dict[str, list[ProductObservation]]:
    index: dict[str, list[ProductObservation]] = {}
    for obs in observations:
        key = key_fn(obs)
        if not key:
            continue
        index.setdefault(key, []).append(obs)
    return index


def _compatible_clusters(
    members: Sequence[ProductObservation],
) -> tuple[list[list[ProductObservation]], dict[str, set[str]], dict[str, set[str]]]:
    """Partition members into mutually attribute-compatible clusters.

    Returns clusters plus per-id conflict reasons and conflict peer ids.
    """
    ordered = tuple(sorted(members, key=lambda item: item.observation_id))
    clusters: list[list[ProductObservation]] = []
    conflict_reasons: dict[str, set[str]] = {m.observation_id: set() for m in ordered}
    conflict_peers: dict[str, set[str]] = {m.observation_id: set() for m in ordered}

    for obs in ordered:
        placed = False
        for cluster in clusters:
            # Must be compatible with every member already in the cluster.
            pairwise = [_attribute_conflict(existing, obs) for existing in cluster]
            if any(pairwise):
                for existing, conflicts in zip(cluster, pairwise, strict=True):
                    if not conflicts:
                        continue
                    conflict_reasons[obs.observation_id].update(conflicts)
                    conflict_reasons[existing.observation_id].update(conflicts)
                    conflict_peers[obs.observation_id].add(existing.observation_id)
                    conflict_peers[existing.observation_id].add(obs.observation_id)
                continue
            cluster.append(obs)
            placed = True
            break
        if not placed:
            clusters.append([obs])
    return clusters, conflict_reasons, conflict_peers


def resolve_product_identity(
    observations: Sequence[ProductObservation],
) -> ProductIdentityResolutionReport:
    """Resolve observations to candidate keys with explicit match states.

    Deterministic: input order does not affect ``to_dict()`` output.
    Fail-closed: weak or conflicting signals never produce ``exact_match``.
    """
    if not observations:
        return ProductIdentityResolutionReport()

    ordered = tuple(sorted(observations, key=lambda item: (item.workspace_id, item.observation_id)))
    if len({obs.observation_id for obs in ordered}) != len(ordered):
        raise ValueError("observation_id values must be unique within a resolve call")

    warnings: list[str] = [
        "product_identity_resolution_does_not_authorize_launch_or_spend",
        "seller_skus_are_not_globally_unique",
        "name_only_matches_are_review_only",
        "candidate_id_hint_is_never_exact_match_basis",
        "fixture_or_manual_evidence_is_never_upgraded_to_live",
    ]

    uf = _UnionFind(obs.observation_id for obs in ordered)
    exact_basis: dict[str, set[str]] = {obs.observation_id: set() for obs in ordered}
    conflict_for: dict[str, set[str]] = {obs.observation_id: set() for obs in ordered}
    conflict_peers: dict[str, set[str]] = {obs.observation_id: set() for obs in ordered}
    review_peers: dict[str, set[str]] = {obs.observation_id: set() for obs in ordered}
    review_state: dict[str, str] = {}

    def consider_exact(group: Sequence[ProductObservation], basis: str) -> None:
        if len(group) < 2:
            return
        clusters, c_reasons, c_peers = _compatible_clusters(group)
        for obs_id, reasons in c_reasons.items():
            conflict_for[obs_id].update(reasons)
        for obs_id, peers in c_peers.items():
            conflict_peers[obs_id].update(peers)
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            for member in cluster:
                exact_basis[member.observation_id].add(basis)
            root = cluster[0].observation_id
            for member in cluster[1:]:
                uf.union(root, member.observation_id)

    by_workspace: dict[str, list[ProductObservation]] = {}
    for obs in ordered:
        by_workspace.setdefault(obs.workspace_id, []).append(obs)

    for _workspace_id, workspace_obs in sorted(by_workspace.items()):
        for _key, group in sorted(_index_by(workspace_obs, lambda o: o.source_record_key).items()):
            consider_exact(group, "source_record")
        for _key, group in sorted(_index_by(workspace_obs, lambda o: o.gtin).items()):
            consider_exact(group, "gtin")
        for _key, group in sorted(_index_by(workspace_obs, lambda o: o.asin).items()):
            consider_exact(group, "asin")
        for _key, group in sorted(_index_by(workspace_obs, lambda o: o.brand_mpn_key).items()):
            consider_exact(group, "brand_mpn")
        for _key, group in sorted(_index_by(workspace_obs, lambda o: o.seller_sku_key).items()):
            consider_exact(group, "seller_sku_scoped")

        # candidate_id_hint is workspace-local sugar only. It never unions
        # components into exact_match; shared hints with attribute conflicts
        # surface conflict, and compatible hint-only peers stay review-only.
        for _hint, group in sorted(_index_by(workspace_obs, lambda o: o.candidate_hint_key).items()):
            if len(group) < 2:
                continue
            members = tuple(sorted(group, key=lambda item: item.observation_id))
            for i, left in enumerate(members):
                for right in members[i + 1 :]:
                    conflicts = _attribute_conflict(left, right)
                    if conflicts:
                        conflict_for[left.observation_id].update(conflicts)
                        conflict_for[right.observation_id].update(conflicts)
                        conflict_for[left.observation_id].add("candidate_id_hint_does_not_override_variant")
                        conflict_for[right.observation_id].add("candidate_id_hint_does_not_override_variant")
                        conflict_peers[left.observation_id].add(right.observation_id)
                        conflict_peers[right.observation_id].add(left.observation_id)
                        review_state[left.observation_id] = "conflict"
                        review_state[right.observation_id] = "conflict"
                    elif uf.find(left.observation_id) != uf.find(right.observation_id):
                        # Compatible but hint-only — never exact.
                        if not exact_basis[left.observation_id] or not exact_basis[right.observation_id]:
                            review_peers[left.observation_id].add(right.observation_id)
                            review_peers[right.observation_id].add(left.observation_id)
                            if review_state.get(left.observation_id) != "conflict":
                                review_state[left.observation_id] = "possible_match"
                            if review_state.get(right.observation_id) != "conflict":
                                review_state[right.observation_id] = "possible_match"

        title_index = _index_by(workspace_obs, lambda o: o.normalized_title)
        for _title_key, group in sorted(title_index.items()):
            if not _title_key or len(group) < 2:
                continue
            members = tuple(sorted(group, key=lambda item: item.observation_id))
            if (
                len({uf.find(m.observation_id) for m in members}) == 1
                and all(exact_basis[m.observation_id] for m in members)
            ):
                continue

            distinct_roots: list[str] = []
            for member in members:
                root = uf.find(member.observation_id)
                if root not in distinct_roots:
                    distinct_roots.append(root)

            for i, left in enumerate(members):
                for right in members[i + 1 :]:
                    if uf.find(left.observation_id) == uf.find(right.observation_id):
                        continue
                    conflicts = _attribute_conflict(left, right)
                    if conflicts:
                        conflict_for[left.observation_id].update(conflicts)
                        conflict_for[right.observation_id].update(conflicts)
                        conflict_peers[left.observation_id].add(right.observation_id)
                        conflict_peers[right.observation_id].add(left.observation_id)
                        review_state[left.observation_id] = "conflict"
                        review_state[right.observation_id] = "conflict"
                    else:
                        review_peers[left.observation_id].add(right.observation_id)
                        review_peers[right.observation_id].add(left.observation_id)

            if len(distinct_roots) > 2:
                for member in members:
                    if not exact_basis[member.observation_id]:
                        review_state[member.observation_id] = "ambiguous"
            elif len(distinct_roots) >= 2:
                for member in members:
                    if exact_basis[member.observation_id]:
                        continue
                    if review_state.get(member.observation_id) == "conflict":
                        continue
                    review_state[member.observation_id] = "possible_match"

    components: dict[tuple[str, str], list[ProductObservation]] = {}
    for obs in ordered:
        root = uf.find(obs.observation_id)
        components.setdefault((obs.workspace_id, root), []).append(obs)

    candidate_key_for: dict[str, str] = {}
    candidate_summaries: list[dict[str, Any]] = []

    for (workspace_id, _root), members in sorted(
        components.items(), key=lambda item: (item[0][0], item[0][1])
    ):
        members = sorted(members, key=lambda item: item.observation_id)
        gtin = next((m.gtin for m in members if m.gtin), "")
        asin = next((m.asin for m in members if m.asin), "")
        brand_mpn = next((m.brand_mpn_key for m in members if m.brand_mpn_key), "")
        seller_sku = next((m.seller_sku_key for m in members if m.seller_sku_key), "")
        source_record = next((m.source_record_key for m in members if m.source_record_key), "")
        has_exact = any(exact_basis[m.observation_id] for m in members)
        if gtin and has_exact:
            material, namespace = gtin, "gtin"
        elif asin and has_exact:
            material, namespace = asin, "asin"
        elif brand_mpn and has_exact:
            material, namespace = brand_mpn, "brand_mpn"
        elif seller_sku and has_exact:
            material, namespace = seller_sku, "seller_sku"
        elif source_record and has_exact:
            material, namespace = source_record, "source_record"
        else:
            material, namespace = members[0].observation_id, "provisional"
        key = _stable_key(workspace_id, namespace, material)
        for member in members:
            candidate_key_for[member.observation_id] = key

        title = next((m.title for m in members if m.title), members[0].title)
        brand = next((m.brand for m in members if m.brand), "")
        currency = next((m.currency for m in members if m.currency), "USD")
        product = ProductCandidate(
            product_id=key,
            name=title or key,
            currency=currency or "USD",
            source_signal_ids=tuple(m.observation_id for m in members),
            quality=DataQuality(
                provenance=members[0].evidence_mode,
                attribution="product_identity_resolution",
                completeness="partial",
                source_ref=",".join(sorted({m.source_record_key for m in members})),
                retrieval_mode="offline",
            ),
        )
        candidate_summaries.append(
            {
                "candidate_key": key,
                "workspace_id": workspace_id,
                "product_id": product.product_id,
                "name": product.name,
                "brand": brand,
                "gtin": gtin,
                "asin": asin,
                "currency": product.currency,
                "observation_ids": list(product.source_signal_ids),
                "evidence_modes": sorted({m.evidence_mode for m in members}),
                "source_kinds": sorted({m.source_kind for m in members}),
            }
        )

    links: list[ProductIdentityLink] = []
    for obs in ordered:
        basis = tuple(sorted(exact_basis[obs.observation_id]))
        conflicts = tuple(sorted(conflict_for[obs.observation_id]))
        peers_conflict = tuple(sorted(conflict_peers[obs.observation_id]))
        peers_review = tuple(sorted(review_peers[obs.observation_id]))
        component_size = sum(
            1
            for other in ordered
            if other.workspace_id == obs.workspace_id
            and uf.find(other.observation_id) == uf.find(obs.observation_id)
        )

        if basis and component_size >= 2:
            state = "exact_match"
        elif review_state.get(obs.observation_id) == "conflict" or (
            conflicts and peers_conflict and not basis
        ):
            state = "conflict"
        elif review_state.get(obs.observation_id) == "ambiguous":
            state = "ambiguous"
        elif review_state.get(obs.observation_id) == "possible_match" or peers_review:
            state = "possible_match"
        else:
            state = "unmatched"

        suggested = tuple(sorted(set(peers_review) | set(peers_conflict)))
        links.append(
            ProductIdentityLink(
                observation_id=obs.observation_id,
                workspace_id=obs.workspace_id,
                candidate_key=candidate_key_for[obs.observation_id],
                match_state=state,
                source_kind=obs.source_kind,
                source_system=obs.source_system,
                source_record_id=obs.source_record_id,
                evidence_mode=obs.evidence_mode,
                match_basis=basis,
                conflict_reasons=conflicts,
                suggested_peer_ids=suggested,
                currency=obs.currency,
                observed_at=obs.observed_at,
                gtin=obs.gtin,
                asin=obs.asin,
                brand=obs.brand,
                model=obs.model,
                mpn=obs.mpn,
                title=obs.title,
            )
        )

    modes = tuple(sorted({obs.evidence_mode for obs in ordered}))
    candidates = tuple(
        sorted(candidate_summaries, key=lambda item: (item["workspace_id"], item["candidate_key"]))
    )
    links_out = tuple(sorted(links, key=lambda item: (item.workspace_id, item.observation_id)))

    return ProductIdentityResolutionReport(
        links=links_out,
        candidates=candidates,
        evidence_modes_seen=modes,
        warnings=tuple(warnings),
        pillar_separation={
            "consumer_attention_is_not_supplier_proof": True,
            "consumer_attention_is_not_marketplace_price_proof": True,
            "fixture_manual_never_upgraded_to_live": True,
            "product_identity_is_not_attention_evidence": True,
            "product_identity_is_not_marketplace_price_proof": True,
            "product_identity_is_not_supplier_proof": True,
        },
    )
