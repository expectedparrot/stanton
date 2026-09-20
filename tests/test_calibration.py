import gzip
import json
from copy import deepcopy

import numpy as np
import pytest

from stanton import Distribution, Session, StantonError
from stanton.calibration import fit_data, spread
from stanton.common import digest, now


@pytest.fixture
def bank(tmp_path):
    s = Session.create(tmp_path / "calibration")
    s.define("x", units="meter", definition="Synthetic error", space="linear", status="target")
    s.estimate("x", Distribution.from_samples([-1, 0, 1]), reason="Synthetic forecast")
    train, test = s.sample("x", n=300, seed=1), s.sample("x", n=30, seed=2)
    s.cohort_define("bank", [
        {"event": "a", "group": "a", "split": "train", "run_id": train["id"]},
        {"event": "b", "group": "b", "split": "test", "run_id": test["id"]},
    ], units="centimeter", reason="Fixed independent synthetic cases")
    s.resolve("x", 3, event="a", run_id=train["id"], units="meter", source="Fixture", observed_at=now())
    return s, train, test


def fit(s, name="v1", **kwargs):
    return s.calibration_fit(name, cohort="bank", method="strategy:main", reason="Synthetic grid fit",
                             scales=[.5, 1, 2, 4], **kwargs)["calibration"]


def test_grid_fit_matches_independent_pairwise_crps_and_preserves_raw(bank):
    s, train, test = bank
    artifact = fit(s)
    values = np.array(train["samples"]["main"]) * 100
    center = np.quantile(values, .5, method="inverted_cdf")
    scores = []
    for candidate in artifact["candidates"]:
        adjusted = center + candidate["scale"] * (values - center)
        loss = np.mean(abs(adjusted - 300)) - np.mean(abs(adjusted[:, None] - adjusted)) / 2
        assert candidate["mean_crps"] == pytest.approx(loss)
        scores.append(loss)
    assert artifact["scale"] == artifact["scales"][np.argmin(scores)]
    assert artifact["variance_multiplier"] == artifact["scale"] ** 2
    assert artifact["n_events"] == artifact["n_groups"] == 1
    assert [e["event"] for e in artifact["training_evidence"]] == ["a"]
    before = s.store.read()
    overlay = s.calibration_apply("v1", run_id=test["id"], reason="Explicit synthetic transfer")
    assert overlay["raw_samples"] == test["samples"]["main"]
    assert overlay["adjusted_samples"] == spread(overlay["raw_samples"], artifact["scale"]).tolist()
    assert overlay["sha256"] == digest({k: v for k, v in overlay.items() if k != "sha256"})
    assert s.store.run(train["id"]) == train and s.store.run(test["id"]) == test
    assert s.store.read() == before
    assert s.validate()["ok"]


def test_fitter_never_reads_test_runs_or_uses_test_outcomes(bank):
    s, train, test = bank
    state, revision = s.store.read()
    def only_train(run_id):
        assert run_id == train["id"]
        return train
    first = fit_data(state, revision, only_train, "bank", "strategy:main", [1, 2, 4], False)
    s.resolve("x", 100000, event="b", run_id=test["id"], units="meter", source="Extreme test evidence", observed_at=now())
    state, _ = s.store.read()
    second = fit_data(state, revision, only_train, "bank", "strategy:main", [1, 2, 4], False)
    assert first == second


def test_evaluation_pins_training_corrections_and_flags_test_timing(bank):
    s, train, test = bank
    fit(s)
    initial = s.calibration_evaluate("v1")
    assert initial["splits"]["test"]["unresolved"] == 1
    s.resolve("x", 2, event="b", run_id=test["id"], units="meter", source="Test outcome", observed_at=now())
    report = s.calibration_evaluate("v1")
    assert report["splits"]["test"]["n_events"] == 1
    assert report["splits"]["test"]["observations_before_fit"] == 0
    assert set(report["splits"]["test"]["matched_methods"]) == {"raw", "adjusted"}
    old = s.resolution_show("a")["resolution"]
    s.resolve("x", -100, event="a", run_id=train["id"], units="meter", source="Correction", observed_at=now(),
              replaces=old["id"], reason="Synthetic correction")
    assert s.calibration_evaluate("v1")["splits"]["train"] == report["splits"]["train"]
    assert s.calibration_evaluate("v1", revision=report["revision"]) == report
    fit(s, "v2")
    late = s.calibration_evaluate("v2")["splits"]["test"]
    assert late["observations_before_fit"] == late["evidence_before_fit"] == 1
    assert s.validate()["ok"]


@pytest.mark.parametrize("scales", [[], [2], [0, 1], [True, 2], [1, 1], [1, float("inf")]])
def test_invalid_scale_grids_are_atomic(bank, scales):
    s, _, _ = bank
    before = s.store.read()
    with pytest.raises(StantonError):
        s.calibration_fit("bad", cohort="bank", method="strategy:main", reason="Fixture", scales=scales)
    assert s.store.read() == before


def test_missing_method_duplicate_artifact_and_stale_revision_fail(bank):
    s, _, _ = bank
    with pytest.raises(StantonError, match="lacks selected method"):
        s.calibration_fit("bad", cohort="bank", method="mixture", reason="Fixture")
    stale = Session(s.store.root, expected_revision=s.store.read()[1])
    artifact = fit(s)
    with pytest.raises(StantonError, match="already exists"):
        fit(s)
    with pytest.raises(StantonError) as error:
        fit(stale, "stale")
    assert error.value.code == "stale_revision"
    assert s.calibration_show("v1")["calibration"] == artifact


