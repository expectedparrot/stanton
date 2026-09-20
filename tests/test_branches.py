import gzip
import json
from copy import deepcopy

import numpy as np
import pytest

from stanton import Distribution, Session, StantonError
from stanton.branch_sampling import validate_branch_run
from stanton.common import digest


def quantity(s, node, *, units="USD", predicates=None, status="estimated"):
    s.define(node, units=units, definition=f"Synthetic {node}", predicates=predicates, status=status)


@pytest.fixture
def s(tmp_path):
    return Session.create(tmp_path / "branches")


def regimes(s, group="economy"):
    s.scenario("low", p=.3, definition="Low regime", reason="Fixture", group=group)
    s.scenario("high", p=.7, definition="High regime", reason="Fixture", group=group)


def test_shared_regime_across_leaves_and_forks(s):
    regimes(s)
    for node in ("revenue", "cost", "net"):
        quantity(s, node)
    for scenario, value in (("low", 10), ("high", 100)):
        s.estimate("revenue", Distribution.from_point(value), given=scenario, reason="Fixture")
        s.estimate("cost", Distribution.from_point(value / 2), given=scenario, reason="Fixture")
    s.relate("net", "revenue - cost")
    s.fork("net", "alternate")
    s.relate("net", "2*(revenue - cost)", fork="alternate")
    s.merge("net", ["main", "alternate"], [.5, .5], reason="Fixture")
    run = s.sample("net", n=20000, seed=91)
    revenue, cost = np.array(run["leaf_samples"]["revenue"]), np.array(run["leaf_samples"]["cost"])
    assert np.array_equal(revenue, cost * 2)
    assert np.array_equal(np.array(run["samples"]["main"]) * 2, run["samples"]["alternate"])
    assert np.mean(revenue == 10) == pytest.approx(.3, abs=.015)
    assert set(run["samples"]["main"]) == {5, 50}
    assert run["scenario_frequencies"]["economy"]["low"]["retained"] == np.mean(revenue == 10)
    assert s.validate()["ok"]
    original = run["leaf_estimates"]["revenue"]["given"]["high"]
    s.estimate("revenue", Distribution.from_point(200), given="high", reason="Revision")
    assert s.audit("net", run_id=run["id"])["conditional_estimates"]["revenue"]["high"]["id"] == original


def test_partial_probabilities_and_missing_conditional_are_not_normalized(s):
    quantity(s, "x")
    s.scenario("low", p=.4, definition="Low")
    s.estimate("x", Distribution.from_point(1), given="low", reason="Fixture")
    assert {"incomplete-scenarios", "unsourced-scenario-p"} <= {w["code"] for w in s.lint()["warnings"]}
    with pytest.raises(StantonError, match="sum to one"):
        s.sample("x", n=100)
    s.scenario("high", p=.6, definition="High", reason="Fixture")
    with pytest.raises(StantonError, match="Missing conditional"):
        s.sample("x", n=100)
    s.estimate("x", Distribution.from_point(2), reason="Explicit fallback")
    run = s.sample("x", n=1000)
    assert set(run["samples"]["main"]) == {1, 2}
    assert set(s.audit("x", run_id=run["id"])["scenarios"]) == {"low", "high"}


def test_multiple_groups_require_independence_record(s):
    for node in ("x", "y", "total"):
        quantity(s, node)
    for group, leaf in (("demand", "x"), ("prices", "y")):
        for scenario, p, value in ((group + "_low", .5, 1), (group + "_high", .5, 2)):
            s.scenario(scenario, p=p, definition=scenario, reason="Fixture", group=group)
            s.estimate(leaf, Distribution.from_point(value), given=scenario, reason="Fixture")
    s.relate("total", "x+y")
    with pytest.raises(StantonError, match="independence reasons"):
        s.sample("total", n=100)
    for group in ("demand", "prices"):
        s.scenario_group(group, definition=group, independence_reason="Independent synthetic factors")
    run = s.sample("total", n=10000)
    assert abs(np.corrcoef(run["leaf_samples"]["x"], run["leaf_samples"]["y"])[0, 1]) < .04


