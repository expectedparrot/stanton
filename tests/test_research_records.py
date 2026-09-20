import gzip
import json

import numpy as np
import pytest

from stanton import Distribution, Session, StantonError
from stanton.common import digest
from stanton.guidance import next_actions
from stanton.reports import report_context, reported_summary
from stanton.research_records import numerical_inputs


def model(tmp_path):
    s = Session.create(tmp_path / "project")
    s.define("population", units="count", definition="Synthetic unique firms", space="linear")
    s.define("rate", units="dimensionless", definition="Synthetic eligible share", space="logit")
    # Intentionally omit status target to match the field session's definition.
    s.define("total", units="count", definition="Synthetic firms with forms", space="linear")
    s.estimate("population", Distribution.from_point(100), source="Synthetic census")
    s.estimate("rate", Distribution.from_interval(.4, .6, shape="logitnormal"), reason="Synthetic bounded prior")
    s.relate("total", "population * rate")
    baseline = s.sample("total", n=20)
    s.estimate("rate", Distribution.from_point(.9), reason="Synthetic high-share sensitivity")
    variation = s.sample("total", n=20)
    s.estimate("rate", Distribution.from_interval(.4, .6, shape="logitnormal"), reason="Restore baseline")
    s.test_comparison = {"baseline_run": baseline["id"], "variation_run": variation["id"], "reason": "Stress the share at .9"}
    return s


def document(s, run_id=None, status="reviewed"):
    d = s.research_template("total", run_id=run_id)
    d.update(status=status, scope="Synthetic fixture: unique firms, not directory listings.",
             scope_details={"population": "Synthetic unique firms", "geography": "United States", "counting_unit": "count",
                            "inclusions": "Paid commercial firms", "exclusions": "Free accounts, education, government, nonprofits",
                            "interpretation": "US headquartered, not any US office",
                            "reference_period": {"start": "2026-01-01", "end": "2026-12-31"}},
             searches=[{"query": "Synthetic register", "outcome": "Exact population count available in fixture."}],
             sources=[{"id": "register", "reference": "Synthetic fixture, not real evidence", "claim": "100 firms",
                       "population": "Synthetic unique firms", "target_mapping": "Same population; modeled form share is judgment.",
                       "method": "Synthetic complete register", "limitations": "No empirical generalization",
                       "publication_date": "Not applicable: synthetic", "observation_period": "Synthetic period",
                       "accessed_at": "2026-09-20", "applies_to": ["population"], "ancestry": ["fixture"],
                       "observation_window": {"start": "2026-01-01", "end": "2026-12-31"},
                       "temporal_status": "aligned", "temporal_mapping": "Same synthetic period"}],
             reconciliation="Fixture has no competing measured claims; rate is labeled judgment.",
             alternative_model="Complete synthetic register; no separately generated measurement in fixture.",
             dependence="Only one method in baseline; shares are judgment, not independent evidence.",
             uncertainty="Bounded rate prior; no empirical coverage claim.",
             sensitivity={"status": "performed", "comparisons": [s.test_comparison], "reason": "Stress the synthetic share"},
             stopping={"reason": "Synthetic demonstration complete; not an empirical finding.", "remaining_gaps": []})
    return d


def test_intervals_are_explicit_and_do_not_modify_saved_runs(tmp_path):
    summary = reported_summary(list(range(101)))
    assert [(i["coverage"], i["lower"], i["upper"]) for i in summary["intervals"]] == [(.8, 10, 90), (.9, 5, 95)]
    s = model(tmp_path)
    run = s.sample("total", n=100)
    before = digest(run)
    shown = s.show("total", coverages=(.95,))
    assert shown["forks"]["main"]["intervals"][0]["lower_percentile"] == 2.5
    assert digest(s.store.run(run["id"])) == before
    for invalid in ([], [0], [1], [.8, .8], [float("nan")]):
        with pytest.raises(StantonError):
            s.show("total", coverages=invalid)


