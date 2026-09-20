import gzip
import json

import numpy as np
import pytest

from stanton import Distribution, Session, StantonError
from stanton.common import digest, now
from stanton.scoring import empirical_score


def test_crps_matches_pairwise_definition_with_ties_and_translation():
    rng = np.random.default_rng(21)
    for draws in ([2], [1, 1, 3], [-4, 0, 2, 8], rng.normal(size=300)):
        values = np.asarray(draws)
        for outcome in (-5, 1, 10):
            expected = np.mean(abs(values - outcome)) - .5 * np.mean(abs(values[:, None] - values))
            assert empirical_score(values, outcome)["crps"] == pytest.approx(expected)
            assert empirical_score(values + 1000, outcome + 1000)["crps"] == pytest.approx(expected)


def test_scores_for_points_interval_misses_and_ties():
    score = empirical_score([10] * 20, 12, [.8])
    assert score["crps"] == score["absolute_error"] == 2
    assert score["intervals"][0]["score"] == pytest.approx(20)
    assert score["intervals"][0]["covered"] is False
    equal = empirical_score([10], 10, [.8])
    assert equal["pit_interval"] == [0, 1] and equal["pit_midrank"] == .5
    assert equal["intervals"][0]["covered"] and equal["crps"] == 0
    assert empirical_score([0, 1, 2, 3], -1, [.5])["intervals"][0]["score"] == 6


def test_empirical_crps_agrees_with_normal_limit_without_quadratic_memory():
    draws = np.random.default_rng(22).normal(size=100000)
    expected = (np.sqrt(2) - 1) / np.sqrt(np.pi)
    assert empirical_score(draws, 0)["crps"] == pytest.approx(expected, abs=.003)


@pytest.mark.parametrize("levels", [[], [0], [1], [.8, .8], [True]])
def test_bad_interval_contracts_fail(levels):
    with pytest.raises(StantonError):
        empirical_score([1], 1, levels)


@pytest.fixture
def s(tmp_path):
    session = Session.create(tmp_path / "evaluation")
    session.define("x", units="meter", definition="Synthetic realized length", space="linear", status="target")
    session.estimate("x", Distribution.from_point(10), reason="Synthetic forecast")
    return session


def resolved(s, run, *, event="length", outcome=11, observed_at=None, **kwargs):
    return s.resolve("x", outcome, event=event, run_id=run["id"], units="meter", source="Synthetic observation",
                     observed_at=observed_at or now(), **kwargs)["resolution"]


def member(run, event="length", split="test", group="independent", **kwargs):
    return {"event": event, "run_id": run["id"], "split": split, "group": group, **kwargs}


def test_resolution_units_frozen_runs_and_correction_history(s):
    run = s.sample("x", n=10)
    old = s.resolve("x", 1100, event="length", run_id=run["id"], units="centimeter", source="Synthetic observation", observed_at=now())["resolution"]
    assert old["outcome"] == 11 and old["supplied_outcome"] == 1100
    first = s.score("length")
    assert first["scores"]["strategy:main"]["crps"] == 1
    assert s.score("length", units="centimeter")["scores"]["strategy:main"]["crps"] == 100
    before = s.store.read()
    with pytest.raises(StantonError, match="already resolved"):
        resolved(s, run, outcome=12)
    assert s.store.read() == before
    updated = resolved(s, run, outcome=12, replaces=old["id"], reason="Corrected measurement")
    assert s.score("length")["scores"]["strategy:main"]["crps"] == 2
    assert s.score("length", resolution_id=old["id"])["scores"] == first["scores"]
    assert s.resolution_show("length")["current_resolution_id"] == updated["id"]
    with pytest.raises(StantonError, match="already resolved"):
        resolved(s, run, replaces=old["id"], reason="Stale correction")
    s.estimate("x", Distribution.from_point(500), reason="New forecast input")
    assert s.store.run(run["id"]) == run
    assert s.score("length")["scores"]["strategy:main"]["median"] == 10
    assert s.validate()["ok"]


