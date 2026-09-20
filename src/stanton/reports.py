"""Bounded, factual report material; narration and source checking belong to the caller."""

from .common import require
from .lint import lint
from .research import research_workflow
from .sampling import summary
from .schemas import graph_order


def show(run, working_revision, quantiles=(5, 25, 50, 75, 95)):
    data = {"run_id": run["id"], "target": run["target"], "units": run["units"],
            "revision": run["revision"], "working_revision": working_revision,
            "newer_working_revision": working_revision != run["revision"],
            "n": run["n"], "seed": run["seed"], "engine": run["engine"], "state_sha256": run["state_sha256"],
            "forks": {f: summary(values, quantiles) for f, values in run["samples"].items()},
            "merged": summary(run["merged_samples"], quantiles) if run["merged_samples"] is not None else None,
            "merge": run["merge"], "bounds": run["bounds"], "attempted": run["attempted"],
            "unconditioned_forks": run["unconditioned_summaries"], "warnings": run["warnings"]}
    if run.get("schema_version") in {2, 3}:
        data.update(branches={key: {**branch, "summary": data["forks"][key]} for key, branch in run["branches"].items()},
                    mixtures={key: {"branches": mixture["branches"], "summary": summary(mixture["samples"], quantiles)}
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
    run = session.store.run(run_id, target)
    return {"summary": session.show(target, run_id=run["id"]), "audit": session.audit(target, run_id=run["id"]),
            "research_workflow": research_workflow(),
            "instructions": ["Apply the attached agent research contract before final synthesis or a polished report. Review the study's RESEARCH.md and frozen target notes; this export does not assess research completion. If material work remains incomplete, disclose it and label the result provisional.",
                             "Keep per-strategy results and disagreement visible.",
                             "Keep decision and definition branches separate; they have no probabilities or blended result.",
                             "Distinguish supplied sources, judgmental assumptions, and computed values.",
                             "These intervals describe this model; calibration and source truthfulness are not established.",
                             "Disclose truncation, unresolved dependence, and any newer working revision."]}
