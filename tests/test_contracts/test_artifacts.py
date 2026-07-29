"""Tests for typed artifact contracts."""
import time
import pytest

from backend.contracts import (
    BaseArtifact, SimulationArtifact, ResearchArtifact,
    WorkflowArtifact, SemanticAsset, CampaignAsset, ReplayArtifact,
    ArtifactRegistry, get_registry,
)


# ── BaseArtifact ──────────────────────────────────────────────────────────────

def test_base_artifact_gets_id():
    a = BaseArtifact(artifact_type="base", workspace="test")
    assert a.artifact_id
    assert len(a.artifact_id) > 8


def test_base_artifact_replay_hash_is_16_hex():
    a = BaseArtifact()
    assert len(a.replay_hash) == 16
    assert all(c in "0123456789abcdef" for c in a.replay_hash)


def test_base_artifact_lineage_chain():
    a = BaseArtifact(parent_ids=["p1", "p2"])
    chain = a.lineage_chain()
    assert "p1" in chain
    assert "p2" in chain
    assert chain[-1] == a.artifact_id


def test_base_artifact_is_valid():
    a = BaseArtifact(artifact_type="base")
    assert a.is_valid()


def test_base_artifact_to_dict():
    a = BaseArtifact(artifact_type="base", workspace="prod")
    d = a.to_dict()
    assert d["artifact_type"] == "base"
    assert d["workspace"] == "prod"
    assert "artifact_id" in d
    assert "parent_ids" in d


# ── SimulationArtifact ────────────────────────────────────────────────────────

def test_simulation_artifact_type():
    a = SimulationArtifact(simulation_id="sim-001", regime="EXPLORE")
    assert a.artifact_type == "simulation"
    assert a.simulation_id == "sim-001"


def test_simulation_artifact_to_dict():
    a = SimulationArtifact(scores=[{"product": "x", "score": 1.5}])
    d = a.to_dict()
    assert "scores" in d
    assert d["source_repo"] == "ScienceR-Dsim"


# ── CampaignAsset ─────────────────────────────────────────────────────────────

def test_campaign_asset_fields():
    a = CampaignAsset(
        campaign_id="cid-001",
        product="wireless earbuds",
        hook="This changed everything",
        angle="problem-solution",
        estimated_roas=2.5,
        budget=100.0,
        dry_run=True,
    )
    assert a.artifact_type == "campaign"
    assert a.campaign_id == "cid-001"
    assert a.dry_run is True


def test_campaign_asset_with_outcome():
    a = CampaignAsset(campaign_id="cid-002", estimated_roas=2.0)
    b = a.with_outcome(roas=3.7)
    assert b.actual_roas == 3.7
    assert b.outcome_recorded is True
    # original unchanged
    assert a.outcome_recorded is False


# ── ReplayArtifact ────────────────────────────────────────────────────────────

def test_replay_artifact_type():
    a = ReplayArtifact(phase="SCALE", capital=5000.0)
    assert a.artifact_type == "replay"
    assert a.capital == 5000.0


# ── SemanticAsset ─────────────────────────────────────────────────────────────

def test_semantic_asset_fields():
    a = SemanticAsset(label="morning_hook_cluster", domain="hook", score=0.87)
    assert a.artifact_type == "semantic"
    assert a.domain == "hook"
    assert a.score == 0.87


# ── ArtifactRegistry ──────────────────────────────────────────────────────────

def test_registry_register_and_get():
    reg = ArtifactRegistry()
    a   = CampaignAsset(campaign_id="reg-001")
    reg.register(a)
    retrieved = reg.get(a.artifact_id)
    assert retrieved is not None
    assert retrieved.artifact_id == a.artifact_id


def test_registry_by_type():
    reg = ArtifactRegistry()
    reg.register(CampaignAsset(campaign_id="c1"))
    reg.register(CampaignAsset(campaign_id="c2"))
    reg.register(WorkflowArtifact(workflow_name="w1"))
    campaigns = reg.by_type("campaign")
    workflows = reg.by_type("workflow")
    assert len(campaigns) == 2
    assert len(workflows) == 1


def test_registry_children_of():
    reg    = ArtifactRegistry()
    parent = SimulationArtifact(simulation_id="parent-sim")
    child  = CampaignAsset(
        campaign_id="child-cid",
        parent_ids=[parent.artifact_id],
    )
    reg.register(parent)
    reg.register(child)
    children = reg.children_of(parent.artifact_id)
    assert len(children) == 1
    assert children[0].artifact_id == child.artifact_id


def test_registry_count():
    reg = ArtifactRegistry()
    assert reg.count() == 0
    reg.register(BaseArtifact())
    assert reg.count() == 1
    assert reg.count("base") == 1
    assert reg.count("campaign") == 0


def test_registry_replaces_updated_artifact_without_duplicate_indexes():
    reg = ArtifactRegistry()
    original = CampaignAsset(
        artifact_id="campaign-update", campaign_id="campaign-update", parent_ids=["parent-a"]
    )
    reg.register(original)
    reg.register(original.with_outcome(2.1))

    assert reg.count("campaign") == 1
    assert len(reg.by_type("campaign")) == 1
    assert len(reg.children_of("parent-a")) == 1
    assert reg.get("campaign-update").outcome_recorded is True


def test_registry_deserialize():
    reg = ArtifactRegistry()
    a   = CampaignAsset(campaign_id="deser-001")
    d   = a.to_dict()
    b   = reg.deserialize(d)
    assert isinstance(b, CampaignAsset)
    assert b.campaign_id == "deser-001"


def test_registry_hydrates_latest_campaign_revision_without_reemitting():
    source = CampaignAsset(
        artifact_id="restore-campaign", campaign_id="restore-campaign", product="Restored"
    )
    updated = source.with_outcome(2.7)
    reg = ArtifactRegistry()
    restored = reg.hydrate([
        {"type": "artifact.campaign.registered", "payload": source.to_dict()},
        {"type": "artifact.campaign.registered", "payload": updated.to_dict()},
    ])

    assert restored == 2
    assert reg.count("campaign") == 1
    campaign = reg.get("restore-campaign")
    assert campaign.product == "Restored"
    assert campaign.outcome_recorded is True
    assert campaign.actual_roas == 2.7
