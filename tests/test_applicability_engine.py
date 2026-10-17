"""Synthetic toy rules/devices only; no MDR classification or normative seed."""
from datetime import date
import json

import pytest
from pydantic import ValidationError

from test_regulatory_registry import data, registry, ready, DAY, QUOTE, move
from mdr_rag.applicability_rules import (ApplicabilityRule, Predicate, LegalCondition,
    CandidateAssessment, combine)
from mdr_rag.applicability_service import ApplicabilityStore, ApplicabilityService, SpecialistApproval
from mdr_rag.device_profile import ProfileStore, ProfilePreview, extract_profile
from mdr_rag.errors import BudgetExceeded, MissingModel, ParsingError, TransientModelError, Cancelled
from mdr_rag.providers import FakeLLM
from mdr_rag import applicability_service as aps
from mdr_rag.regulatory_registry import RegistryNotReady, digest


@pytest.fixture
def service(registry, data):
    ready(registry, data)
    store = ApplicabilityStore(data.root / "applicability", data.archive)
    return ApplicabilityService(store, registry, allow_fixture=True)


def make_profile(data, values=None, *, confirm=True, root=None):
    values = {"software": "yes", "measurement": "yes", "sterile": "not sterile"} if values is None else values
    text = "Product: SYNTHETIC TOY A\n" + "\n".join(k.replace("_", " ") + ": " + v for k, v in values.items())
    manifest, key = data.archive.ingest("device", "toy-device-" + digest(text)[:8] + ".txt", text.encode())
    draft = extract_profile(data.archive, [key], "SYNTHETIC TOY A")
    profiles = ProfileStore(root or data.root / ("profiles-" + digest(text)[:8]), data.archive)
    if profiles.path("head.json").exists():
        return profiles.load()[0].preview
    revision, current = profiles.publish(draft, editor="toy-reviewer", reason="SYNTHETIC supplied facts",
        expected_revision=None, operation_id="extract")
    if confirm:
        for attribute in draft.profile.attributes:
            if attribute.value is not None:
                revision, current = profiles.edit(attribute.name, action="confirm", editor="toy-reviewer",
                    reason="SYNTHETIC source checked", expected_revision=current, operation_id="confirm-" + attribute.name)
    return revision.preview


@pytest.fixture
def profile(data):
    return make_profile(data)


@pytest.fixture
def rule(data):
    return ApplicabilityRule(id="toy-rule-v1", edition_id=data.edition.id, requirement_id=data.requirement.id,
        legal_refs={"scope": LegalCondition(requirement_id=data.requirement.id, start=0, end=len(QUOTE), exact_quote=QUOTE)},
        applies_when=Predicate(id="software-check", op="is_true", field="software", legal_ref_ids=["scope"]),
        exclusion_rationale="SYNTHETIC toy scope exclusion; not an MDR interpretation",
        exclusion_ref_ids=["scope"])


def audit(service, operation):
    return dict(reviewer="toy-specialist", reason="SYNTHETIC rule review, no real law",
        expected_revision=service.store.load()[0].revision, operation_id=operation)


def approve(service, rule, **changes):
    service.import_rule(rule, as_of=DAY, **audit(service, "import-" + rule.id))
    approval = SpecialistApproval(reviewer="toy-specialist", reason="SYNTHETIC mapping only",
        as_of=DAY, review_until=date(2026, 12, 31), specialist_reviewed=True)
    if changes:
        approval = SpecialistApproval.model_validate({**approval.model_dump(), **changes})
    service.approve_rule(rule.id, approval, **audit(service, "approve-" + rule.id))


def evaluate(service, data, profile, **kwargs):
    return service.evaluate(data.edition.id, data.requirement.id, DAY, preview=profile, **kwargs)


@pytest.mark.parametrize("op,values,expected", [
    ("all", ["true", "true"], "true"), ("all", ["true", "false"], "false"),
    ("all", ["true", "unknown"], "unknown"), ("all", ["false", "true"], "false"),
    ("all", ["false", "false"], "false"), ("all", ["false", "unknown"], "false"),
    ("all", ["unknown", "true"], "unknown"), ("all", ["unknown", "false"], "false"),
    ("all", ["unknown", "unknown"], "unknown"),
    ("any", ["true", "true"], "true"), ("any", ["true", "false"], "true"),
    ("any", ["true", "unknown"], "true"), ("any", ["false", "true"], "true"),
    ("any", ["false", "false"], "false"), ("any", ["false", "unknown"], "unknown"),
    ("any", ["unknown", "true"], "true"), ("any", ["unknown", "false"], "unknown"),
    ("any", ["unknown", "unknown"], "unknown"),
    ("not", ["true"], "false"), ("not", ["false"], "true"), ("not", ["unknown"], "unknown"),
])
def test_tri_state_tables(op, values, expected):
    assert combine(op, values) == expected


