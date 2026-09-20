import gzip
import json
import sqlite3

import numpy as np
import pytest

from stanton import Distribution, Session, StantonError
from stanton.common import canonical, digest
from stanton.expressions import parse


def define(session, name, units="dimensionless", space="linear", status="estimated"):
    session.define(name, units=units, definition="Synthetic fixture: " + name, space=space, status=status)


@pytest.fixture
def session(tmp_path):
    return Session.create(tmp_path / "project")


def test_shared_leaf_identities_and_independent_sum(session):
    for node in ["x", "y", "zero", "sum_xy"]:
        define(session, node)
    session.estimate("x", Distribution("normal", (4, 2)), reason="Fixture")
    session.estimate("y", Distribution("normal", (3, 3)), reason="Fixture")
    session.relate("zero", "x - x")
    session.relate("sum_xy", "x + y")
    zero = session.sample("zero", n=1000)
    assert zero["samples"]["main"] == [0] * 1000
    run = session.sample("sum_xy", n=100000, seed=42)
    assert run["summaries"]["main"]["mean"] == pytest.approx(7, abs=.04)
    assert run["summaries"]["main"]["std"] == pytest.approx(np.sqrt(13), abs=.04)
    define(session, "unrelated")
    session.estimate("unrelated", Distribution.from_point(99), reason="Fixture")
    again = session.sample("sum_xy", n=100000, seed=42)
    assert run["samples"] == again["samples"]


def test_units_convert_and_mismatch_warns_before_sampling_fails(session):
    define(session, "length_cm", "cm")
    define(session, "length_m", "meter")
    define(session, "duration", "second")
    session.anchor("length_cm", 250, source="Synthetic", asof="2026-01")
    session.anchor("duration", 5, source="Synthetic", asof="2026-01")
    session.relate("length_m", "length_cm")
    assert session.sample("length_m", n=10)["samples"]["main"] == [2.5] * 10
    session.relate("length_m", "length_cm + duration")
    assert "unit-mismatch" in {w["code"] for w in session.lint()["warnings"]}
    with pytest.raises(StantonError, match="convert"):
        session.sample("length_m", n=10)


def test_count_conversion(session):
    define(session, "boxes", "dozen")
    define(session, "items", "count")
    session.estimate("boxes", Distribution.from_point(3), reason="Fixture")
    session.relate("items", "boxes")
    assert session.sample("items", n=5)["samples"]["main"] == [36] * 5


def test_shared_factors_across_forks_and_old_runs_survive_edits(session):
    for node in ["inflation", "total"]:
        define(session, node)
    original = session.estimate("inflation", Distribution.from_interval(.8, 1.2), reason="Fixture")
    session.relate("total", "100 * inflation")
    session.fork("total", "left")
    session.fork("total", "right")
    session.relate("total", "200 * inflation", fork="right")
    session.merge("total", ["left", "right"], [.25, .75], reason="Synthetic weights")
    run = session.sample("total", n=10000, seed=123)
    assert np.array_equal(np.array(run["samples"]["left"]) * 2, run["samples"]["right"])
    assert np.mean(np.array(run["mixture_choices"]) == 1) == pytest.approx(.75, abs=.02)
    assert "divergent-strategies" in {w["code"] for w in run["warnings"]}
    session.estimate("inflation", Distribution.from_point(3), reason="Revised fixture")
    assert session.show("total", run_id=run["id"])["newer_working_revision"]
    audit = session.audit("total", run_id=run["id"])
    assert audit["estimates"]["inflation"]["id"] == original["estimate"]["id"]
    newer = session.sample("total", n=10)
    assert newer["samples"]["left"] == [300] * 10
    assert newer["samples"]["right"] == [600] * 10
    assert session.store.run(run["id"])["samples"] == run["samples"]
    assert session.validate()["ok"]


def test_bounds_warn_without_modifying_draws_and_condition_joint_rows(session):
    for node in ["x", "twice"]:
        define(session, node)
    session.estimate("x", Distribution("normal", (0, 1)), reason="Fixture")
    session.relate("twice", "2*x")
    raw = session.sample("twice", n=10000, seed=12)
    session.bound("x", lower=0, reason="Illustrative constraint")
    warned = session.sample("twice", n=10000, seed=12)
    assert raw["samples"] == warned["samples"]
    assert warned["bounds"][0]["violation_mass"] == pytest.approx(.5, abs=.02)
    session.bound("x", lower=0, reason="Condition on nonnegative x", clip=True)
    clipped = session.sample("twice", n=10000, seed=12)
    x = np.array(clipped["leaf_samples"]["x"])
    y = np.array(clipped["samples"]["main"])
    assert np.all(x > 0) and np.array_equal(y, 2 * x)
    assert x.mean() == pytest.approx(np.sqrt(2 / np.pi), abs=.025)
    assert clipped["bounds"][0]["violation_mass"] == pytest.approx(.5, abs=.02)
    assert clipped["unconditioned_summaries"]["main"]["min"] < 0
    session.bound("x", lower=100, reason="Impossible in this fixture", clip=True)
    with pytest.raises(StantonError, match="retained only"):
        session.sample("twice", n=100)