def test_realized_context_excludes_alternative_definitions_decisions_and_flips(s):
    s.define("base", units="meter", definition="Base length", space="linear")
    s.estimate("base", Distribution.from_point(10), reason="Fixture")
    s.define("extra", units="meter", definition="Optional extra length", predicates={"extra": True})
    s.estimate("extra", Distribution.from_point(2), reason="Fixture")
    s.decision("size", options={"small": 1, "large": 2}, definition="Chosen size")
    s.relate("x", "base*size+extra")
    for name, included in (("full", True), ("base_only", False)):
        s.definition(name, target="x", measure="Length", predicates={"extra": included})
    s.fork("x", "alternative")
    s.relate("x", "base*size+extra+base/10", fork="alternative")
    s.merge("x", ["main", "alternative"], [.5, .5], reason="Compare supplied strategies")
    run = s.sample("x", n=100, definitions="all", predicate_flips=True)
    with pytest.raises(StantonError, match="ambiguous"):
        resolved(s, run)
    with pytest.raises(StantonError, match="ambiguous"):
        resolved(s, run, definition="full")
    record = resolved(s, run, outcome=12, definition="full", decisions={"size": "small"})
    score = s.score("length")
    assert set(score["scores"]) == {"strategy:main", "strategy:alternative", "mixture"}
    assert score["scores"]["strategy:main"]["crps"] == 0
    assert len(record["forecast"]["branches"]) == 2
    s.definition("full", target="x", measure="Revised length definition", predicates={"extra": False})
    new = s.sample("x", n=100, definitions="all")
    with pytest.raises(StantonError, match="differ"):
        s.score("length", run_id=new["id"])
    assert s.score("length")["scores"] == score["scores"]
    assert s.validate()["ok"]


@pytest.mark.parametrize("bad", ["units", "source", "time", "outcome"])
def test_invalid_outcome_does_not_mutate_model(s, bad):
    run = s.sample("x", n=10)
    kwargs = dict(event="length", run_id=run["id"], units="meter", source="Fixture", observed_at=now())
    outcome = 10
    if bad == "units":
        kwargs["units"] = "second"
    elif bad == "source":
        kwargs["source"] = ""
    elif bad == "time":
        kwargs["observed_at"] = "2020-01-01"
    else:
        outcome = True
    before = s.store.read()
    with pytest.raises(StantonError):
        s.resolve("x", outcome, **kwargs)
    assert s.store.read() == before


def test_cohort_counts_unresolved_excludes_retrospective_and_separates_splits(s):
    run = s.sample("x", n=10)
    members = [member(run, "a", "train", "group_a"), member(run, "b", "test", "group_b"),
               member(run, "c", "test", "group_b"), member(run, "d", "test", "group_d")]
    s.cohort_define("bank", members, units="meter", reason="Fixed synthetic evaluation cases")
    resolved(s, run, event="a", outcome=10)
    resolved(s, run, event="b", outcome=12)
    resolved(s, run, event="c", outcome=11, observed_at="2000-01-01T00:00:00+00:00")
    report = s.cohort_evaluate("bank")
    train, test = report["splits"]["train"], report["splits"]["test"]
    assert train["n_events"] == 1 and train["matched_methods"]["strategy:main"]["mean_crps"] == 0
    assert test["registered"] == 3 and test["n_events"] == 1 and test["unresolved"] == 1 and test["excluded_retrospective"] == 1
    assert test["matched_methods"]["strategy:main"]["mean_crps"] == 2
    retrospective = s.cohort_evaluate("bank", include_retrospective=True)["splits"]["test"]
    assert retrospective["n_events"] == 2 and retrospective["n_groups"] == 1
    assert retrospective["matched_methods"]["strategy:main"]["mean_crps"] == 1.5
    assert s.validate()["ok"]