def test_approved_known_rule_is_applicable_without_model(service, data, profile, rule):
    approve(service, rule)
    provider = FakeLLM([])
    result = evaluate(service, data, profile, assist=True, provider=provider)
    decision = result["assessment"]
    assert decision["status"] == "applicable" and decision["candidate_status"] == "applicable"
    assert not provider.calls and result["advice"]["status"] == "not_needed"
    assert decision["evidence_sufficiency"] == "not_assessed"
    assert decision["legal_sources"]["scope"]["file_sha256"] == data.edition.file_sha256
    assert decision["device_attributes"]["software"]["evidence_ids"]


def test_proposed_or_missing_rules_never_route_requirements(service, data, profile, rule):
    missing = evaluate(service, data, profile)
    assert missing["assessment"]["status"] == "unknown"
    service.import_rule(rule, as_of=DAY, **audit(service, "propose"))
    assert evaluate(service, data, profile)["assessment"]["status"] == "unknown"
    assert service.store.load()[0].rules[rule.id].status == "proposed"


def test_explicit_false_is_not_missing(service, data, rule):
    approve(service, rule)
    false = evaluate(service, data, make_profile(data, {"software": "no"}))["assessment"]
    unknown = evaluate(service, data, make_profile(data, {}))["assessment"]
    assert false["status"] == "not_applicable" and false["exclusion_supported"]
    assert false["exclusion_rationale"] and false["legal_sources"]
    assert unknown["status"] == "unknown" and unknown["candidate_status"] is None
    assert "software" in unknown["questions"]


@pytest.mark.parametrize("field,value", [("sterile", "not sterile"), ("invasive", "non-invasive")])
def test_high_impact_false_is_candidate_exclusion_for_specialist(service, data, rule, field, value):
    updated = rule.model_copy(update={"applies_when": Predicate(id="high-impact", op="is_true", field=field, legal_ref_ids=["scope"])})
    approve(service, updated)
    false = evaluate(service, data, make_profile(data, {field: value}))["assessment"]
    unknown = evaluate(service, data, make_profile(data, {}))["assessment"]
    assert false["candidate_status"] == "not_applicable" and false["status"] == "requires_human_review"
    assert unknown["status"] == "unknown"


def test_no_exclusion_without_reviewed_rationale(service, data, rule):
    rule = rule.model_copy(update={"exclusion_rationale": None, "exclusion_ref_ids": []})
    approve(service, rule)
    decision = evaluate(service, data, make_profile(data, {"software": "no"}))["assessment"]
    assert decision["status"] == "requires_human_review" and not decision["exclusion_supported"]
    with pytest.raises(ValueError, match="source-backed exclusion"):
        service.override(data.edition.id, data.requirement.id, DAY, "not_applicable",
            preview=make_profile(data, {"software": "no"}), specialist_reviewed=True,
            decision_key=evaluate(service, data, make_profile(data, {"software": "no"}))["decision_key"],
            **audit(service, "bad-exclusion"))


def test_unconfirmed_source_is_unknown_not_false(service, data, rule):
    approve(service, rule)
    preview = make_profile(data, {"software": "no"}, confirm=False)
    result = evaluate(service, data, preview)["assessment"]
    assert result["status"] == "unknown" and "software" in result["questions"]


def test_exception_takes_precedence_over_true_base(service, data, profile, rule):
    exception = Predicate(id="except-measurement", op="is_true", field="measurement", legal_ref_ids=["scope"])
    approve(service, rule.model_copy(update={"except_when": [exception]}))
    result = evaluate(service, data, profile)["assessment"]
    assert result["status"] == "not_applicable" and "verified_exception_matches" in result["reason_codes"]


def test_unknown_exception_preserves_conditional(service, data, rule):
    exception = Predicate(id="except-measurement", op="is_true", field="measurement", legal_ref_ids=["scope"])
    approve(service, rule.model_copy(update={"except_when": [exception]}))
    result = evaluate(service, data, make_profile(data, {"software": "yes"}))["assessment"]
    assert result["status"] == "conditional" and result["candidate_status"] is None
    assert "measurement" in result["questions"]


