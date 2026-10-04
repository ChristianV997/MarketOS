"""A literal ``sk-`` credential prefix must not match inside innocuous hyphenated words.

Many offline guards in MarketOS reject secret-shaped input with a plain substring
test for ``sk-``. That also matches the tail of ordinary ids such as
``desk-clamp-lamp``, ``risk-review-pack`` or ``task-queue-board`` and rejects
legitimate client/product/engagement text. Every guard below must now require
``sk-`` to start a token (not follow a letter or digit) while still rejecting
secret-shaped controls.

Only synthetic values are used: no real credential, provider response or
account identifier appears here, and nothing touches the network.
"""
from __future__ import annotations

import importlib
import json
import tempfile
from pathlib import Path

import pytest

# Innocuous text that merely contains the letters "sk-" inside a word.
INNOCUOUS = [
    "desk-clamp-lamp",
    "risk-review-pack",
    "task-queue-board",
    "disk-usage-report",
    "Standing Desk-Clamp Lamp (sku desk-001)",
]

# Synthetic secret-shaped controls whose "sk-" starts a token.
SK_SECRETS = {
    "bare": "sk-SYNTHETICEXAMPLEKEY000000",
    "embedded": "token is sk-SYNTHETICEXAMPLEKEY000000 ok",
    "key_value": "OPENAI_API_KEY=sk-SYNTHETICEXAMPLEKEY000000",
    "quoted": '"sk-SYNTHETICEXAMPLEKEY000000"',
    "upper": "SK-SYNTHETICEXAMPLEKEY000000",
    "bearer": "Bearer sk-SYNTHETICEXAMPLE0000",
    "project": "sk-proj-SYNTHETICEXAMPLE0000",
    "live": "sk-live-SYNTHETICEXAMPLE0000",
}
# Non-sk markers each guard already handled; they must be untouched by the change.
OTHER_SECRETS = {
    "ghp": "ghp_SYNTHETICEXAMPLEVALUE0000000000",
    "pem": "-----BEGIN PRIVATE KEY-----",
    "bearer_plain": "Bearer SYNTHETICEXAMPLE",
}


def _raises(function):
    def check(value: str) -> bool:
        try:
            function(value)
        except (ValueError, SystemExit):
            return True
        return False

    return check


def _site(module_name: str, attribute: str):
    return getattr(importlib.import_module(module_name), attribute)


def _governor(value: str) -> bool:
    module = importlib.import_module("scripts.run_resource_execution_governor")
    with tempfile.TemporaryDirectory(dir=module.ROOT) as directory:
        path = Path(directory) / "input.json"
        path.write_text(json.dumps({"note": value}), encoding="utf-8")
        try:
            module._load_json(str(path))
        except SystemExit:
            return True
    return False


def _leakage(value: str) -> bool:
    module = importlib.import_module("evaluation.trustos.client_workspace_isolation")
    return any(check.status != "pass" for check in module.check_workspace_leakage({"note": value}))


def _redacted(value: str) -> bool:
    module = importlib.import_module("evaluation.companyos.service_delivery")
    return module._redact_client_unsafe_values(value) != value


def _smoke(value: str) -> bool:
    module = importlib.import_module("backend.deployment.service_delivery_smoke")
    return bool(module.check_projection_workspace_isolation({"note": value}))


def _conformance(value: str) -> bool:
    module = importlib.import_module("scripts.ai.portfolio_conformance_matrix")
    try:
        module._text(value, field="note")
    except module.MatrixInputError:
        return True
    return False


_SECRET_LIKE_MODULES = (
    "evaluation.trustos.security_scanner_adapter",
    "evaluation.commerce.intelligence_adapter_plan",
    "evaluation.commerce.dataforseo_adapter",
    "scripts.run_companyos_approval_ledger",
    "scripts.run_serpapi_commerce_projection",
    "scripts.run_companyos_provider_registry",
    "scripts.run_dataforseo_readonly_adapter",
    "scripts.run_intelligence_adapter_plan",
    "scripts.run_trustos_control_plane",
)