def test_empty_cohort_results_are_not_zero_scores_and_future_dates_are_excluded(s):
    run = s.sample("x", n=10)
    s.cohort_define("empty", [member(run)], units="meter", reason="Fixture")
    report = s.cohort_evaluate("empty")["splits"]["test"]
    assert report["unresolved"] == 1 and report["matched_methods"] == {}
    resolved(s, run, observed_at="2999-01-01T00:00:00+00:00")
    report = s.cohort_evaluate("empty", include_retrospective=True)["splits"]["test"]
    assert report["excluded_future_observation"] == 1 and report["matched_methods"] == {}


def test_cohort_registration_rejects_split_leakage_and_duplicate_events(s):
    run = s.sample("x", n=10)
    before = s.store.read()
    with pytest.raises(StantonError, match="cross"):
        s.cohort_define("bad", [member(run, "a", "train"), member(run, "b", "test")], units="meter", reason="Fixture")
    with pytest.raises(StantonError, match="once"):
        s.cohort_define("bad", [member(run), member(run)], units="meter", reason="Fixture")
    with pytest.raises(StantonError, match="compatible"):
        s.cohort_define("bad", [member(run)], units="second", reason="Fixture")
    assert s.store.read() == before


def test_matched_methods_use_identical_event_denominators(s):
    main = s.sample("x", n=10, fork="main")
    s.fork("x", "alternative")
    s.merge("x", ["main", "alternative"], [.5, .5], reason="Fixture")
    both = s.sample("x", n=10)
    s.cohort_define("matched", [member(main, "a", group="a"), member(both, "b", group="b")], units="meter", reason="Fixture")
    resolved(s, main, event="a")
    resolved(s, both, event="b")
    result = s.cohort_evaluate("matched")["splits"]["test"]
    assert result["n_events"] == 2
    assert result["method_availability"] == {"strategy:main": 2, "strategy:alternative": 1, "mixture": 1}
    assert set(result["matched_methods"]) == {"strategy:main"}


def test_archives_preserve_corrections_and_revision_pinned_evaluation(s, tmp_path):
    run = s.sample("x", n=10)
    old = resolved(s, run)
    s.cohort_define("late", [member(run)], units="meter", reason="Post-outcome diagnostic cohort")
    first = s.cohort_evaluate("late")
    assert first["registered_with_known_outcomes"] == first["registered_after_observation"] == 1
    resolved(s, run, outcome=13, replaces=old["id"], reason="Revised measurement")
    assert s.cohort_evaluate("late", revision=first["revision"]) == first
    archive = tmp_path / "bank.gz"
    s.save(archive)
    restored = Session(tmp_path / "restored")
    restored.load(archive)
    assert restored.cohort_evaluate("late") == s.cohort_evaluate("late")
    assert restored.cohort_evaluate("late", revision=first["revision"]) == first
    assert restored.validate()["ok"]
    payload = json.loads(gzip.decompress(archive.read_bytes()))
    # Re-sign a tampered binding: structural validation must reject it before creating a destination.
    for row in payload["data"]["revisions"]:
        for resolution in row["body"].get("resolutions", {}).values():
            resolution["forecast"]["run_sha256"] = "tampered"
        for cohort in row["body"].get("cohorts", {}).values():
            for m in cohort["members"]:
                m["forecast"]["run_sha256"] = "tampered"
        row["sha256"] = digest(row["body"])
    payload["sha256"] = digest(payload["data"])
    bad = tmp_path / "bad.gz"
    bad.write_bytes(gzip.compress(json.dumps(payload).encode()))
    with pytest.raises(StantonError, match="binding"):
        Session(tmp_path / "bad_project").load(bad)
    assert not (tmp_path / "bad_project").exists()


def test_outcome_bookkeeping_does_not_stale_surveys(s):
    run = s.sample("x", n=10)
    s.survey_draft("ask", nodes=["x"])
    resolved(s, run)
    s.cohort_define("bank", [member(run)], units="meter", reason="Fixture")
    assert not s.survey_show("ask")["stale"]
    assert s.validate()["ok"]