def test_conflicting_population_never_becomes_exclusion(service, data, rule):
    first, one = data.archive.ingest("device", "population-one.txt", b"Product: SYNTHETIC TOY A\nTarget population: adults")
    second, two = data.archive.ingest("device", "population-two.txt", b"Product: SYNTHETIC TOY A\nTarget population: children")
    preview = extract_profile(data.archive, [one, two], "SYNTHETIC TOY A")
    condition = Predicate(id="population", op="equals", field="target_population", values=["adults"], legal_ref_ids=["scope"])
    approve(service, rule.model_copy(update={"applies_when": condition}))
    result = evaluate(service, data, preview)["assessment"]
    assert result["status"] == "requires_human_review" and result["candidate_status"] is None
    assert "conflicting_profile_attribute" in result["reason_codes"]


def test_multiple_purposes_are_not_silently_excluded(service, data, rule):
    condition = Predicate(id="purpose", op="equals", field="intended_purpose", values=["toy monitoring"], legal_ref_ids=["scope"])
    approve(service, rule.model_copy(update={"applies_when": condition}))
    result = evaluate(service, data, make_profile(data, {"intended_purpose": "toy monitoring; toy measurement"}))["assessment"]
    assert result["status"] == "requires_human_review"
    assert result["candidate_status"] is None


@pytest.mark.parametrize("value", ["may include software", "shall include software", "could include software", "not specified"])
def test_modal_normative_or_unknown_wording_does_not_imply_false(service, data, rule, value):
    approve(service, rule)
    result = evaluate(service, data, make_profile(data, {"software": value}))["assessment"]
    assert result["status"] == "unknown" and result["candidate_status"] is None


def test_classification_output_is_always_candidate_for_review(service, data, profile, rule):
    approve(service, rule.model_copy(update={"candidate_category": "SYNTHETIC TOY CATEGORY — NOT A LEGAL CLASS"}))
    decision = evaluate(service, data, profile)["assessment"]
    assert decision["status"] == "requires_human_review"
    assert decision["classification_status"] == "requires_review" and decision["review_required"]
    assert "SYNTHETIC" in decision["classification_candidate"]


def test_manual_unsourced_profile_cannot_support_exclusion(service, data, profile, rule):
    approve(service, rule)
    raw = profile.model_dump()
    for item in raw["profile"]["attributes"]:
        if item["name"] == "software":
            item.update(value="no", origin="manual", status="user_confirmed", review_state="overridden",
                        evidence_ids=[], source_span_ids=[])
    decision = evaluate(service, data, ProfilePreview.model_validate(raw))["assessment"]
    assert decision["status"] == "unknown"


def test_repeated_evaluation_and_irrelevant_name_edit_reuse_cache(service, data, profile, rule):
    approve(service, rule.model_copy(update={"candidate_category": "SYNTHETIC TOY CATEGORY"}))
    first = evaluate(service, data, profile)
    assert first["assessment"]["classification_candidate"] == "SYNTHETIC TOY CATEGORY"
    assert not first["cached"]
    assert evaluate(service, data, profile)["cached"]
    raw = profile.model_dump()
    for item in raw["profile"]["attributes"]:
        if item["name"] == "device_name":
            item.update(value="SYNTHETIC cosmetic name edit", origin="manual", status="user_confirmed", review_state="overridden")
    changed = evaluate(service, data, ProfilePreview.model_validate(raw))
    assert changed["cached"] and changed["decision_key"] == first["decision_key"]
    assert changed["assessment"] == first["assessment"]


def test_relevant_attribute_change_invalidates_cached_result(service, data, profile, rule):
    approve(service, rule)
    before = evaluate(service, data, profile)
    after = evaluate(service, data, make_profile(data, {"software": "no"}))
    assert after["decision_key"] != before["decision_key"] and not after["cached"]
    assert after["assessment"]["status"] == "not_applicable"


def test_retired_rule_does_not_reuse_prior_result(service, data, profile, rule):
    approve(service, rule)
    first = evaluate(service, data, profile)
    service.retire_rule(rule.id, **audit(service, "retire"))
    second = evaluate(service, data, profile)
    assert first["decision_key"] != second["decision_key"]
    assert second["assessment"]["status"] == "unknown"


def test_overlapping_approved_rules_require_explicit_retirement(service, data, rule):
    approve(service, rule)
    with pytest.raises(ValueError, match="Overlapping"):
        approve(service, rule.model_copy(update={"id": "toy-rule-v2"}))


def test_different_edition_and_forged_legal_quote_cannot_be_approved(service, data, rule):
    wrong = rule.model_copy(update={"edition_id": "different-edition"})
    with pytest.raises(RegistryNotReady):
        service.import_rule(wrong, as_of=DAY, **audit(service, "wrong-edition"))
    ref = LegalCondition(requirement_id=data.requirement.id, start=0, end=4, exact_quote="fake")
    with pytest.raises(ValueError, match="condition quote"):
        service.import_rule(rule.model_copy(update={"legal_refs": {"scope": ref}}), as_of=DAY, **audit(service, "forged"))


