"""Bounded, factual report material; narration and source checking belong to the caller."""

import numpy as np

from .common import require
from .lint import lint
from .research import research_workflow
from .sampling import summary
from .schemas import graph_order
from .scoring import coverage_levels


def reported_summary(values, quantiles=(5, 25, 50, 75, 95), coverages=(.8, .9)):
    """Presentation intervals, leaving historical numerical run schemas unchanged."""
    intervals = []
    for coverage in coverage_levels(coverages):
        lower_p = round((1 - coverage) * 50, 12)
        upper_p = 100 - lower_p
        lower, upper = np.percentile(values, [lower_p, upper_p], method="linear")
        intervals.append({"coverage": coverage, "lower_percentile": lower_p, "upper_percentile": upper_p,
                          "lower": float(lower), "upper": float(upper), "kind": "central_model_interval",
                          "quantile_method": "linear"})
    return {**summary(values, quantiles), "median": float(np.percentile(values, 50)), "intervals": intervals}


def show(run, working_revision, quantiles=(5, 25, 50, 75, 95), coverages=(.8, .9)):
    data = {"run_id": run["id"], "target": run["target"], "units": run["units"],
            "revision": run["revision"], "working_revision": working_revision,
            "newer_working_revision": working_revision != run["revision"],
            "n": run["n"], "seed": run["seed"], "engine": run["engine"], "state_sha256": run["state_sha256"],
            "forks": {f: reported_summary(values, quantiles, coverages) for f, values in run["samples"].items()},
            "merged": reported_summary(run["merged_samples"], quantiles, coverages) if run["merged_samples"] is not None else None,
            "merge": run["merge"], "bounds": run["bounds"], "attempted": run["attempted"],
            "unconditioned_forks": run["unconditioned_summaries"], "warnings": list(run["warnings"])}
    if run.get("schema_version") in {2, 3}:
        data.update(branches={key: {**branch, "summary": data["forks"][key]} for key, branch in run["branches"].items()},
                    mixtures={key: {"branches": mixture["branches"], "summary": reported_summary(mixture["samples"], quantiles, coverages)}
                              for key, mixture in run["mixtures"].items()}, scenario_frequencies=run["scenario_frequencies"],
                    conditioning=run["conditioning"])
    if run.get("schema_version") == 3:
        data["processes"] = run["process_plan"]
    return data