def test_decisions_are_paired_branches_not_probabilities(s):
    quantity(s, "price")
    quantity(s, "cost", status="target")
    s.estimate("price", Distribution.from_interval(10, 20), reason="Fixture")
    s.decision("scale", options={"small": 1, "large": 3}, definition="User-selected scale", default="small")
    s.relate("cost", "price * scale")
    run = s.sample("cost", n=1000)
    assert "scale" not in run["leaf_samples"]
    assert run["merged_samples"] is None
    small = np.array(run["samples"]["main@[scale=small]"])
    assert np.array_equal(small * 3, run["samples"]["main@[scale=large]"])
    s.choose("scale", leave_open=True, reason="Asker wants both options")
    assert s.status()["decisions"]["scale"]["status"] == "open"
    selected = s.sample("cost", n=10, decisions={"scale": "small"})
    assert len(selected["branches"]) == 1
    assert s.status()["decisions"]["scale"]["status"] == "open"
    s.choose("scale", option="large", reason="Asker selected larger scale")
    assert list(s.sample("cost", n=10)["branches"]) == ["main@[scale=large]"]
    with pytest.raises(StantonError, match="Decisions"):
        s.estimate("scale", Distribution.from_point(2), reason="Cannot sample a choice")
    assert s.validate()["ok"]


def definition_fixture(s):
    quantity(s, "core")
    quantity(s, "commerce", predicates={"commerce": True})
    quantity(s, "total", status="target")
    s.estimate("core", Distribution.from_point(10), reason="Fixture")
    s.estimate("commerce", Distribution.from_point(90), reason="Fixture")
    s.relate("total", "core+commerce")
    s.definition("strict", target="total", measure="earnings", predicates={"commerce": False}, owner="claimant", role="primary")
    s.definition("broad", target="total", measure="earnings", predicates={"commerce": True})


def test_definition_masks_claim_ties_and_predicate_flip_sensitivity(s):
    definition_fixture(s)
    run = s.sample("total", n=100, definitions="all", predicate_flips=True)
    assert run["samples"]["main@strict"] == [10] * 100
    assert run["samples"]["main@broad"] == [100] * 100
    assert run["samples"]["main@strict~commerce"] == run["samples"]["main@broad"]
    assert run["merged_samples"] is None
    verdict = s.check(100, "total", definition="strict")
    result = verdict["results"]["main@strict"]
    assert result["percentile"] == 100 and result["verdict"] == "above_p95"
    flipped = result["predicate_flips"]["commerce"]
    assert flipped["changes_verdict"] and flipped["percentile"] == 50
    assert flipped["percentile_interval"] == [0, 100] and flipped["equal_mass"] == 1
    assert flipped["paired_difference"]["mean"] == 90
    assert s.validate()["ok"]


def test_masked_subgraphs_do_not_need_unknown_leaf_values(s):
    quantity(s, "unknown")
    quantity(s, "optional", predicates={"include": True})
    quantity(s, "total", status="target")
    s.relate("optional", "unknown")
    s.relate("total", "optional")
    s.definition("narrow", target="total", measure="spend", predicates={"include": False}, role="primary")
    run = s.sample("total", n=10)
    assert run["samples"]["main@narrow"] == [0] * 10
    assert not run["leaf_samples"]
    assert s.validate()["ok"]
    with pytest.raises(StantonError, match="Missing estimates"):
        s.sample("total", n=10, predicate_flips=True)