def test_retired_legal_requirement_blocks_cached_decision(service, data, profile, registry, rule):
    approve(service, rule)
    evaluate(service, data, profile)
    move(registry, "requirements", data.requirement.id, "retired")
    with pytest.raises(RegistryNotReady):
        evaluate(service, data, profile)


def test_fixture_authority_not_enabled_by_production_service(service, data, profile):
    production = ApplicabilityService(service.store, service.registry)
    with pytest.raises(RegistryNotReady):
        evaluate(production, data, profile)


def test_no_approved_law_blocks_before_advice(registry, data):
    store = ApplicabilityStore(data.root / "applicability", data.archive)
    service = ApplicabilityService(store, registry, allow_fixture=True)
    provider = FakeLLM([])
    with pytest.raises(RegistryNotReady):
        service.evaluate(data.edition.id, data.requirement.id, DAY, assist=True, provider=provider)
    assert provider.calls == 0


def test_no_profile_generates_unknown_without_sources(service, data, rule):
    approve(service, rule)
    result = service.evaluate(data.edition.id, data.requirement.id, DAY)
    assert result["profile_revision_sha256"] is None
    assert result["assessment"]["status"] == "unknown"


def test_not_applicable_override_needs_reason_and_review(service, data, rule):
    high = rule.model_copy(update={"applies_when": Predicate(id="sterility", op="is_true", field="sterile", legal_ref_ids=["scope"])})
    approve(service, high)
    profile = make_profile(data, {"sterile": "not sterile"})
    result = evaluate(service, data, profile)
    kwargs = dict(preview=profile, decision_key=result["decision_key"])
    with pytest.raises(ValueError, match="specialist"):
        service.override(data.edition.id, data.requirement.id, DAY, "not_applicable", **kwargs, **audit(service, "missing-specialist"))
    args = audit(service, "confirm-exclusion")
    args["reason"] = " "
    with pytest.raises(ValueError, match="reviewer and reason"):
        service.override(data.edition.id, data.requirement.id, DAY, "not_applicable",
            **kwargs, specialist_reviewed=True, **args)
    old, old_key = service.store.load()
    new, _ = service.override(data.edition.id, data.requirement.id, DAY, "not_applicable",
        **kwargs, specialist_reviewed=True, **audit(service, "confirmed-exclusion"))
    assert new.revision == old.revision + 1
    assert service.store.load(old_key)[0] == old
    evaluated = evaluate(service, data, profile)
    assert evaluated["assessment"]["status"] == "not_applicable"
    assert evaluated["assessment"]["human_override"]["reviewer"] == "toy-specialist"


def test_override_cannot_invent_exclusion_from_unknown(service, data, rule):
    approve(service, rule)
    profile = make_profile(data, {})
    result = evaluate(service, data, profile)
    with pytest.raises(ValueError, match="cannot contradict"):
        service.override(data.edition.id, data.requirement.id, DAY, "not_applicable",
            preview=profile, decision_key=result["decision_key"], specialist_reviewed=True, **audit(service, "invent"))


def test_override_does_not_survive_changed_relevant_fact(service, data, rule):
    approve(service, rule)
    first_profile = make_profile(data, {"software": "no"})
    first = evaluate(service, data, first_profile)
    service.override(data.edition.id, data.requirement.id, DAY, "not_applicable",
        preview=first_profile, decision_key=first["decision_key"], specialist_reviewed=True, **audit(service, "exclude"))
    changed = evaluate(service, data, make_profile(data, {"software": "yes"}))
    assert changed["assessment"]["status"] == "applicable" and changed["assessment"]["human_override"] is None


def test_stale_override_key_rejected(service, data, profile, rule):
    approve(service, rule)
    before = evaluate(service, data, profile)
    with pytest.raises(ValueError, match="inputs changed"):
        service.override(data.edition.id, data.requirement.id, DAY, "unknown",
            preview=make_profile(data, {"software": "no"}), decision_key=before["decision_key"],
            specialist_reviewed=True, **audit(service, "stale"))


def test_rule_operations_are_idempotent_and_immutable(service, data, rule):
    args = audit(service, "import")
    first = service.import_rule(rule, as_of=DAY, **args)
    assert service.import_rule(rule, as_of=DAY, **args) == first
    changed = rule.model_copy(update={"candidate_category": "SYNTHETIC DIFFERENT"})
    with pytest.raises(ValueError, match="reused"):
        service.import_rule(changed, as_of=DAY, **args)
    with pytest.raises(ValueError, match="Immutable"):
        service.import_rule(changed, as_of=DAY, **audit(service, "changed"))