def test_shadowed_anchor_and_stale_report_are_visible_and_block_old_review(tmp_path):
    s = model(tmp_path)
    run = s.sample("total", n=100)
    d = document(s)
    s.anchor("total", 40, source="Directory listing count (different population)", asof="2026-08-01")
    finding = next(f for f in s.lint()["warnings"] if f["code"] == "overridden-estimate")
    assert finding["node"] == "total" and finding["fork"] == "main"
    assert "lower bound" in finding["message"] and "bound" in finding["remedy"]
    context = report_context(s, "total", run["id"])
    assert context["summary"]["stale_run"]
    assert "stale-run" in {f["code"] for f in context["summary"]["warnings"]}
    with pytest.raises(StantonError, match="changed"):
        s.research_review("stale", d)
    # An ignored anchor must never silently replace the numerical output.
    fresh = s.sample("total", n=100)
    assert fresh["samples"] == run["samples"]
    d = document(s)
    s.research_review("unresolved", d)
    with pytest.raises(StantonError, match="every remaining warning"):
        s.report_issue("bad", review="unresolved")
    d["warning_dispositions"] = [{"warning_id": f["id"], "reason": "Kept as comparison evidence only; population mapping does not support a firm lower bound."}
                                  for f in d["available_findings"]]
    s.research_review("reconciled", d)
    issued = s.report_issue("answer", review="reconciled")["record"]
    assert issued["headline"]["median"] == np.median(run["samples"]["main"])
    assert issued["headline"]["median"] != 40


def test_rate_support_cannot_be_waived_even_for_provisional_issuance(tmp_path):
    s = model(tmp_path)
    s.estimate("rate", Distribution.from_interval(.8, .9), reason="Field-run regression: unbounded rate")
    run = s.sample("total", n=20000)
    d = document(s, status="provisional")
    d["warning_dispositions"] = [{"warning_id": f["id"], "reason": "Only rare draws exceed one"} for f in d["available_findings"]]
    s.research_review("bad_rate", d)
    with pytest.raises(StantonError, match="cannot be waived"):
        s.report_issue("bad", review="bad_rate")
    s.estimate("rate", Distribution.from_interval(.8, .9, shape="logitnormal"), reason="Correct support")
    fixed = s.sample("total", n=200)
    assert all(0 <= x <= 1 for x in fixed["leaf_samples"]["rate"])
    assert fixed["id"] != run["id"]
    s.research_review("fixed", document(s))
    assert s.report_issue("fixed_answer", review="fixed")["record"]["status"] == "reviewed"


def test_reviews_issue_immutable_computed_conclusions_and_bookkeeping_is_not_stale(tmp_path):
    s = model(tmp_path)
    run = s.sample("total", n=100)
    s.research_review("review", document(s))
    assert not s.show("total")["stale_run"]
    assert s.show("total")["newer_working_revision"]
    result = s.report_issue("answer", review="review", coverages=(.8, .9))["record"]
    assert result["forecast"]["run_sha256"] == digest(run)
    assert result["headline"]["median"] == np.median(run["samples"]["main"])
    assert result["headline"]["intervals"][0]["coverage"] == .8
    assert "sample" not in {a["kind"] for a in next_actions(s)["next_actions"]}
    assert next_actions(s)["next_actions"][0]["completion_status"] == "recorded"
    assert report_context(s, "total")["issued_reports"]["answer"] == result
    with pytest.raises(StantonError, match="immutable"):
        s.report_issue("answer", review="review")
    s.note("total", "New evidence after issuance, requiring reconciliation")
    assert not s.research_show("answer", issued=True)["current_basis"]
    assert s.research_show("answer", issued=True)["record"] == result
    with pytest.raises(StantonError, match="changed"):
        s.report_issue("outdated", review="review")
    assert s.validate()["ok"]


def test_material_gaps_and_warnings_remain_visible_in_provisional_report(tmp_path):
    s = model(tmp_path)
    s.anchor("total", 45, source="Comparison only", asof="2026")
    s.sample("total", n=100)
    d = document(s)
    d["stopping"]["remaining_gaps"] = ["Representative rate measurement not yet collected"]
    with pytest.raises(StantonError, match="provisional"):
        s.research_review("false_complete", d)
    d["status"] = "provisional"
    s.research_review("interim", d)
    result = s.report_issue("interim_answer", review="interim")["record"]
    assert result["status"] == "provisional"
    assert result["remaining_gaps"] == d["stopping"]["remaining_gaps"]
    assert {f["code"] for f in result["unresolved_findings"]} == {"overridden-estimate"}


