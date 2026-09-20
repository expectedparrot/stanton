from copy import deepcopy

import numpy as np
import pytest

from stanton import Distribution, Session, StantonError
from stanton.branch_sampling import validate_branch_run


@pytest.fixture
def s(tmp_path):
    return Session.create(tmp_path / "processes", timezone="America/New_York")


def quantity(s, node, units="USD", status="estimated"):
    s.define(node, units=units, definition=f"Synthetic {node}", space="linear", status=status)


def base_path(s, *, rho=.75, mode="additive", periods=(2026, 2027, 2028, 2029)):
    quantity(s, "base")
    quantity(s, "growth", "USD" if mode == "additive" else "dimensionless")
    quantity(s, "end", status="target")
    s.anchor("base", 100, source="Synthetic fixture", asof="2026-01")
    distribution = Distribution("normal", (0, 2)) if mode == "additive" else Distribution.from_interval(1.01, 1.1)
    s.estimate("growth", distribution, reason="Synthetic marginal growth prior")
    s.series("path", base="base", growth="growth", periods=periods, rho=rho, mode=mode,
             definition="Synthetic equal-step path", reason="Synthetic persistence assumption")
    s.relate_path("end", "path")


def test_ar1_path_matches_covariance_and_terminal_variance(s):
    base_path(s)
    run = s.sample("end", n=50000, seed=9)
    growth = run["process_draws"]["growth"]["path"]
    assert np.corrcoef(growth["2027"], growth["2028"])[0, 1] == pytest.approx(.75, abs=.015)
    assert np.corrcoef(growth["2027"], growth["2029"])[0, 1] == pytest.approx(.75**2, abs=.015)
    expected_variance = 4 * (3 + 2 * (2 * .75 + .75**2))
    assert np.var(run["samples"]["main"]) == pytest.approx(expected_variance, rel=.025)
    assert "growth" not in run["leaf_samples"]
    assert "growth" in run["process_priors"]
    shown = s.series_show("path", run_id=run["id"])
    assert set(shown["branches"]["main"]) == {"2026", "2027", "2028", "2029"}
    assert s.validate()["ok"]


@pytest.mark.parametrize("rho", [-1, 0, 1])
def test_persistence_boundaries(s, rho):
    base_path(s, rho=rho)
    run = s.sample("end", n=10000, seed=1)
    a = np.asarray(run["process_draws"]["growth"]["path"]["2027"])
    b = np.asarray(run["process_draws"]["growth"]["path"]["2028"])
    if rho == 0:
        assert abs(np.corrcoef(a, b)[0, 1]) < .04
    else:
        assert np.allclose(b, rho * a, atol=1e-12)


def test_scenario_conditional_growth_regime_persists_for_whole_path(s):
    base_path(s, mode="multiplicative")
    s.scenario("slow", p=.4, definition="Slow regime", reason="Fixture", group="economy")
    s.scenario("fast", p=.6, definition="Fast regime", reason="Fixture", group="economy")
    s.estimate("growth", Distribution.from_point(1.1), given="slow", reason="Fixture")
    s.estimate("growth", Distribution.from_point(1.2), given="fast", reason="Fixture")
    s.fork("end", "double")
    s.relate("end", "2*path__2029", fork="double")
    s.merge("end", ["main", "double"], [.5, .5], reason="Fixture")
    run = s.sample("end", n=1000, seed=5)
    growth = run["process_draws"]["growth"]["path"]
    assert growth["2027"] == growth["2028"] == growth["2029"]
    assert np.allclose(run["samples"]["main"], 100 * np.asarray(growth["2027"])**3)
    assert np.array_equal(np.asarray(run["samples"]["main"]) * 2, run["samples"]["double"])
    assert .35 < np.mean(np.asarray(growth["2027"]) == 1.1) < .45
    audit = s.audit("end", run_id=run["id"])
    assert audit["series"]["path"]["rho"] == .75
    assert set(audit["conditional_estimates"]["growth"]) == {"slow", "fast"}
    assert s.validate()["ok"]
    bad = deepcopy(run)
    bad["process_draws"]["growth"]["path"]["2027"][0] = 1.15
    with pytest.raises(StantonError, match="scenario prior support"):
        validate_branch_run(bad, s.store.read()[0])


def test_anchor_resets_forward_without_rewriting_earlier_run(s):
    base_path(s, mode="multiplicative")
    old = s.sample("end", n=100, seed=42)
    quantity(s, "observed")
    s.anchor("observed", 250, source="Synthetic observation", asof="2028")
    s.series_anchor("path", 2028, "observed", reason="Reset to the observed level")
    new = s.sample("end", n=100, seed=42)
    assert np.allclose(new["samples"]["main"], 250 * np.asarray(new["process_draws"]["growth"]["path"]["2029"]))
    assert s.store.run(old["id"])["samples"] == old["samples"]
    assert set(s.series_show("path", run_id=new["id"])["branches"]["main"]) == {"2028", "2029"}
    assert s.validate()["ok"]