def test_stale_mutation_and_interrupted_head_leave_old_book(service, data, rule, monkeypatch):
    args = audit(service, "first")
    service.import_rule(rule, as_of=DAY, **args)
    with pytest.raises(ValueError, match="revision changed"):
        service.import_rule(rule, as_of=DAY, **{**args, "operation_id": "stale"})
    original = service.store.load()
    real = aps.atomic_bytes
    def fail(path, payload, **kwargs):
        if path.name == "head.json":
            raise OSError("SYNTHETIC private storage failure")
        return real(path, payload, **kwargs)
    monkeypatch.setattr(aps, "atomic_bytes", fail)
    with pytest.raises(OSError):
        approve(service, rule)
    assert service.store.load() == original


def test_rulebook_and_cache_tampering_fail_closed(service, data, profile, rule):
    approve(service, rule)
    result = evaluate(service, data, profile)
    cache = service.store.path("cache", result["decision_key"] + ".json")
    content = json.loads(cache.read_text())
    content["decision_sha256"] = "0" * 64
    cache.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match="cache integrity"):
        evaluate(service, data, profile)
    book, key = service.store.load()
    service.store.path("revisions", key + ".json").write_bytes(b"SYNTHETIC tampered")
    with pytest.raises(ValueError, match="revision hash"):
        service.store.load()


def test_source_original_tampering_blocks_cached_evaluation(service, data, profile, rule):
    approve(service, rule)
    evaluate(service, data, profile)
    ref = next(iter(profile.evidence.values()))
    manifest = data.archive.load(ref.manifest_sha256)
    data.archive.original(manifest).write_bytes(b"SYNTHETIC tampered source")
    with pytest.raises(ValueError, match="hash mismatch"):
        evaluate(service, data, profile)


@pytest.mark.parametrize("error", [MissingModel, BudgetExceeded, TransientModelError, ConnectionError, TimeoutError, ParsingError])
def test_advice_failure_preserves_unknown(service, data, rule, error):
    approve(service, rule)
    class Offline:
        calls = 0
        def generate(self, *args):
            self.calls += 1
            raise error()
    provider = Offline()
    result = evaluate(service, data, make_profile(data, {}), assist=True, provider=provider)
    assert result["assessment"]["status"] == "unknown"
    assert provider.calls == 1 and result["advice"]["status"] == "advice_unavailable_or_invalid"


def test_advice_cannot_change_predicates_or_invent_refs(service, data, rule):
    approve(service, rule)
    profile = make_profile(data, {})
    provider = FakeLLM([{"reason_code": "clarify_profile", "question_fields": ["software"], "legal_ref_ids": ["scope"]}])
    before = evaluate(service, data, profile)
    advised = evaluate(service, data, profile, assist=True, provider=provider)
    assert advised["assessment"] == before["assessment"]
    assert advised["advice"]["status"] == "advisory_only"
    malicious = FakeLLM([{"status": "not_applicable", "reason_code": "review_scope", "question_fields": [], "legal_ref_ids": []}])
    result = evaluate(service, data, profile, assist=True, provider=malicious)
    assert result["assessment"] == before["assessment"] and malicious.calls == 1
    forged = FakeLLM([{"reason_code": "review_scope", "question_fields": ["invented"], "legal_ref_ids": ["forged"]}])
    assert evaluate(service, data, profile, assist=True, provider=forged)["advice"]["status"] == "advice_unavailable_or_invalid"


def test_advice_cancellation_propagates(service, data, rule):
    approve(service, rule)
    class Cancel:
        def generate(self, *args): raise Cancelled()
    with pytest.raises(Cancelled):
        evaluate(service, data, make_profile(data, {}), assist=True, provider=Cancel())


@pytest.mark.parametrize("node", [
    {"id": "bad", "op": "python_eval", "field": "software", "legal_ref_ids": ["scope"]},
    {"id": "bad", "op": "equals", "field": "../../secret", "values": ["yes"], "legal_ref_ids": ["scope"]},
    {"id": "bad", "op": "not", "children": []},
    {"id": "bad", "op": "is_true", "field": "software", "legal_ref_ids": []},
])
def test_invalid_dsl_is_not_executable(node):
    with pytest.raises(ValidationError):
        Predicate.model_validate(node)


def test_duplicate_predicate_ids_and_missing_legal_refs_rejected(rule):
    duplicate = Predicate(id="group", op="all", children=[rule.applies_when, rule.applies_when])
    with pytest.raises(ValidationError, match="duplicate"):
        ApplicabilityRule.model_validate({**rule.model_dump(), "applies_when": duplicate})
    with pytest.raises(ValidationError, match="unknown legal"):
        ApplicabilityRule.model_validate({**rule.model_dump(), "legal_refs": {"other": next(iter(rule.legal_refs.values()))}})


