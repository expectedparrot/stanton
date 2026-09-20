import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from stanton import Session

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args, cwd):
    result = subprocess.run([sys.executable, "-m", "stanton", *args], cwd=cwd, text=True, capture_output=True, timeout=30)
    return result


def execute_walkthrough(path, tmp_path):
    text = path.read_text().split("<!-- walkthrough:start -->")[1].split("<!-- walkthrough:end -->")[0]
    blocks = re.findall(r"```bash\n(.*?)```", text, re.S)
    wrapper = "stanton() { " + shlex.quote(sys.executable) + " -m stanton \"$@\"; }\n"
    result = subprocess.run(["bash", "-e", "-c", wrapper + "\n".join(blocks)], cwd=tmp_path,
                            text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return result


def test_readme_walkthrough_in_fresh_processes(tmp_path):
    result = execute_walkthrough(ROOT / "README.md", tmp_path)
    assert "divergent-strategies" in result.stdout
    assert "bound-violation" in result.stdout
    assert (tmp_path / "report-context.json").exists()
    project = Session(tmp_path / "facility")
    restored = Session(tmp_path / "restored-facility")
    run = project.store.run(target="cost")
    assert restored.store.run(run["id"]) == run
    assert project.validate()["ok"]
    assert 120000 < run["summaries"]["extrapolation"]["quantiles"]["p50"] < 125000
    assert 225000 < run["summaries"]["costing"]["quantiles"]["p50"] < 233000
    assert project.audit("cost")["strategies"]["reference_class"]["status"] == "abandoned"


def test_conditional_walkthrough_in_fresh_processes(tmp_path):
    execute_walkthrough(ROOT / "docs/conditional-models.md", tmp_path)
    project = Session(tmp_path / "renovation")
    restored = Session(tmp_path / "restored-renovation")
    check = project.check(30000, "cost", definition="quoted")
    assert restored.check(30000, "cost", definition="quoted") == check
    result = check["results"]["main@quoted[finish=standard]"]
    assert result["verdict"] == "above_p95"
    assert result["predicate_flips"]["disposal"]["changes_verdict"]
    assert project.validate()["ok"]


def test_process_walkthrough_in_fresh_processes(tmp_path):
    execute_walkthrough(ROOT / "docs/paths-and-allocations.md", tmp_path)
    project = Session(tmp_path / "planning")
    restored = Session(tmp_path / "restored-planning")
    assert project.validate()["ok"] and restored.validate()["ok"]
    assert project.store.run(target="occupancy")["samples"]["main"] == [20] * 100
    for name, target, method, command in (
        ("revenue", "future", "series_show", "series"),
        ("spending", "allocated", "allocation_show", "allocation"),
    ):
        run = project.store.run(target=target)
        report = getattr(project, method)(name, run_id=run["id"])
        assert getattr(restored, method)(name, run_id=run["id"]) == report
        result = run_cli(command, "show", name, "--run", run["id"], "--project", "planning", cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["data"] == report
    assert report["max_conservation_error"] < 1e-9


def test_elicitation_walkthrough_in_fresh_processes(tmp_path):
    execute_walkthrough(ROOT / "docs/elicitation.md", tmp_path)
    project = Session(tmp_path / "roof")
    restored = Session(tmp_path / "restored-roof")
    assert project.validate()["ok"] and restored.validate()["ok"]
    assert project.survey_review("owner_input") == restored.survey_review("owner_input")
    review = project.survey_review("owner_input")
    assert len(review["responses"]) == 1 and all(p["status"] == "applied" for p in review["proposals"].values())
    run = project.store.run(target="cost")
    assert restored.store.run(run["id"]) == run
    result = run_cli("survey", "ingest", "owner_input", "--from", "responses.json", "--source", "Duplicate",
                     "--project", "roof", cwd=tmp_path)
    assert result.returncode == 1 and result.stdout == ""
    assert json.loads(result.stderr)["errors"][0]["code"] == "stale_survey"


def test_calibration_walkthrough_in_fresh_processes(tmp_path):
    execute_walkthrough(ROOT / "docs/calibration.md", tmp_path)
    project = Session(tmp_path / "calibration")
    restored = Session(tmp_path / "restored-calibration")
    report = project.calibration_evaluate("spread_v1")
    assert report == restored.calibration_evaluate("spread_v1")
    assert report["splits"]["train"]["n_events"] == report["splits"]["test"]["n_events"] == 1
    assert report["splits"]["test"]["observations_before_fit"] == 0
    assert json.loads((tmp_path / "comparison.json").read_text())["data"] == report
    overlay = json.loads((tmp_path / "adjusted.json").read_text())["data"]
    assert project.store.run(overlay["forecast"]["run_id"])["samples"]["main"] == overlay["raw_samples"]
    assert json.loads((tmp_path / "unresolved.json").read_text())["data"]["splits"]["test"]["unresolved"] == 1
    assert project.validate()["ok"] and restored.validate()["ok"]


def test_outcome_walkthrough_in_fresh_processes(tmp_path):
    execute_walkthrough(ROOT / "docs/outcome-scoring.md", tmp_path)
    project = Session(tmp_path / "evaluation")
    restored = Session(tmp_path / "restored-evaluation")
    report = project.cohort_evaluate("roofs")
    assert report == restored.cohort_evaluate("roofs")
    assert report["splits"]["train"]["n_events"] == report["splits"]["test"]["n_events"] == 1
    assert report["splits"]["test"]["unresolved"] == 1
    assert json.loads((tmp_path / "evaluation-report.json").read_text())["data"] == report
    unresolved = json.loads((tmp_path / "unresolved.json").read_text())["data"]
    assert unresolved["splits"]["test"]["n_events"] == 0
    assert unresolved["splits"]["test"]["unresolved"] == 2
    assert project.validate()["ok"]


@pytest.mark.parametrize("args", [
    ("define", "x", "--units", "USD", "--def", "Fixture", "--when", "included=maybe"),
    ("decision", "define", "choice", "--options", "x=1,x=2", "--def", "Fixture"),
    ("definition", "define", "scope", "--target", "x", "--measure", "spend", "--predicates", "x=unknown"),
])
def test_bad_branch_arguments_are_structured_errors(args, tmp_path):
    Session.create(tmp_path / "project")
    result = run_cli(*args, "--project", str(tmp_path / "project"), cwd=tmp_path)
    assert result.returncode == 1 and result.stdout == ""
    assert json.loads(result.stderr)["status"] == "error"


def test_structured_errors_and_discovery_without_project(tmp_path):
    result = run_cli("bogus", cwd=tmp_path)
    assert result.returncode == 1 and result.stdout == ""
    assert json.loads(result.stderr)["errors"][0]["code"] == "invalid_arguments"
    for args in [("guide",), ("schema", "estimate"), ("version",)]:
        result = run_cli(*args, cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["status"] == "ok"


def test_project_flag_placement_and_estimate_file(tmp_path):
    result = run_cli("--project", "p", "init", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    result = run_cli("--project", "p", "define", "x", "--units", "dimensionless", "--def", "Fixture", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    payload = {"quantity": "x", "distribution": {"family": "point", "parameters": [3]}, "reason": "Fixture"}
    (tmp_path / "estimate.json").write_text(json.dumps(payload))
    result = run_cli("estimate", "--from", "estimate.json", "--project", "p", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    result = run_cli("sample", "x", "-n", "10", "--project", "p", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["data"]["forks"]["main"]["mean"] == 3


def test_research_review_walkthrough_in_fresh_processes(tmp_path):
    execute_walkthrough(ROOT / "docs/research-review.md", tmp_path)
    project = Session(tmp_path / "reviewed-study")
    restored = Session(tmp_path / "restored-reviewed-study")
    assert project.validate()["ok"] and restored.validate()["ok"]
    issued = project.research_show("synthetic_answer", issued=True)
    assert issued == restored.research_show("synthetic_answer", issued=True)
    assert issued["current_basis"]
    review = project.research_show("synthetic_review")["record"]
    assert review["sensitivity_results"][0]["results"]["strategy:main"]["variation"]["median"] == 80
    assert issued["record"]["headline"]["intervals"][0]["coverage"] == .8


@pytest.mark.parametrize("args", [
    ["relate", "total", "--fork", "alternate", "=", "x * y"],
    ["relate", "--fork", "alternate", "total", "=", "x * y"],
    ["relate", "total", "=", "x * y", "--fork", "alternate"],
    ["relate", "total", "--fork", "alternate", "x * y", "--project", "study"],
])
def test_relate_options_can_precede_follow_or_interrupt_positionals(args):
    # Run on Python 3.11 as well as 3.12: ordinary argparse behavior differs.
    from stanton.cli import parser
    parsed = parser().parse_args(args)
    assert parsed.target == "total" and parsed.fork == "alternate"
    assert " ".join(parsed.expression).removeprefix("= ") == "x * y"


def test_field_session_errors_give_corrective_commands(tmp_path, capsys):
    from stanton.cli import main
    for args, text in [
        (["anchor", "x", "--value", "100", "--source", "Fixture"], "--asof 2026-01-01"),
        (["note", "x", "--text", "Finding"], "stanton note TARGET"),
        (["report", "issue", "answer", "--review", "review", "--status", "provisional"], "status comes from review.json"),
    ]:
        assert main(args) == 1
        assert text in json.loads(capsys.readouterr().err)["errors"][0]["message"]