def test_growth_units_convert_and_fuzzy_anchor_dates_stay_metadata(s):
    quantity(s, "base")
    quantity(s, "growth", "percent")
    s.anchor("base", 100, source="Synthetic fuzzy date", asof="2020..2025")
    s.estimate("growth", Distribution.from_point(105), reason="Multiplier expressed as percent")
    s.series("path", base="base", growth="growth", periods=["a", "b"], rho=0, definition="Explicit equal steps", reason="No implicit date fitting")
    run = s.sample("path__b", n=10)
    assert np.allclose(run["samples"]["main"], 105)
    assert s.audit("path__b", run_id=run["id"])["estimates"]["base"]["asof"] == "2020..2025"
    assert any(w["code"] == "fuzzy-anchor-time" for w in run["warnings"])
    assert s.validate()["ok"]


def test_periodic_hour_uses_frozen_timezone_and_bucket(s):
    quantity(s, "daytime", "dimensionless")
    quantity(s, "nighttime", "dimensionless")
    s.estimate("daytime", Distribution.from_point(.1), reason="Fixture")
    s.estimate("nighttime", Distribution.from_point(.8), reason="Fixture")
    profile = {hour: "daytime" if 8 <= hour < 20 else "nighttime" for hour in range(24)}
    s.periodic("asleep", over="hour_of_day", profile=profile, definition="Synthetic profile", reason="Hourly step function")
    s.context(at="2026-09-19T15:00:00+00:00")
    day = s.sample("asleep", n=10)
    assert day["process_plan"]["periodic"]["asleep"]["period"] == "11"
    assert day["samples"]["main"] == [.1] * 10
    s.context(at="2026-09-20T02:00:00+00:00")
    night = s.sample("asleep", n=10)
    assert night["process_plan"]["periodic"]["asleep"]["period"] == "22"
    assert night["samples"]["main"] == [.8] * 10
    assert s.show("asleep", run_id=day["id"])["forks"]["main"]["mean"] == pytest.approx(.1)
    assert s.series_show("asleep", run_id=day["id"])["context"]["now"] == "2026-09-19T15:00:00+00:00"
    assert s.validate()["ok"]


def test_periodic_weekday_and_incomplete_profiles(s):
    quantity(s, "weekday", "dimensionless")
    quantity(s, "weekend", "dimensionless")
    s.estimate("weekday", Distribution.from_point(1), reason="Fixture")
    s.estimate("weekend", Distribution.from_point(2), reason="Fixture")
    with pytest.raises(StantonError, match="every index"):
        s.periodic("bad", over="day_of_week", profile={0: "weekday"}, definition="Incomplete", reason="Fixture")
    s.periodic("weekly", over="day_of_week", profile={i: "weekday" if i < 5 else "weekend" for i in range(7)}, definition="Weekly", reason="Fixture")
    s.context(at="2026-09-19T12:00:00-04:00")
    assert s.sample("weekly", n=10)["samples"]["main"] == [2] * 10


def test_generated_nodes_reject_overrides_and_hidden_cycles(s):
    base_path(s)
    with pytest.raises(StantonError, match="Generated quantities"):
        s.estimate("path__2028", Distribution.from_point(1), reason="Invalid override")
    with pytest.raises(StantonError, match="Generated quantities"):
        s.relate("path__2028", "base")
    with pytest.raises(StantonError, match="Cycle"):
        s.series_anchor("path", 2027, "path__2028", reason="Invalid future loop")
    quantity(s, "loop")
    s.periodic("profile", over="day_of_week", profile={i: "loop" if i == 1 else "base" for i in range(7)},
               definition="Hidden cycle fixture", reason="Fixture")
    with pytest.raises(StantonError, match="Cycle"):
        s.relate("loop", "profile")


def allocation(s):
    quantity(s, "total", status="known")
    quantity(s, "sum_parts", status="target")
    s.anchor("total", 100, source="Synthetic known total", asof="2026")
    s.allocate("total", {"a": 2, "b": 3, "c": 5}, allocation="budget", reason="Synthetic share prior")
    s.relate("sum_parts", "a+b+c")