def test_no_source_exclusion_cannot_be_serialized_as_not_applicable():
    with pytest.raises(ValidationError, match="source-backed"):
        CandidateAssessment(status="not_applicable", requirement_id="toy.p1", edition_id="toy", reason_codes=[])


def test_cli_schema_show_and_no_law_gate(data, monkeypatch, capsys):
    import main
    from mdr_rag import core
    monkeypatch.setattr(core, "STATE", data.root / "empty-state")
    monkeypatch.setattr("sys.argv", ["main.py", "applicability-schema"])
    assert main.main() == 0 and "rule" in json.loads(capsys.readouterr().out)
    monkeypatch.setattr("sys.argv", ["main.py", "applicability-show"])
    assert main.main() == 0 and json.loads(capsys.readouterr().out)["revision"] == 0
    monkeypatch.setattr("sys.argv", ["main.py", "applicability-evaluate", "--edition", "missing",
        "--requirement", "missing.p1", "--as-of", DAY.isoformat()])
    assert main.main() == 1
    assert "legal_registry_not_ready" in capsys.readouterr().err


def test_expired_rule_approval_returns_unknown(service, data, profile, rule):
    approve(service, rule, review_until=DAY)
    result = service.evaluate(data.edition.id, data.requirement.id, date(2026, 10, 18), preview=profile)
    assert result["assessment"]["status"] == "unknown"
    assert result["assessment"]["legal_sources"]["requirement"]["source_span_id"] == data.requirement.source_span_id


def test_specialist_approval_and_explicit_scope_are_required(service, data, rule):
    service.import_rule(rule, as_of=DAY, **audit(service, "import"))
    with pytest.raises(ValidationError):
        SpecialistApproval(reviewer="r", reason="toy", as_of=DAY, review_until=DAY, specialist_reviewed=False)
    broken = rule.model_copy(update={"legal_refs": {"scope": LegalCondition(requirement_id="inactive.p1",
        start=0, end=len(QUOTE), exact_quote=QUOTE)}})
    with pytest.raises(ValueError, match="target requirement"):
        service.import_rule(broken, as_of=DAY, **audit(service, "bad-legal-ref"))


@pytest.mark.parametrize("value", ["0", "off", "none", "software unknown"])
def test_unrecognized_boolean_is_not_coerced_false(service, data, rule, value):
    approve(service, rule)
    result = evaluate(service, data, make_profile(data, {"software": value}))["assessment"]
    assert result["status"] == "unknown" and result["candidate_status"] is None


def test_literal_membership_and_nested_predicates(service, data, rule):
    condition = Predicate(id="all", op="all", children=[
        Predicate(id="software", op="is_true", field="software", legal_ref_ids=["scope"]),
        Predicate(id="measurement", op="one_of", field="measurement", values=["yes", "YES"], legal_ref_ids=["scope"])])
    approve(service, rule.model_copy(update={"applies_when": condition}))
    result = evaluate(service, data, make_profile(data, {"software": "TRUE", "measurement": "yes"}))["assessment"]
    assert result["status"] == "applicable"
    assert [p["truth"] for p in result["predicates"]] == ["true", "true", "true"]


def test_deep_predicate_trees_are_bounded(rule):
    node = rule.applies_when
    for i in range(9):
        node = Predicate(id="not-" + str(i), op="not", children=[node])
    with pytest.raises(ValidationError, match="overlarge"):
        ApplicabilityRule.model_validate({**rule.model_dump(), "applies_when": node})


def test_cache_keys_are_edition_scoped(service, data, profile, rule, registry):
    from mdr_rag.regulatory_registry import RegistryBundle
    approve(service, rule)
    first = evaluate(service, data, profile)
    second = data.edition.model_copy(update={"id": "toy-edition-two", "supersedes": [data.edition.id]})
    provision = data.requirement.model_copy(update={"id": second.id + ".p1", "edition_id": second.id})
    registry.import_bundle(RegistryBundle(project_id=data.archive.project_id, fixture_only=True,
        editions=[second], requirements=[provision]), expected_revision=registry.revision,
        operation_id="second-edition", reviewer="r", reason="SYNTHETIC separate edition")
    move(registry, "editions", data.edition.id, "retired")
    for target in ("source_verified", "specialist_reviewed", "active"):
        move(registry, "editions", second.id, target)
    for target in ("source_verified", "specialist_reviewed", "active"):
        move(registry, "requirements", provision.id, target)
    result = service.evaluate(second.id, provision.id, DAY, preview=profile)
    assert result["assessment"]["status"] == "unknown" and result["decision_key"] != first["decision_key"]
    second_rule = ApplicabilityRule.model_validate({**rule.model_dump(), "id": "toy-rule-edition-two",
        "edition_id": second.id, "requirement_id": provision.id,
        "legal_refs": {"scope": {**rule.legal_refs["scope"].model_dump(), "requirement_id": provision.id}}})
    approve(service, second_rule)
    assert service.evaluate(second.id, provision.id, DAY, preview=profile)["assessment"]["status"] == "applicable"


