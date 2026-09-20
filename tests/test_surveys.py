from copy import deepcopy

import numpy as np
import pytest

from stanton import Distribution, Session, StantonError
from stanton.elicitation import instrument_digest, model_digest, validate_survey_history
from stanton.schemas import validate_state


@pytest.fixture
def s(tmp_path):
    session = Session.create(tmp_path / "elicitation")
    session.define("area", units="meter**2", definition="Roof surface area", space="linear")
    session.define("rate", units="USD/meter**2", definition="Installed price per unit area")
    session.define("cost", units="USD", definition="Total roof cost", status="target")
    session.decision("finish", options={"standard": 1, "premium": 2}, definition="Chosen finish")
    session.relate("cost", "area*rate*finish")
    return session


def draft(s, **kwargs):
    return s.survey_draft("roof", phase="triage", **kwargs)["response_template"]


def answered(template, *, respondent="owner", kind="asker"):
    payload = deepcopy(template)
    payload["responses"][0].update(respondent={"id": respondent, "kind": kind}, answers={
        "leaf__area": {"status": "point", "value": 1000000, "units": "centimeter**2", "reason": "Measured footprint"},
        "leaf__rate": {"status": "interval", "low": 80, "high": 120, "units": "USD/meter**2", "reason": "Synthetic quote range"},
        "decision__finish": {"status": "open", "reason": "Compare both finishes"},
    })
    return payload


def test_draft_ingest_review_apply_preserve_units_intervals_and_provenance(s, tmp_path):
    payload = answered(draft(s))
    state_before, _ = s.store.read()
    result = s.survey_ingest("roof", payload, source="Synthetic interview")
    assert len(result["proposal_ids"]) == 3
    state, _ = s.store.read()
    assert model_digest(state) == model_digest(state_before)
    assert not state["estimates"]
    review = s.survey_review("roof")
    assert not review["stale"] and not review["conflicts"]
    response = next(iter(review["responses"].values()))
    assert response["raw"] == payload["responses"][0]
    assert response["answers"]["leaf__area"]["value"] == 100
    s.survey_apply("roof", "all", reason="Accept interview inputs; compare both finishes")
    state, _ = s.store.read()
    assert state["decisions"]["finish"]["status"] == "open"
    assert state["estimates"]["area"]["distribution"]["parameters"] == [100]
    distribution = Distribution.from_dict(state["estimates"]["rate"]["distribution"])
    assert np.allclose(distribution.ppf([.1, .9]), [80, 120])
    run = s.sample("cost", n=100)
    assert np.array_equal(np.asarray(run["samples"]["main@[finish=standard]"]) * 2,
                          run["samples"]["main@[finish=premium]"])
    audit = s.audit("cost", run_id=run["id"])
    assert audit["elicitation"]["roof"]["responses"][response["id"]]["raw"] == payload["responses"][0]
    archive = tmp_path / "interview.gz"
    s.save(archive)
    restored = Session(tmp_path / "restored")
    restored.load(archive)
    assert restored.survey_review("roof") == s.survey_review("roof")
    assert restored.store.run(run["id"]) == run
    assert restored.validate()["ok"]


@pytest.mark.parametrize("change", ["estimate", "definition", "context", "relation"])
def test_model_changes_reject_stale_import_without_writing(s, change):
    payload = answered(draft(s))
    if change == "estimate":
        s.estimate("area", Distribution.from_point(120), reason="New measurement")
    elif change == "definition":
        s.definition("scope", target="cost", measure="Roof spend", predicates={})
    elif change == "context":
        s.context(at="2020-01-01T00:00:00+00:00")
    else:
        s.relate("cost", "2*area*rate*finish")
    before = s.store.read()
    with pytest.raises(StantonError, match="stale"):
        s.survey_ingest("roof", payload, source="Fixture")
    assert s.store.read() == before
    assert s.survey_show("roof")["stale"]


def test_notes_and_other_drafts_do_not_stale_instruments(s):
    payload = answered(draft(s))
    s.note("roof", "Ask the owner on Friday")
    s.survey_draft("second", nodes=["area"])
    s.survey_ingest("roof", payload, source="Fixture")
    assert not s.survey_review("roof")["stale"]
    assert s.validate()["ok"]


def test_duplicate_rows_and_bad_units_roll_back_the_whole_batch(s):
    payload = answered(draft(s))
    batch = deepcopy(payload)
    batch["responses"].append(deepcopy(payload["responses"][0]))
    before = s.store.read()
    with pytest.raises(StantonError, match="Duplicate"):
        s.survey_ingest("roof", batch, source="Fixture")
    assert s.store.read() == before
    bad = deepcopy(payload)
    bad["responses"].append(deepcopy(payload["responses"][0]))
    bad["responses"][1]["respondent"]["id"] = "other"
    bad["responses"][1]["answers"]["leaf__area"]["units"] = "second"
    before = s.store.read()
    with pytest.raises(StantonError, match="units"):
        s.survey_ingest("roof", bad, source="Fixture")
    assert s.store.read() == before
    s.survey_ingest("roof", payload, source="Fixture")
    before = s.store.read()
    with pytest.raises(StantonError, match="Duplicate"):
        s.survey_ingest("roof", payload, source="Same answers in a renamed file")
    assert s.store.read() == before


