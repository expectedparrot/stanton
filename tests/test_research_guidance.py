import json
import subprocess
import sys

from stanton import Distribution, Session
from stanton.guidance import next_actions
from stanton.reports import report_context


def cli(*args, cwd):
    result = subprocess.run([sys.executable, "-m", "stanton", *args], cwd=cwd,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["data"]


def test_installed_agent_surfaces_share_contract_without_certifying_research(tmp_path):
    # Guide discovery must work before creating a project.
    guide = cli("guide", cwd=tmp_path)
    contract = guide["research_workflow"]
    assert contract["default_effort"] == "high"
    assert contract["completion_status"] == "not_assessed"
    assert guide["guide"].index("AGENT RESEARCH CONTRACT") < guide["guide"].index("COMMAND REFERENCE")
    assert {s["id"] for s in contract["steps"]} == {
        "scope", "source_search", "reconcile", "alternative_model", "stress_test", "synthesis_gate"}
    s = Session.create(tmp_path / "study")
    s.define("count", units="count", definition="Empirical activity count", status="target")
    s.estimate("count", Distribution.from_point(11000), source="One supplied number", reason="Initial lookup")
    run = s.sample("count", n=10)
    assert s.validate()["ok"]
    next_result = cli("next", "--project", str(s.store.root), cwd=tmp_path)
    report = cli("report", "context", "count", "--project", str(s.store.root), cwd=tmp_path)
    assert next_result["research_workflow"] == report["research_workflow"] == contract
    review = next_result["next_actions"][0]
    assert review["kind"] == "research_review" and review["targets"] == ["count"]
    assert cli(*review["argv"][1:], cwd=tmp_path)["research_workflow"] == contract
    assert any(a["kind"] == "inspect_result" for a in next_result["next_actions"])
    assert report["summary"]["run_id"] == run["id"]
    assert any("provisional" in instruction for instruction in report["instructions"])


def test_research_reminder_does_not_suppress_model_gaps_or_mutate_state(tmp_path):
    s = Session.create(tmp_path / "study")
    before = s.store.read()
    assert {a["kind"] for a in next_actions(s)["next_actions"]} == {"research_review", "define_target"}
    assert s.store.read() == before
    s.define("unknown", units="count", definition="Unresearched count", status="target")
    result = next_actions(s)
    assert {a["kind"] for a in result["next_actions"]} >= {"research_review", "complete_model"}
    # A caller editing its response cannot mark later guidance as assessed.
    result["research_workflow"]["completion_status"] = "complete"
    assert next_actions(s)["research_workflow"]["completion_status"] == "not_assessed"


def test_research_summary_is_frozen_with_run_and_survives_archive(tmp_path):
    s = Session.create(tmp_path / "study")
    s.define("count", units="count", definition="Empirical activity count", status="target")
    s.estimate("count", Distribution.from_point(11000), reason="Initial baseline")
    review = "Provisional: only one underlying count; suspicious zeros unresolved. Alternative demand inputs unavailable. No validated interval. Stopping because user requested this interim baseline; next obtain operator logs."
    s.note("count", review)
    run = s.sample("count", n=10)
    s.note("count", "Later investigation; this note must not rewrite the prior review.")
    archive = tmp_path / "study.gz"
    s.save(archive)
    restored = Session(tmp_path / "restored")
    restored.load(archive)
    context = report_context(restored, "count", run["id"])
    assert [n["text"] for n in context["audit"]["notes"]["count"]] == [review]
    assert context["research_workflow"]["completion_status"] == "not_assessed"