def test_sensitivity_requires_changed_inputs_and_records_actual_effect(tmp_path):
    s = model(tmp_path)
    a = s.sample("total", n=100, seed=0)
    b = s.sample("total", n=200, seed=1)
    d = document(s)
    d["sensitivity"] = {"comparisons": [{"baseline_run": a["id"], "variation_run": b["id"], "reason": "Attempted placebo"}], "status": "performed", "reason": "Vary a consequential input"}
    with pytest.raises(StantonError, match="changed numerical inputs"):
        s.research_review("placebo", d)
    s.estimate("rate", Distribution.from_point(.9), reason="High rate sensitivity")
    b = s.sample("total", n=100)
    s.estimate("rate", Distribution.from_interval(.4, .6, shape="logitnormal"), reason="Restore intended baseline")
    final = s.sample("total", n=100)
    d["run_id"] = final["id"]
    d["sensitivity"]["comparisons"][0].update(variation_run=b["id"], reason="Increase eligible share to .9")
    result = s.research_review("tested", d)["record"]
    sensitivity = result["sensitivity_results"][0]
    assert sensitivity["changed_components"] == ["marginals"]
    assert sensitivity["results"]["strategy:main"]["variation"]["median"] == 90
    assert sensitivity["results"]["strategy:main"]["median_change"] == pytest.approx(90 - np.median(a["samples"]["main"]))
    assert s.validate()["ok"]


def test_provenance_rewrite_bound_draws_and_unrelated_inputs_are_not_sensitivity(tmp_path):
    s = model(tmp_path)
    s.bound("total", lower=45, reason="Synthetic bound")
    a = s.sample("total", n=100)
    frozen = s.store.read()[0]
    s.relate("total", "population * rate")
    s.estimate("rate", Distribution.from_interval(.4, .6, shape="logitnormal"), reason="Changed provenance only")
    s.define("unrelated", units="count", definition="Unused variable", space="linear")
    s.estimate("unrelated", Distribution.from_point(42), reason="Unused")
    b = s.sample("total", n=200, seed=1)
    assert numerical_inputs(a, frozen) == numerical_inputs(b, s.store.read()[0])
    d = document(s)
    d["sensitivity"] = {"comparisons": [{"baseline_run": a["id"], "variation_run": b["id"], "reason": "Provenance only"}], "status": "performed", "reason": "Vary a consequential input"}
    with pytest.raises(StantonError, match="changed numerical inputs"):
        s.research_review("not_sensitivity", d)


def test_dependence_detects_shared_leaves_sources_and_ancestry(tmp_path):
    s = model(tmp_path)
    s.fork("total", "topdown", reason="Restatement shares the same population and rate")
    s.merge("total", ["main", "topdown"], [.6, .4], reason="Synthetic mixture")
    s.sample("total", n=100)
    d = document(s)
    record = s.research_review("dependent", d)["record"]
    overlap = record["dependency_overlap"][0]
    assert overlap["shared_leaves"] == ["population", "rate"]
    assert overlap["shared_source_ids"] == ["register"]
    assert overlap["shared_ancestry"] == ["fixture"]
    d["warning_dispositions"] = [{"warning_id": f["id"], "reason": "Shared evidence; no independent corroboration claim."} for f in record["findings"]]
    s.research_review("acknowledged", d)
    with pytest.raises(StantonError, match="Choose --method"):
        s.report_issue("ambiguous", review="acknowledged")
    issued = s.report_issue("mixture_answer", review="acknowledged", method="mixture")["record"]
    assert set(issued["strategies"]) == {"strategy:main", "strategy:topdown", "mixture"}
    assert s.validate()["ok"]