@pytest.mark.parametrize("answer", [
    {"status": "point", "value": True, "units": "meter**2"},
    {"status": "point", "value": "100", "units": "meter**2"},
    {"status": "point", "value": 100},
    {"status": "interval", "low": 120, "high": 80, "units": "meter**2"},
    {"status": "unknown"},
    {"status": "unanswered", "value": 100},
])
def test_invalid_answer_types_cannot_create_proposals(s, answer):
    payload = draft(s)
    payload["responses"][0]["answers"]["leaf__area"] = answer
    before = s.store.read()
    with pytest.raises(StantonError):
        s.survey_ingest("roof", payload, source="Fixture")
    assert s.store.read() == before


def test_unknown_unanswered_and_explicit_reasking(s):
    payload = draft(s)
    payload["responses"][0]["answers"]["leaf__area"] = {"status": "unknown", "reason": "No measurement exists"}
    result = s.survey_ingest("roof", payload, source="Owner")
    assert not result["proposal_ids"]
    automatic = s.survey_draft("next", phase="triage")["instrument"]
    assert "leaf__area" not in automatic["slots"] and "leaf__rate" in automatic["slots"]
    explicit = s.survey_draft("again", nodes=["area"])["instrument"]
    assert list(explicit["slots"]) == ["leaf__area"]
    assert "leaf__area" in s.survey_draft("retry", reask=True)["instrument"]["slots"]


def test_conflicts_require_one_proposal_per_slot_and_review_is_atomic(s):
    template = draft(s, nodes=["area"])
    payload = deepcopy(template)
    payload["responses"] = [{"respondent": {"id": person, "kind": "human_panel"},
        "answers": {"leaf__area": {"status": "point", "value": value, "units": "meter**2"}}}
        for person, value in (("a", 100), ("b", 120))]
    result = s.survey_ingest("roof", payload, source="Independent survey responses")
    assert "leaf__area" in s.survey_review("roof")["conflicts"]
    before = s.store.read()
    with pytest.raises(StantonError, match="Conflicting"):
        s.survey_apply("roof", "all", reason="Invalid ambiguous application")
    assert s.store.read() == before
    first, second = result["proposal_ids"]
    s.survey_apply("roof", [first], reason="Use the measured response")
    with pytest.raises(StantonError, match="stale"):
        s.survey_apply("roof", [second], reason="Cannot overwrite after model change")
    s.survey_reject("roof", [second], reason="Superseded by measured response")
    assert s.validate()["ok"]


def test_revision_binding_and_instrument_changes_are_detected(s):
    payload = draft(s)
    for field in ("instrument_id", "instrument_sha256", "model_revision", "model_sha256", "project_id"):
        bad = deepcopy(payload)
        bad[field] = "wrong"
        with pytest.raises(StantonError, match="does not match"):
            s.survey_ingest("roof", bad, source="Fixture")
    state, revision = s.store.read()
    bad = deepcopy(state)
    bad["surveys"]["roof"]["instrument"]["slots"]["leaf__area"]["quantity"]["units"] = "second"
    with pytest.raises(StantonError, match="digest"):
        validate_state(bad)
    instrument = bad["surveys"]["roof"]["instrument"]
    instrument["sha256"] = instrument_digest(instrument)
    states = [s.store.read(r)[0] for r in range(1, revision)] + [bad]
    with pytest.raises(StantonError, match="archived"):
        validate_survey_history(states)


def test_existing_estimate_revision_and_synthetic_provenance(s):
    s.estimate("area", Distribution.from_point(100), reason="Initial estimate")
    prior_id = s.store.read()[0]["estimates"]["area"]["id"]
    payload = draft(s, nodes=["area"])
    payload["responses"][0].update(respondent={"id": "persona1", "kind": "llm_panel"},
        answers={"leaf__area": {"status": "point", "value": 110, "units": "meter**2", "reason": "Synthetic judgment"}})
    s.survey_ingest("roof", payload, source="Synthetic test panel")
    s.survey_apply("roof", "all", reason="Use as an explicitly synthetic assumption")
    estimate = s.store.read()[0]["estimates"]["area"]
    assert estimate["previous"] == prior_id and estimate["elicitation"]["calibrated"] is False
    assert any(w["code"] == "synthetic-elicitation" for w in s.lint()["warnings"])
    assert s.validate()["ok"]


def test_draft_budget_and_unsupported_slots(s):
    assert list(s.survey_draft("one", phase="triage", budget=1)["instrument"]["slots"]) == ["decision__finish"]
    assert list(s.survey_draft("two", budget=1)["instrument"]["slots"]) == ["leaf__area"]
    with pytest.raises(StantonError, match="primitive"):
        s.survey_draft("invalid", nodes=["cost"])
    s.scenario("busy", p=1, definition="Busy", reason="Fixture")
    s.estimate("area", Distribution.from_point(100), given="busy", reason="Fixture")
    with pytest.raises(StantonError, match="Conditional"):
        s.survey_draft("conditional", nodes=["area"])


def test_reelicited_estimate_retains_explicit_source_scope(s):
    s.definition("scope", target="cost", measure="Roof spend", predicates={"shed": False})
    s.estimate("area", Distribution.from_point(100), definition_id="scope", reason="Original scoped estimate")
    payload = draft(s, nodes=["area"])
    payload["responses"][0]["answers"]["leaf__area"] = {"status": "point", "value": 110, "units": "meter**2"}
    s.survey_ingest("roof", payload, source="Owner's correction in the same scope")
    s.survey_apply("roof", "all", reason="Accept scoped correction")
    state, _ = s.store.read()
    assert state["estimates"]["area"]["definition_id"] == "scope"
    assert state["estimates"]["area"]["definition_revision"] == state["definitions"]["scope"]["id"]
    assert s.validate()["ok"]