def test_cycles_missing_estimates_and_invalid_arithmetic(session):
    define(session, "x")
    define(session, "y")
    session.relate("y", "x + 1")
    with pytest.raises(StantonError, match="Cycle"):
        session.relate("x", "y + 1")
    assert "x" not in session.store.read()[0]["graphs"]["main"]
    with pytest.raises(StantonError, match="Missing estimates"):
        session.sample("y", n=10)
    session.estimate("x", Distribution.from_point(0), reason="Fixture")
    session.relate("y", "1 / x")
    with pytest.raises(StantonError, match="nonfinite"):
        session.sample("y", n=10)


@pytest.mark.parametrize("expression", ["__import__('os').system('echo danger')", "x[0]", "x.real", "[x for x in y]", "x ** y"])
def test_expression_language_rejects_python_execution(expression):
    with pytest.raises(StantonError):
        parse(expression)


def test_provenance_lint_and_abandonments(session):
    for node in ["a", "b", "total"]:
        define(session, node)
    session.assumption("macro", "Shared background assumption, no numeric effect specified")
    session.estimate("a", Distribution.from_point(1), assumes=["macro"], ancestry=["original"])
    session.estimate("b", Distribution.from_point(2), assumes=["macro"], ancestry=["original"])
    session.fork("total", "one")
    session.fork("total", "two")
    session.fork("total", "discarded")
    session.relate("total", "a", fork="one")
    session.relate("total", "b", fork="two")
    session.abandon("discarded", "No defensible reference class")
    session.note("total", "Hypothetical data")
    session.merge("total", ["one", "two"], [.5, .5], reason="Fixture")
    codes = {w["code"] for w in session.lint()["warnings"]}
    assert {"unsourced-leaf", "unresolved-dependence", "shared-ancestor"} <= codes
    audit = session.audit("total")
    assert audit["strategies"]["discarded"]["reason"] == "No defensible reference class"
    assert audit["notes"]["total"][0]["text"] == "Hypothetical data"


def test_stale_write_and_database_immutability(session):
    stale = Session(session.store.root, expected_revision=1)
    define(session, "x")
    with pytest.raises(StantonError, match="Expected revision"):
        define(stale, "y")
    assert "y" not in session.store.read()[0]["quantities"]
    with sqlite3.connect(session.store.path) as c:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            c.execute("UPDATE revisions SET operation='changed'")


def test_export_import_and_corrupt_archive_rejection(session, tmp_path):
    define(session, "x")
    session.estimate("x", Distribution.from_point(5), reason="Fixture")
    run = session.sample("x", n=25)
    archive = tmp_path / "saved.stanton.gz"
    session.save(archive)
    restored = Session(tmp_path / "restored")
    restored.load(archive)
    assert restored.store.read() == session.store.read()
    assert restored.store.run(run["id"]) == run
    assert restored.validate()["ok"]
    second_archive = tmp_path / "roundtrip.stanton.gz"
    restored.save(second_archive)
    assert second_archive.read_bytes() == archive.read_bytes()
    with pytest.raises(StantonError, match="uninitialized"):
        restored.load(archive)
    with pytest.raises(FileExistsError):
        session.save(archive)
    payload = json.loads(gzip.decompress(archive.read_bytes()))
    payload["data"]["runs"][0]["samples"]["main"][0] = 999
    payload["sha256"] = digest(payload["data"])
    corrupt = tmp_path / "corrupt.gz"
    corrupt.write_bytes(gzip.compress(canonical(payload).encode()))
    invalid = Session(tmp_path / "invalid")
    with pytest.raises(StantonError, match="summary"):
        invalid.load(corrupt)
    assert not invalid.store.path.exists()


def test_source_cutoff_and_space_lint(tmp_path):
    s = Session.create(tmp_path / "dated", asof="2020-06-01")
    define(s, "profit", space="log")
    s.estimate("profit", Distribution.from_interval(-1, 1, shape="normal"), reason="Fixture", asof="2021")
    assert {"future-leak", "support-crosses-zero"} <= {w["code"] for w in s.lint()["warnings"]}


def test_next_inspects_current_result_instead_of_resampling(session):
    from stanton.guidance import next_actions
    define(session, "x", status="target")
    session.estimate("x", Distribution.from_point(5), reason="Fixture")
    assert "sample" in {item["kind"] for item in next_actions(session)["next_actions"]}
    session.sample("x", n=10)
    kinds = {item["kind"] for item in next_actions(session)["next_actions"]}
    assert "sample" not in kinds and "inspect_result" in kinds


def test_open_positive_support_does_not_warn_about_zero(session):
    define(session, "positive", space="log")
    session.estimate("positive", Distribution.from_interval(1, 2), reason="Fixture")
    assert "support-crosses-zero" not in {w["code"] for w in session.lint()["warnings"]}
    session.estimate("positive", Distribution.from_interval(.1, .9, shape="logitnormal"), reason="Fixture")
    assert "support-crosses-zero" not in {w["code"] for w in session.lint()["warnings"]}
    session.estimate("positive", Distribution.from_point(0), reason="Fixture")
    assert "support-crosses-zero" in {w["code"] for w in session.lint()["warnings"]}