@pytest.mark.parametrize("change", ["headline", "review_binding", "sensitivity", "rewrite", "remove", "presentation"])
def test_archives_roundtrip_and_reject_resigned_research_tampering(tmp_path, change):
    s = model(tmp_path)
    a = s.sample("total", n=25)
    s.estimate("rate", Distribution.from_point(.9), reason="Sensitivity")
    b = s.sample("total", n=25)
    d = document(s)
    d["sensitivity"] = {"comparisons": [{"baseline_run": a["id"], "variation_run": b["id"], "reason": "Test change"}], "status": "performed", "reason": "Vary a consequential input"}
    s.research_review("review", d)
    s.report_issue("answer", review="review")
    s.note("total", "Later evidence preserves original artifacts")
    archive = tmp_path / "archive.gz"
    s.save(archive)
    restored = Session(tmp_path / "restored")
    restored.load(archive)
    assert restored.research_show("answer", issued=True) == s.research_show("answer", issued=True)
    assert restored.validate()["ok"]
    payload = json.loads(gzip.decompress(archive.read_bytes()))
    rows = payload["data"]["revisions"]
    for row in rows:
        state = row["body"]
        if change == "headline" and "answer" in state.get("issued_reports", {}):
            state["issued_reports"]["answer"]["headline"]["median"] = 123
        elif change == "presentation" and "answer" in state.get("issued_reports", {}):
            state["issued_reports"]["answer"]["presentation"]["headline"] = "Verified current estimate for all US organizations"
        elif change == "review_binding" and "review" in state.get("research_reviews", {}):
            state["research_reviews"]["review"]["run_sha256"] = "0" * 64
        elif change == "sensitivity" and "review" in state.get("research_reviews", {}):
            state["research_reviews"]["review"]["sensitivity_results"][0]["results"]["strategy:main"]["median_change"] = 999
        elif change == "rewrite" and row is rows[-1]:
            state["research_reviews"]["review"]["document"]["scope"] = "Rewritten after issuance"
        elif change == "remove" and row is rows[-1]:
            del state["issued_reports"]["answer"]
        row["sha256"] = digest(state)
    payload["sha256"] = digest(payload["data"])
    bad = tmp_path / "tampered.gz"
    bad.write_bytes(gzip.compress(json.dumps(payload).encode()))
    destination = Session(tmp_path / "rejected")
    with pytest.raises(StantonError):
        destination.load(bad)
    assert not destination.store.path.exists()


@pytest.mark.parametrize("field", ["target_mapping", "population", "reference", "ancestry", "applies_to"])
def test_source_mappings_are_required_and_failed_review_is_atomic(tmp_path, field):
    s = model(tmp_path)
    s.sample("total", n=10)
    d = document(s)
    del d["sources"][0][field]
    before = s.store.read()
    with pytest.raises(StantonError):
        s.research_review("invalid", d)
    assert s.store.read() == before


def test_cli_rate_defaults_review_and_issuance(tmp_path, capsys):
    from stanton.cli import main
    s = model(tmp_path)
    def cli(*args, ok=True):
        code = main([*args, "--project", str(s.store.root)])
        output = capsys.readouterr()
        assert code == (0 if ok else 1), output.err
        return json.loads(output.out if ok else output.err)
    cli("estimate", "rate", "--interval", ".8", ".9", "--reason", "Judgmental rate")
    assert s.store.read()[0]["estimates"]["rate"]["distribution"]["family"] == "logitnormal"
    cli("estimate", "rate", "--interval", "0", "1", "--reason", "Invalid open endpoints", ok=False)
    cli("estimate", "rate", "--value", "1", "--reason", "Exact certain rate")
    cli("sample", "total", "-n", "25")
    template_path = tmp_path / "review.json"
    cli("research", "template", "total", "--output", str(template_path))
    assert json.loads(template_path.read_text())["run_id"] == s.store.run()["id"]
    cli("research", "template", "total", "--output", str(template_path), ok=False)
    template_path.write_text(json.dumps(document(s)))
    cli("research", "review", "review", "--from", str(template_path))
    result = cli("report", "issue", "answer", "--review", "review", "--coverages", ".8,.9")["data"]["record"]
    assert result["headline"]["median"] == 100
    assert cli("report", "show", "answer")["data"]["record"] == result
    assert cli("research", "status", "total")["data"]["reviews"]["review"]["current_basis"]
    assert cli("schema", "research_review")["data"]
    assert main(["show", "total", "--format", "text", "--project", str(s.store.root)]) == 0
    text = capsys.readouterr().out
    assert "80% central model interval (p10–p90)" in text
    assert "90% central model interval (p5–p95)" in text


def test_unknown_sensitivity_run_and_revision_races_do_not_write_records(tmp_path):
    s = model(tmp_path)
    s.sample("total", n=20)
    d = document(s)
    d["sensitivity"] = {"comparisons": [{"baseline_run": "missing", "variation_run": d["run_id"], "reason": "Invalid reference"}], "status": "performed", "reason": "Vary a consequential input"}
    before = s.store.read()
    with pytest.raises(StantonError):
        s.research_review("missing", d)
    stale = Session(s.store.root, expected_revision=before[1] - 1)
    with pytest.raises(StantonError, match="Expected revision"):
        stale.research_review("racing", document(s))
    assert s.store.read() == before