def test_mixtures_never_cross_definitions_or_decisions(s):
    definition_fixture(s)
    s.decision("scale", options={"small": 1, "large": 2}, definition="Scale")
    s.relate("total", "(core+commerce)*scale")
    s.fork("total", "second")
    s.relate("total", "2*(core+commerce)*scale", fork="second")
    s.merge("total", ["main", "second"], [.5, .5], reason="Fixture")
    run = s.sample("total", n=100, definitions="all", predicate_flips=True)
    assert run["merged_samples"] is None and run["merged_summary"] is None
    assert len(run["mixtures"]) == 8
    small = np.array(run["mixtures"]["strict[scale=small]"]["samples"])
    large = np.array(run["mixtures"]["strict[scale=large]"]["samples"])
    assert np.array_equal(small * 2, large)
    assert set(small) == {10, 20}
    assert s.check(100, "total", definition="strict")["results"]["mixture@strict[scale=small]"]["verdict"] == "above_p95"
    assert s.validate()["ok"]


def test_clipping_preserves_regimes_and_paired_decisions(s):
    regimes(s)
    quantity(s, "x")
    quantity(s, "total")
    s.estimate("x", Distribution.from_point(10), given="low", reason="Fixture")
    s.estimate("x", Distribution.from_point(100), given="high", reason="Fixture")
    s.decision("scale", options={"small": 1, "large": 2}, definition="Scale")
    s.relate("total", "x*scale")
    s.bound("x", upper=20, reason="Condition on low outcomes", clip=True)
    run = s.sample("total", n=1000, seed=9)
    assert run["samples"]["main@[scale=small]"] == [10] * 1000
    assert run["samples"]["main@[scale=large]"] == [20] * 1000
    assert run["scenario_frequencies"]["economy"]["high"]["retained"] == 0
    assert run["scenario_frequencies"]["economy"]["high"]["unconditioned"] == pytest.approx(.7, abs=.03)
    assert s.validate()["ok"]


def test_definition_tags_bridges_and_revision_provenance(s):
    definition_fixture(s)
    s.definition("reconstructed", target="total", measure="TAM", predicates={"commerce": True},
                 owner="reconstructed", confidence="low", source="Synthetic public summary")
    quantity(s, "published")
    s.anchor("published", 200, source="Synthetic figure", asof="2026", definition_id="reconstructed")
    s.bridge("conversion", "reconstructed", "strict", Distribution.from_interval(.4, .6), source="Synthetic bridge evidence")
    s.relate("total", "published*conversion")
    run = s.sample("total", n=100)
    audit = s.audit("total", run_id=run["id"])
    assert audit["bridges"]["conversion"]["from"] == "reconstructed"
    assert audit["definitions"]["reconstructed"]["confidence"] == "low"
    assert audit["estimates"]["conversion"]["method"] == "definition_bridge"
    s.definition("reconstructed", target="total", measure="TAM", predicates={"commerce": False},
                 owner="reconstructed", confidence="medium", source="Revised synthetic summary")
    codes = {warning["code"] for warning in s.lint()["warnings"]}
    assert {"stale-definition-tag", "stale-definition-bridge"} <= codes
    assert s.audit("total", run_id=run["id"])["definitions"]["reconstructed"]["confidence"] == "low"


def test_branch_archives_roundtrip_and_invalid_decisions_rollback(s, tmp_path):
    definition_fixture(s)
    run = s.sample("total", n=25, definitions="all", predicate_flips=True)
    before = s.store.read()[1]
    with pytest.raises(StantonError):
        s.decision("invalid", options={"one": 1}, definition="Invalid single choice")
    assert s.store.read()[1] == before
    path = tmp_path / "branches.gz"
    s.save(path)
    restored = Session(tmp_path / "restored")
    restored.load(path)
    assert restored.store.run(run["id"]) == run
    assert restored.check(100, "total", definition="strict") == s.check(100, "total", definition="strict")
    second = tmp_path / "second.gz"
    restored.save(second)
    assert gzip.decompress(path.read_bytes()) == gzip.decompress(second.read_bytes())
    assert json.loads(gzip.decompress(second.read_bytes()))["data"]["revisions"][-1]["body"]["schema_version"] == 6