def test_irrelevant_new_rule_does_not_change_this_decision(service, data, profile, rule, registry):
    from mdr_rag.regulatory_registry import RegistryBundle
    approve(service, rule)
    before = evaluate(service, data, profile)
    second = data.provision("p2", "SYNTHETIC TOY ONLY: record a different imaginary observation.")
    registry.import_bundle(RegistryBundle(project_id=data.archive.project_id, fixture_only=True, requirements=[second]),
        expected_revision=registry.revision, operation_id="second-provision", reviewer="r", reason="toy")
    for target in ("source_verified", "specialist_reviewed", "active"):
        move(registry, "requirements", second.id, target)
    ref = LegalCondition(requirement_id=second.id, start=0, end=len(second.exact_quote), exact_quote=second.exact_quote)
    other = rule.model_copy(update={"id": "other-rule", "requirement_id": second.id, "legal_refs": {"scope": ref}})
    approve(service, other)
    after = evaluate(service, data, profile)
    assert after["cached"] and after["decision_key"] == before["decision_key"]


def test_immutable_sources_remain_unchanged_after_override(service, data, profile, rule):
    approve(service, rule)
    snapshots = {ref.manifest_sha256: data.archive.original(data.archive.load(ref.manifest_sha256)).read_bytes()
                 for ref in profile.evidence.values()}
    result = evaluate(service, data, profile)
    service.override(data.edition.id, data.requirement.id, DAY, "conditional",
        preview=profile, decision_key=result["decision_key"], specialist_reviewed=True, **audit(service, "defer"))
    assert evaluate(service, data, profile)["assessment"]["status"] == "conditional"
    assert all(data.archive.original(data.archive.load(key)).read_bytes() == value for key, value in snapshots.items())


def test_advice_prompt_cap_prevents_model_call(service, data, rule, monkeypatch):
    from mdr_rag.settings import Settings
    approve(service, rule)
    monkeypatch.setattr("mdr_rag.settings.load_settings", lambda: Settings(max_prompt_chars_per_call=1))
    provider = FakeLLM([])
    result = evaluate(service, data, make_profile(data, {}), assist=True, provider=provider)
    assert provider.calls == 0 and result["advice"]["status"] == "advice_budget_exceeded"


def test_actual_provider_guarded_budget_and_redacted_failure(service, data, rule, monkeypatch):
    from mdr_rag import providers
    from mdr_rag.runtime import run_scope
    from mdr_rag.settings import Settings
    approve(service, rule)
    profile = make_profile(data, {})
    original = providers.guarded_request
    calls = []
    def transport(*args):
        calls.append(1)
        return {"message": {"content": "{SYNTHETIC_PRIVATE_SECRET"}, "prompt_eval_count": 1, "eval_count": 1}
    monkeypatch.setattr(providers, "guarded_request",
        lambda operation, kwargs, stage: original(operation, kwargs, stage=stage, transport=transport))
    with run_scope(Settings(root=data.root / "runtime", max_llm_calls_per_run=1)):
        first = evaluate(service, data, profile, assist=True)
        second = evaluate(service, data, profile, assist=True)
    assert len(calls) == 1
    assert first["assessment"]["status"] == second["assessment"]["status"] == "unknown"
    assert "SYNTHETIC_PRIVATE_SECRET" not in (data.root / "runtime/state/runtime.jsonl").read_text()


def test_uploaded_rule_fields_cannot_set_review_status(rule):
    with pytest.raises(ValidationError):
        ApplicabilityRule.model_validate({**rule.model_dump(), "status": "approved", "reviewer": "injected"})