def test_missing_sensitivity_is_a_gap_that_dispositions_cannot_waive(tmp_path):
    s = model(tmp_path)
    s.sample("total", n=100)
    d = document(s)
    d["sensitivity"] = {"status": "not_performed", "comparisons": [], "reason": "Compared two methods instead of testing assumptions"}
    before = s.store.read()
    preview = s.research_check(d)
    assert s.store.read() == before
    gap = next(f for f in preview["warnings"] if f["code"] == "sensitivity-not-performed")
    d["warning_dispositions"] = [{"warning_id": gap["id"], "reason": "We acknowledge the omission"}]
    s.research_review("unperformed", d)
    with pytest.raises(StantonError, match="requires provisional"):
        s.report_issue("cannot_waive", review="unperformed")
    d["status"] = "provisional"
    s.research_review("interim", d)
    issued = s.report_issue("interim", review="interim")["record"]
    assert issued["research_gaps"][0]["code"] == "sensitivity-not-performed"
    assert "not been stress-tested" in issued["presentation"]["limitations"][0]
    assert "sensitivity-not-performed" in {w["code"] for w in s.research_show("interim", issued=True)["warnings"]}


def test_uncertain_model_cannot_use_not_applicable_escape_clause(tmp_path):
    s = model(tmp_path)
    s.sample("total", n=1)
    d = document(s, status="provisional")
    d["sensitivity"] = {"status": "not_applicable", "comparisons": [], "reason": "Monte Carlo already captures uncertainty"}
    with pytest.raises(StantonError, match="not inapplicable"):
        s.research_review("escape", d)
    s.estimate("rate", Distribution.from_point(.5), reason="Deterministic fixture")
    s.sample("total", n=10)
    d["run_id"] = s.store.run()["id"]
    d["sensitivity"]["reason"] = "Complete deterministic fixture, with no uncertain inputs"
    assert s.research_check(d)["review"]["findings"][0]["code"] == "sensitivity-not-applicable"


def test_ratio_conflict_and_unresolved_explanation_survive_issuance(tmp_path):
    s = model(tmp_path)
    s.sample("total", n=20)
    d = document(s, status="provisional")
    d["numeric_checks"] = [{"id": "us_share", "source_id": "register", "numerator": 41009, "denominator": 82255,
                            "reported_ratio": .6191, "denominator_population": "All reported global detections",
                            "explanation": "Geography percentage may use a smaller population; not verified"}]
    d["discrepancies"] = [{"id": "population", "claim": "Global detections do not establish a US commercial lower bound",
                           "source_ids": ["register"], "status": "unresolved", "explanation": "May include nonprofits and foreign firms"}]
    preview = s.research_check(d)["review"]
    mismatch = next(f for f in preview["findings"] if f["code"] == "source-ratio-mismatch")
    assert mismatch["calculated_ratio"] == pytest.approx(.498559358)
    d["warning_dispositions"] = [{"warning_id": f["id"], "reason": "Disclosed as unresolved"} for f in preview["findings"]]
    s.research_review("sources", d)
    issued = s.report_issue("sources_answer", review="sources")["record"]
    assert len(issued["research_gaps"]) == 2
    assert len(issued["presentation"]["limitations"]) == 2
    assert report_context(s, "total")["warnings"]
    d["discrepancies"][0]["status"] = "resolved"
    with pytest.raises(StantonError, match="Evidence resolving"):
        s.research_check(d)
    d["numeric_checks"][0]["tolerance"] = .2
    d["discrepancies"][0]["status"] = "unresolved"
    with pytest.raises(StantonError, match="tolerance"):
        s.research_check(d)