# (site id, rejects(value) -> bool, sk controls it rejects today, other controls it rejects today)
ALL_SK = frozenset(SK_SECRETS)
SITES = [
    ("service_delivery._reject_secret_shaped", lambda v: _raises(lambda x: _site("evaluation.companyos.service_delivery", "_reject_secret_shaped")(x, field_name="f"))(v), ALL_SK, frozenset(OTHER_SECRETS)),
    ("client_workspace_isolation._contains_forbidden_value", lambda v: _site("evaluation.trustos.client_workspace_isolation", "_contains_forbidden_value")(v), ALL_SK, frozenset(OTHER_SECRETS)),
    ("client_workspace_isolation.check_workspace_leakage", _leakage, ALL_SK, frozenset(OTHER_SECRETS)),
    ("run_client_service_intake._reject_secret_shaped_recursive", lambda v: _raises(lambda x: _site("scripts.run_client_service_intake", "_reject_secret_shaped_recursive")(x, field_name="f"))(v), ALL_SK, frozenset(OTHER_SECRETS)),
    ("run_resource_execution_governor._load_json", _governor, ALL_SK, frozenset({"pem"})),
    ("consulting_engagement.schemas._safe_text", lambda v: _raises(lambda x: _site("services.consulting_engagement.schemas", "_safe_text")(x, "note"))(v), ALL_SK, frozenset(OTHER_SECRETS)),
    ("consulting_offers.schemas._safe_text", lambda v: _raises(lambda x: _site("services.consulting_offers.schemas", "_safe_text")(x, "note"))(v), ALL_SK, frozenset(OTHER_SECRETS)),
    ("market_research.report._validate_safe_inputs", lambda v: _raises(lambda x: _site("services.market_research.report", "_validate_safe_inputs")(x))(v), ALL_SK, frozenset(OTHER_SECRETS)),
    *[
        (f"{name}._secret_like", lambda v, name=name: _site(name, "_secret_like")(v), ALL_SK, frozenset(OTHER_SECRETS))
        for name in _SECRET_LIKE_MODULES
    ],
]
# service_delivery's redaction layer only removes what its leak detector flags (sk-, PEM, html).
REDACTION_SITE = ("service_delivery._redact_client_unsafe_values", _redacted, ALL_SK, frozenset({"pem"}))
# The smoke and conformance guards use narrower sk- shapes today; keep exactly those.
SMOKE_SITE = ("service_delivery_smoke.check_projection_workspace_isolation", _smoke, ALL_SK, frozenset(OTHER_SECRETS))
CONFORMANCE_SITE = ("portfolio_conformance_matrix._text", _conformance, ALL_SK - {"project"}, frozenset(OTHER_SECRETS))
# sk-proj-... is not matched by the conformance pattern today; fixing that is a separate detection change.

ALL_SITES = [*SITES, REDACTION_SITE, SMOKE_SITE, CONFORMANCE_SITE]
IDS = [site[0] for site in ALL_SITES]


@pytest.mark.parametrize("site", ALL_SITES, ids=IDS)
@pytest.mark.parametrize("value", INNOCUOUS)
def test_embedded_sk_letters_in_an_ordinary_id_are_accepted(site, value):
    _, rejects, _, _ = site
    assert rejects(value) is False


@pytest.mark.parametrize("site", ALL_SITES, ids=IDS)
def test_sk_shaped_controls_are_still_rejected(site):
    _, rejects, sk_controls, _ = site
    missed = sorted(name for name in sk_controls if not rejects(SK_SECRETS[name]))
    assert missed == []


@pytest.mark.parametrize("site", ALL_SITES, ids=IDS)
def test_the_other_secret_markers_each_guard_handled_are_unchanged(site):
    _, rejects, _, other_controls = site
    missed = sorted(name for name in other_controls if not rejects(OTHER_SECRETS[name]))
    assert missed == []


@pytest.mark.parametrize(
    "value",
    ["desk-live-demo", "risk-proj-alpha", "task-live-board", "desk-organizerstandwithchargers", "risk-reviewpackstandardedition"],
)
def test_narrow_sk_shapes_in_the_smoke_and_conformance_guards_do_not_match_inside_words(value):
    assert _smoke(value) is False
    assert _conformance(value) is False


# Characters that are not ASCII letters or digits, including ones a JSON dump would escape to letters/digits.
NON_ALNUM_PREFIXES = ["(", ":", "=", "_", "-", ".", "/", " ", '"', "\n", "\t", "\u00e9", "\uff53", "\u200b", "\u2028"]


@pytest.mark.parametrize("prefix", NON_ALNUM_PREFIXES, ids=lambda p: repr(p))
def test_sk_prefix_after_a_non_alphanumeric_character_is_rejected_everywhere(prefix):
    value = prefix + "sk-SYNTHETICEXAMPLEKEY000000"
    missed = [name for name, rejects, _, _ in SITES if not rejects(value)]
    assert missed == []


def test_governor_checks_decoded_strings_not_escaped_json_text():
    """json.dumps turns a newline or accented character into \\n / \\u00e9, which must not hide a real token."""
    assert _governor("line one\nsk-SYNTHETICEXAMPLEKEY000000") is True
    assert _governor("caf\u00e9 sk-SYNTHETICEXAMPLEKEY000000") is True
    assert _governor("\u00e9sk-SYNTHETICEXAMPLEKEY000000") is True