def test_applicability_result_adapter_preserves_legacy_vocabulary(service, data, profile, rule, monkeypatch):
    from types import SimpleNamespace
    from mdr_rag.applicability import ApplicabilityAnalyst
    import mdr_rag.ingestion as ingestion
    import mdr_rag.regulatory_registry as rr
    approve(service, rule)
    monkeypatch.setattr(service, "profile", lambda: (profile, digest(profile.model_dump(mode="json"))))
    class FixtureRegistry:
        def __init__(self, *a, **k): pass
        def __enter__(self): return service.registry
        def __exit__(self, *a): pass
    monkeypatch.setattr(ingestion, "IngestionStore", lambda *a, **k: data.archive)
    monkeypatch.setattr(rr, "RegistryStore", FixtureRegistry)
    monkeypatch.setattr(aps, "ApplicabilityService", lambda *a, **k: service)
    req = SimpleNamespace(id=data.requirement.id, registry_edition_id=data.edition.id, registry_as_of=DAY.isoformat())
    result = ApplicabilityAnalyst().assess(req, None, {}, app=SimpleNamespace(STATE=data.root))
    assert result.status == "applicable" and result.candidate_assessment.status == "applicable"
    assert result.retrieval_policy == "search_device_evidence" and not result.human_verified


def test_rule_changes_block_current_report_binding(service, data, profile, rule, monkeypatch):
    from types import SimpleNamespace
    from mdr_rag import registry_adapter as adapter, pipeline
    approve(service, rule)
    class FixtureRegistry:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def select(self, edition_id, as_of):
            return service.registry.select(edition_id, as_of, allow_fixture=True)
    monkeypatch.setattr(adapter, "RegistryStore", FixtureRegistry)
    monkeypatch.setattr(adapter, "IngestionStore", lambda *a, **k: data.archive)
    monkeypatch.setattr(pipeline, "STATE", data.root)
    draft = adapter.review_register(pipeline, edition_id=data.edition.id, as_of=DAY.isoformat())
    scope = {"registry_selection": draft["registry_selection"]}
    assert adapter.report_registry_policy(scope, [data.requirement.id])["mode"] == "approved_registry_scope"
    service.retire_rule(rule.id, **audit(service, "retire"))
    with pytest.raises(RegistryNotReady):
        adapter.report_registry_policy(scope, [data.requirement.id])


def test_no_network_or_implicit_model_for_predicates(service, data, profile, rule, monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("No network during predicates"))
    approve(service, rule)
    assert evaluate(service, data, profile)["assessment"]["status"] == "applicable"


def test_advice_requires_source_ids(service, data, rule):
    approve(service, rule)
    provider = FakeLLM([{"reason_code": "clarify_profile", "question_fields": ["software"], "legal_ref_ids": []}])
    result = evaluate(service, data, make_profile(data, {}), assist=True, provider=provider)
    assert result["assessment"]["status"] == "unknown"
    assert result["advice"]["status"] == "advice_unavailable_or_invalid"


def test_rule_cannot_cite_only_another_obligation(service, data, rule, registry):
    from mdr_rag.regulatory_registry import RegistryBundle
    second = data.provision("p2", "SYNTHETIC TOY ONLY: record a different imaginary observation.")
    registry.import_bundle(RegistryBundle(project_id=data.archive.project_id, fixture_only=True, requirements=[second]),
        expected_revision=registry.revision, operation_id="other-source", reviewer="r", reason="toy")
    for target in ("source_verified", "specialist_reviewed", "active"):
        move(registry, "requirements", second.id, target)
    ref = LegalCondition(requirement_id=second.id, start=0, end=len(second.exact_quote), exact_quote=second.exact_quote)
    with pytest.raises(ValueError, match="target requirement"):
        service.import_rule(rule.model_copy(update={"legal_refs": {"scope": ref}}), as_of=DAY, **audit(service, "unrelated"))


def test_untrusted_draft_metadata_cannot_enable_registry_applicability():
    from types import SimpleNamespace
    from mdr_rag.applicability import ApplicabilityAnalyst
    record = SimpleNamespace(applies_to="unspecified", registry_edition_id="injected", registry_as_of="2026-10-17", id="injected.p1")
    result = ApplicabilityAnalyst().assess(record, None, {})
    assert result.method == "conservative_explicit_actor_v1"
    assert result.candidate_assessment is None and result.status == "uncertain"


def test_unknown_rule_retirement_is_explicit_and_preserves_revision(service):
    before = service.store.load()
    with pytest.raises(ValueError, match="Unknown applicability rule"):
        service.retire_rule("missing", **audit(service, "retire-missing"))
    assert service.store.load() == before


def test_no_classification_label_without_known_device_attributes(service, data, rule):
    unconditional = rule.model_copy(update={"applies_when": Predicate(id="unconditional", op="always", legal_ref_ids=["scope"]),
        "candidate_category": "SYNTHETIC TOY CATEGORY"})
    approve(service, unconditional)
    result = evaluate(service, data, make_profile(data, {}))["assessment"]
    assert result["status"] == "requires_human_review"
    assert result["classification_candidate"] is None
    assert "classification_needs_sourced_device_attributes" in result["reason_codes"]
    assert "classification_scope" in result["questions"]