def test_scope_dates_and_unknown_temporal_mapping_are_visible(tmp_path):
    s = model(tmp_path)
    s.sample("total", n=20)
    d = document(s, status="provisional")
    d["scope_details"]["reference_period"] = {"start": "2025-01-01", "end": "2025-12-31"}
    with pytest.raises(StantonError, match="outside the target period"):
        s.research_check(d)
    d["sources"][0].update(temporal_status="unresolved", temporal_mapping="2026 detections may not represent 2025")
    s.research_review("dated", d)
    result = s.report_issue("dated", review="dated")["record"]
    assert "2025-01-01 to 2025-12-31" in result["presentation"]["headline"]
    assert "United States" in result["presentation"]["headline"]
    assert result["presentation"]["exclusions"] == d["scope_details"]["exclusions"]
    assert result["research_gaps"][0]["code"] == "unresolved-source-period"
    d["sources"][0].update(observation_window=None, temporal_status="aligned")
    with pytest.raises(StantonError, match="Unknown observation"):
        s.research_check(d)
    d["sources"][0]["temporal_status"] = "adjusted"
    with pytest.raises(StantonError, match="Evidence supporting"):
        s.research_check(d)


def test_conceptual_input_dependency_detected_without_shared_model_leaves(tmp_path):
    s = model(tmp_path)
    for name, value in [("detections", 300), ("correction", 3)]:
        s.define(name, units="dimensionless", definition="Synthetic " + name)
        s.estimate(name, Distribution.from_point(value), reason="Synthetic")
    s.fork("total", "crawl", reason="Alternative route")
    s.relate("total", "detections / correction", fork="crawl")
    s.merge("total", ["main", "crawl"], [.6, .4], reason="Synthetic mixture")
    s.sample("total", n=20)
    d = document(s, status="provisional")
    d["input_dependencies"] = [{"quantity": "correction", "depends_on": ["population"], "reason": "Correction calibrated using the official population total"}]
    record = s.research_review("circular", d)["record"]
    overlap = record["dependency_overlap"][0]
    assert not overlap["shared_leaves"]
    assert overlap["shared_source_ids"] == ["register"]
    assert "population" in overlap["shared_evidence_quantities"]
    result = s.report_issue("circular", review="circular", method="strategy:main")["record"]
    assert result["dependency_overlap"] == record["dependency_overlap"]
    assert "shared-strategy-evidence" in {f["code"] for f in result["findings"]}


def test_legacy_review_and_issuance_remain_immutable_but_cannot_issue_anew(tmp_path):
    from stanton.common import now
    from stanton.research_records import LEGACY_ENGINE, issuance_data, review_data
    s = model(tmp_path)
    s.sample("total", n=20)
    d = document(s, status="provisional")
    for key in ("schema_version", "scope_details", "numeric_checks", "discrepancies", "input_dependencies"):
        d.pop(key)
    d["sensitivity"] = {"comparisons": [], "not_applicable_reason": "Legacy rationale"}
    state, revision = s.store.read()
    created = now()
    data = review_data(d, state, revision, s.store.run, lambda r: s.store.read(r)[0], created, engine=LEGACY_ENGINE)
    s._research_record("research_reviews", "old_review", data, state, created)
    state, revision = s.store.read()
    data = issuance_data(state, revision, "old_review", s.store.run, lambda r: s.store.read(r)[0], engine=LEGACY_ENGINE)
    original = s._research_record("issued_reports", "old_answer", data, state, now())["record"]
    assert s.validate()["ok"]
    assert s.research_show("old_answer", issued=True)["record"] == original
    with pytest.raises(StantonError, match="predates"):
        s.report_issue("new_from_old", review="old_review")
    archive = tmp_path / "legacy.gz"
    s.save(archive)
    restored = Session(tmp_path / "restored")
    restored.load(archive)
    assert restored.research_show("old_answer", issued=True)["record"] == original
    assert {w["code"] for w in restored.research_show("old_answer", issued=True)["warnings"]} >= {"legacy-research-review", "sensitivity-not-performed", "provisional-result"}


def test_issued_presentation_preserves_fractional_headlines(tmp_path):
    s = model(tmp_path)
    s.estimate("population", Distribution.from_point(.001), reason="Small synthetic scale")
    s.sample("total", n=20)
    s.research_review("small", document(s))
    report = s.report_issue("small", review="small")["record"]
    assert f"{report['headline']['median']:,.6g}" in report["presentation"]["headline"]
    assert "estimate: 0 count" not in report["presentation"]["headline"]


@pytest.mark.parametrize("field", ["discrepancies", "numeric_checks", "input_dependencies"])
def test_malformed_research_entries_return_structured_errors(tmp_path, field):
    s = model(tmp_path)
    s.sample("total", n=10)
    d = document(s)
    d[field] = ["not an object"]
    with pytest.raises(StantonError, match="must be an object"):
        s.research_check(d)