def audit(state, revision, target, run=None):
    require(target in state["quantities"], "Unknown target.", "not_found")
    forks = run["forks"] if run else [f for f, v in state["strategies"].items()
                                      if f == "main" or v.get("target") == target]
    dependencies = {f: graph_order(state, f, target) for f in forks}
    nodes = sorted({node for order in dependencies.values() for node in order})
    series_names = {state["quantities"][node]["process"]["name"] for node in nodes
                    if state["quantities"][node].get("process", {}).get("kind") == "series"}
    allocations = {state["quantities"][node]["process"]["name"] for node in nodes
                   if state["quantities"][node].get("process", {}).get("kind") == "allocation"}
    nodes = sorted(set(nodes) | {state["series"][key]["growth"] for key in series_names if state["series"][key]["kind"] == "path"})
    conditional = {node: values for node, values in state.get("conditional_estimates", {}).items() if node in nodes}
    all_estimates = [state["estimates"][node] for node in nodes if node in state["estimates"]]
    all_estimates += [estimate for values in conditional.values() for estimate in values.values()]
    assumptions = sorted({a for estimate in all_estimates for a in estimate["assumes"]})
    bridges = {key: record for key, record in state.get("bridges", {}).items() if key in nodes}
    definition_refs = {estimate["definition_id"] for estimate in all_estimates if estimate.get("definition_id")}
    definition_refs.update(record[direction] for record in bridges.values() for direction in ("from", "to"))
    definitions = {key: record for key, record in state.get("definitions", {}).items()
                   if record["target"] == target or key in definition_refs}
    scenario_groups = {state["scenarios"][scenario]["group"] for values in conditional.values() for scenario in values}
    scenarios = {key: record for key, record in state.get("scenarios", {}).items() if record["group"] in scenario_groups}
    elicited = [e["elicitation"] for e in all_estimates if e.get("elicitation")]
    elicited += [record["elicitation"] for key, record in state.get("decisions", {}).items() if key in nodes and record.get("elicitation")]
    surveys = {}
    for reference in elicited:
        key = reference["survey"]
        record = state["surveys"][key]
        entry = surveys.setdefault(key, {"instrument": record["instrument"], "responses": {}, "proposals": {}})
        entry["responses"][reference["response_id"]] = record["responses"][reference["response_id"]]
        entry["proposals"][reference["proposal_id"]] = record["proposals"][reference["proposal_id"]]
    return {"target": target, "revision": revision, "run_id": run["id"] if run else None,
            "context": state["context"], "quantities": {node: state["quantities"][node] for node in nodes},
            "estimates": {node: state["estimates"][node] for node in nodes if node in state["estimates"]},
            "relations": {f: {node: state["graphs"][f][node] for node in dependencies[f] if node in state["graphs"][f]} for f in forks},
            "assumptions": {a: state["assumptions"][a] for a in assumptions},
            "notes": {key: value for key, value in state["notes"].items()
                      if key in nodes or key in assumptions or key in forks or key in definitions or key in scenarios
                      or key in series_names or key in allocations},
            "series": {key: state["series"][key] for key in series_names},
            "allocations": {key: state["allocations"][key] for key in allocations},
            "conditional_estimates": conditional, "scenarios": scenarios,
            "scenario_groups": state.get("scenario_groups", {}), "definitions": definitions,
            "decisions": {key: record for key, record in state.get("decisions", {}).items() if key in nodes},
            "bridges": bridges,
            "elicitation": surveys,
            "branches": run.get("branches", {}) if run else {},
            "strategies": {key: value for key, value in state["strategies"].items()
                           if key in forks or value.get("target") == target},
            "bounds": {key: value for key, value in state["bounds"].items() if key in nodes},
            "merge": state["merges"].get(target), "warnings": run["warnings"] if run else lint(state)}


def report_context(session, target, run_id=None):
    state, _ = session.store.read()
    require(target not in state.get("issued_reports", {}) or target in state["quantities"],
            f"{target} is an issued report name. Use stanton report show {target}; report context expects the target quantity.", "wrong_report_identifier")
    run = session.store.run(run_id, target)
    result = session.show(target, run_id=run["id"])
    issued = {key: record for key, record in state.get("issued_reports", {}).items() if record["run_id"] == run["id"]}
    warnings = list(result["warnings"])
    from .research_checks import presentation
    for record in issued.values():
        warnings += presentation(record, state.get("research_reviews", {}).get(record["review"]))
    if not issued:
        warnings.append({"code": "unissued-result", "message": "Draft numerical context; record a research review and use report issue before presenting a completed conclusion."})
    return {"summary": result, "audit": session.audit(target, run_id=run["id"]),
            "publication_status": "historical_issued" if issued and result["stale_run"] else "issued" if issued else "draft",
            "warnings": warnings,
            "research_workflow": research_workflow(),
            "research_status": session.research_status(target, run_id=run["id"]),
            "research_reviews": {key: record for key, record in state.get("research_reviews", {}).items() if record["run_id"] == run["id"]},
            "issued_reports": issued,
            "instructions": ["Apply the attached agent research contract before final synthesis or a polished report. Review the study's RESEARCH.md and frozen target notes; this export does not assess research completion. If material work remains incomplete, disclose it and label the result provisional.",
                             "Use report issue to freeze a conclusion after research review. Until issuance, this context is draft material. Copy labeled central model intervals exactly: p5–p95 is 90%, p10–p90 is 80%. Never replace the computed headline with an unmodeled judgment; revise, sample, and review it.",
                             "Use the issued presentation with its scope and reference period, not an unqualified numerical headline. Include shared evidence, unperformed sensitivity, unresolved discrepancies, and provisional status even when a warning has a disposition.",
                             "Keep per-strategy results and disagreement visible.",
                             "Keep decision and definition branches separate; they have no probabilities or blended result.",
                             "Distinguish supplied sources, judgmental assumptions, and computed values.",
                             "These intervals describe this model; calibration and source truthfulness are not established.",
                             "Disclose truncation, unresolved dependence, and any newer working revision."]}