def test_legacy_run_remains_valid_when_project_gains_conditional_estimates(s, tmp_path):
    quantity(s, "x")
    s.estimate("x", Distribution.from_point(5), reason="Legacy fixture")
    run = s.sample("x", n=10)
    state = s.store.read()[0]
    state["schema_version"] = 1
    for field in ("scenario_groups", "scenarios", "conditional_estimates", "decisions", "definitions", "bridges"):
        state.pop(field)
    legacy = Session(tmp_path / "legacy")
    legacy.store.init(state)
    run.update(schema_version=1, engine="stanton.sampler.v1", state_sha256=digest(state),
               leaf_estimates={"x": state["estimates"]["x"]["id"]})
    for field in ("branches", "selection", "scenario_groups", "scenario_draws", "scenario_frequencies", "mixtures"):
        run.pop(field)
    old = legacy.store.put_run(run, 1)
    assert legacy.validate()["ok"]
    legacy.scenario("only", p=1, definition="Single regime", reason="Fixture")
    legacy.estimate("x", Distribution.from_point(8), given="only", reason="New estimate")
    new = legacy.sample("x", n=10)
    assert legacy.show("x", run_id=old["id"])["forks"]["main"]["mean"] == 5
    assert new["samples"]["main"] == [8] * 10
    assert legacy.validate()["ok"]
    archive = tmp_path / "mixed.gz"
    legacy.save(archive)
    restored = Session(tmp_path / "mixed-restored")
    restored.load(archive)
    assert restored.store.run(old["id"]) == old
    assert restored.validate()["ok"]


def test_saved_scenario_assignments_and_mixture_metadata_are_validated(s):
    regimes(s)
    quantity(s, "x")
    for scenario, value in (("low", 1), ("high", 2)):
        s.estimate("x", Distribution.from_point(value), given=scenario, reason="Fixture")
    run = s.sample("x", n=100)
    altered = deepcopy(run)
    altered["scenario_draws"]["economy"] = [1 - i for i in altered["scenario_draws"]["economy"]]
    with pytest.raises(StantonError, match="frequencies"):
        validate_branch_run(altered, s.store.read()[0])
    altered = deepcopy(run)
    altered["merged_samples"] = [3] * 100
    with pytest.raises(StantonError, match="merged-result aliases"):
        validate_branch_run(altered, s.store.read()[0])


def test_missing_definitions_and_missing_predicates_fail_without_new_runs(s):
    quantity(s, "x", predicates={"include": True})
    s.estimate("x", Distribution.from_point(3), reason="Fixture")
    with pytest.raises(StantonError, match="select a definition"):
        s.sample("x", n=10)
    s.definition("incomplete", target="x", measure="spend", predicates={}, role="primary")
    with pytest.raises(StantonError, match="lacks predicates"):
        s.sample("x", n=10)
    with pytest.raises(StantonError, match="No matching sample"):
        s.show("x")


def test_zero_probability_regimes_need_no_estimate(s):
    quantity(s, "x")
    s.scenario("never", p=0, definition="Impossible in this fixture", reason="Fixture")
    s.scenario("always", p=1, definition="Certain in this fixture", reason="Fixture")
    s.estimate("x", Distribution.from_point(7), given="always", reason="Fixture")
    assert s.sample("x", n=100)["samples"]["main"] == [7] * 100
    assert s.validate()["ok"]


def test_next_handles_conditional_models_and_excluded_unknowns(s):
    from stanton.guidance import next_actions
    quantity(s, "unknown")
    quantity(s, "optional", predicates={"include": True})
    quantity(s, "total", status="target")
    s.relate("optional", "unknown")
    s.relate("total", "optional")
    s.definition("narrow", target="total", measure="spend", predicates={"include": False}, role="primary")
    tasks = next_actions(s)["next_actions"]
    assert any(task["kind"] == "sample" for task in tasks)
    s.definition("narrow", target="total", measure="spend", predicates={"include": True}, role="primary")
    tasks = next_actions(s)["next_actions"]
    assert any(task["kind"] == "complete_model" and task["code"] == "incomplete_model" for task in tasks)