def test_allocation_conserves_total_and_matches_dirichlet_moments(s):
    allocation(s)
    run = s.sample("sum_parts", n=30000, seed=7)
    shares = run["process_draws"]["shares"]["budget"]
    assert np.allclose(run["samples"]["main"], 100, rtol=0, atol=1e-12)
    assert np.mean(shares["a"]) == pytest.approx(.2, abs=.003)
    assert np.var(shares["a"]) == pytest.approx(2 * 8 / (100 * 11), rel=.04)
    assert np.cov(shares["a"], shares["b"])[0, 1] < 0
    report = s.allocation_show("budget", run_id=run["id"])
    assert report["max_conservation_error"] < 1e-12
    assert s.validate()["ok"]


def test_clipped_allocations_keep_the_whole_partition(s):
    allocation(s)
    s.bound("a", upper=10, reason="Condition on small a", clip=True)
    run = s.sample("sum_parts", n=1000, seed=7)
    shares = run["process_draws"]["shares"]["budget"]
    assert np.all(np.asarray(shares["a"]) * 100 <= 10)
    assert np.allclose(np.sum(list(shares.values()), axis=0), 1)
    assert np.allclose(run["samples"]["main"], 100)
    assert s.allocation_show("budget", run_id=run["id"])["max_conservation_error"] < 1e-12
    assert s.validate()["ok"]


def test_allocation_requires_known_total_and_preserves_revisions(s):
    allocation(s)
    old = s.sample("sum_parts", n=100, seed=1)
    with pytest.raises(StantonError, match="known point"):
        s.estimate("total", Distribution.from_interval(80, 120), reason="Uncertain total is unsupported")
    s.anchor("total", 200, source="Revised synthetic total", asof="2026")
    new = s.sample("sum_parts", n=100, seed=1)
    assert old["process_draws"] == new["process_draws"]
    assert np.allclose(new["samples"]["main"], 200)
    assert s.allocation_show("budget", run_id=old["id"])["total"] == 100
    assert s.validate()["ok"]


def test_process_archives_roundtrip_and_invalid_draws_fail(s, tmp_path):
    allocation(s)
    run = s.sample("sum_parts", n=25)
    bad = deepcopy(run)
    bad["process_draws"]["shares"]["budget"]["a"][0] = 1
    with pytest.raises(StantonError, match="conserve"):
        validate_branch_run(bad, s.store.read()[0])
    archive = tmp_path / "processes.gz"
    s.save(archive)
    restored = Session(tmp_path / "restored")
    restored.load(archive)
    assert restored.store.run(run["id"]) == run
    assert restored.allocation_show("budget", run_id=run["id"]) == s.allocation_show("budget", run_id=run["id"])
    assert restored.validate()["ok"]


def test_schema_version_does_not_downgrade_after_process_edits(s):
    base_path(s)
    s.scenario("only", p=1, definition="One scenario", reason="Fixture")
    s.estimate("growth", Distribution.from_point(2), given="only", reason="Fixture")
    assert s.store.read()[0]["schema_version"] == 7


def test_path_decisions_are_paired_and_excluded_processes_need_no_prior(s):
    base_path(s, mode="multiplicative")
    quantity(s, "fixed")
    s.anchor("fixed", 100, source="Fixture", asof="2026")
    s.decision("scale", options={"small": 1, "large": 2}, definition="Controlled starting size")
    s.relate("base", "fixed*scale")
    s.define("included", units="USD", definition="Optional path", predicates={"include_path": True})
    s.relate("included", "path__2029")
    s.relate("end", "included")
    for name, included in (("full", True), ("empty", False)):
        s.definition(name, target="end", measure="End level", predicates={"include_path": included})
    s.note("path", "Paired across all reported choices")
    run = s.sample("end", n=100, definitions="all")
    assert np.allclose(np.asarray(run["samples"]["main@full[scale=small]"]) * 2,
                       run["samples"]["main@full[scale=large]"])
    assert run["samples"]["main@empty[scale=small]"] == [0] * 100
    assert s.audit("end", run_id=run["id"])["notes"]["path"][0]["text"] == "Paired across all reported choices"
    excluded = s.sample("end", n=10, definitions=["empty"])
    assert excluded["process_plan"]["paths"] == {}
    assert excluded["process_priors"] == {}
    assert excluded["leaf_samples"] == {}
    assert s.validate()["ok"]


def test_additive_empirical_growth_converts_support(s):
    quantity(s, "base", "meter")
    quantity(s, "growth", "centimeter")
    s.anchor("base", 1, source="Fixture", asof="2026")
    s.estimate("growth", Distribution("empirical", (10, 20, 30)), reason="Synthetic increments")
    s.series("length", base="base", growth="growth", periods=["a", "b", "c"], rho=.5, mode="additive",
             definition="Length path", reason="Synthetic persistence")
    run = s.sample("length__c", n=100)
    assert set(run["process_draws"]["growth"]["length"]["b"]) <= {.1, .2, .3}
    assert s.validate()["ok"]