def test_no_eligible_training_and_point_forecasts_are_rejected(bank):
    s, train, _ = bank
    state, revision = s.store.read()
    point = deepcopy(train)
    point["samples"]["main"] = [1] * point["n"]
    with pytest.raises(StantonError, match="only point"):
        fit_data(state, revision, lambda _: point, "bank", "strategy:main", [1, 2], False)
    state["resolutions"] = {}
    with pytest.raises(StantonError, match="No eligible"):
        fit_data(state, revision, s.store.run, "bank", "strategy:main", [1, 2], False)


def test_retrospective_opt_in_and_future_evidence_exclusion(bank):
    s, train, _ = bank
    old = s.resolution_show("a")["resolution"]
    correction = s.resolve("x", 3, event="a", run_id=train["id"], units="meter", source="Retrospective fixture",
                           observed_at="2000-01-01T00:00:00+00:00", replaces=old["id"], reason="Timing correction")["resolution"]
    with pytest.raises(StantonError, match="No eligible"):
        fit(s)
    assert fit(s, include_retrospective=True)["include_retrospective"]
    s.resolve("x", 3, event="a", run_id=train["id"], units="meter", source="Future fixture",
              observed_at="2999-01-01T00:00:00+00:00", replaces=correction["id"], reason="Timing correction")
    with pytest.raises(StantonError, match="No eligible"):
        fit(s, "future", include_retrospective=True)


def test_calibration_archive_replays_and_rejects_resigned_fit_tampering(bank, tmp_path):
    s, _, test = bank
    fit(s)
    s.survey_draft("ask", nodes=["x"])
    fit(s, "v2")
    assert not s.survey_show("ask")["stale"]
    archive = tmp_path / "calibration.gz"
    s.save(archive)
    restored = Session(tmp_path / "restored")
    restored.load(archive)
    assert restored.calibration_evaluate("v1") == s.calibration_evaluate("v1")
    assert restored.calibration_apply("v1", run_id=test["id"], reason="Fixture") == s.calibration_apply("v1", run_id=test["id"], reason="Fixture")
    payload = json.loads(gzip.decompress(archive.read_bytes()))
    for row in payload["data"]["revisions"]:
        for artifact in row["body"].get("calibrations", {}).values():
            artifact["scale"] = 1 if artifact["scale"] != 1 else 2
            artifact["variance_multiplier"] = artifact["scale"] ** 2
        row["sha256"] = digest(row["body"])
    payload["sha256"] = digest(payload["data"])
    bad = tmp_path / "bad.gz"
    bad.write_bytes(gzip.compress(json.dumps(payload).encode()))
    with pytest.raises(StantonError, match="Calibration fit"):
        Session(tmp_path / "bad_project").load(bad)
    assert not (tmp_path / "bad_project").exists()


def test_correcting_test_outcome_does_not_hide_prior_knowledge(bank):
    s, _, test = bank
    old = s.resolve("x", 2, event="b", run_id=test["id"], units="meter", source="Known before fit", observed_at=now())["resolution"]
    fit(s)
    s.resolve("x", 3, event="b", run_id=test["id"], units="meter", source="Later correction", observed_at=now(),
              replaces=old["id"], reason="Synthetic revised outcome")
    assert s.calibration_evaluate("v1")["splits"]["test"]["evidence_before_fit"] == 1


def test_application_reports_bound_violations_and_rejects_incompatible_units(bank):
    s, _, _ = bank
    artifact = fit(s)
    assert artifact["scale"] > 1
    s.bound("x", lower=-1, upper=1, reason="Synthetic bounded support", clip=True)
    run = s.sample("x", n=100)
    overlay = s.calibration_apply("v1", run_id=run["id"], reason="Check support after expansion")
    assert overlay["target_support"]["below"] + overlay["target_support"]["above"] > 0
    assert any(w["code"] == "adjusted-bound-violation" for w in overlay["warnings"])
    assert s.store.run(run["id"]) == run
    s.define("time", units="second", definition="Incompatible target", space="linear")
    s.estimate("time", Distribution.from_point(1), reason="Fixture")
    other = s.sample("time", n=10)
    with pytest.raises(StantonError):
        s.calibration_apply("v1", run_id=other["id"], reason="Wrong dimension")


def test_mixture_selection_and_explicit_decision_context(bank):
    s, _, _ = bank
    s.define("base", units="meter", definition="Base value", space="linear")
    s.estimate("base", Distribution.from_samples([1, 2, 3]), reason="Fixture")
    s.decision("size", options={"small": 1, "large": 2}, definition="Size")
    s.relate("x", "base*size")
    s.fork("x", "alternative")
    s.relate("x", "base*size+base", fork="alternative")
    s.merge("x", ["main", "alternative"], [.5, .5], reason="Fixture")
    run = s.sample("x", n=50)
    s.cohort_define("mixtures", [{"event": "c", "group": "c", "split": "train", "run_id": run["id"],
                                 "decisions": {"size": "small"}}], units="meter", reason="Fixture")
    s.resolve("x", 5, event="c", run_id=run["id"], units="meter", source="Fixture", observed_at=now(), decisions={"size": "small"})
    s.calibration_fit("mix", cohort="mixtures", method="mixture", reason="Fit one mixture context")
    with pytest.raises(StantonError, match="ambiguous"):
        s.calibration_apply("mix", run_id=run["id"], reason="Ambiguous choices")
    overlay = s.calibration_apply("mix", run_id=run["id"], reason="Explicit small context", decisions={"size": "small"})
    context = overlay["forecast"]["context_key"]
    assert overlay["raw_samples"] == run["mixtures"][context]["samples"]
    assert s.validate()["ok"]
