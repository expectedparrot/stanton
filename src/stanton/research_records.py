"""Run-bound research records and reproducible issuance, not evidence certification."""

from copy import deepcopy
from itertools import combinations

from .common import digest, nonblank, require
from .elicitation import model_digest
from .lint import lint
from .reports import reported_summary
from .schemas import graph_order
from .scoring import forecast_binding, forecast_samples, timestamp

ENGINE = "stanton.research-review.v1"
HARD_ERRORS = {"support-outside-rate", "unit-mismatch", "incomplete-scenarios"}
SOURCE_FIELDS = ("id", "reference", "claim", "population", "target_mapping", "method", "limitations",
                 "publication_date", "observation_period", "accessed_at")


def evidence_digest(state):
    # Notes are evidence. Adding reviews, outcomes, or issuance records is bookkeeping.
    return digest({"model": model_digest(state), "notes": state["notes"]})


def run_findings(run, frozen):
    findings = {}
    for warning in [*run["warnings"], *lint(frozen)]:
        key = digest(warning)
        findings[key] = {"id": key, **warning, "blocks_issuance": warning["code"] in HARD_ERRORS}
    return list(findings.values())


def dependency_overlap(run, state, sources):
    orders = {fork: set(graph_order(state, fork, run["target"])) for fork in run["forks"]}
    for nodes in orders.values():
        for node in list(nodes):
            process = state["quantities"][node].get("process", {})
            if process.get("kind") == "series":
                series = state["series"][process["name"]]
                if series["kind"] == "path":
                    nodes.add(series["growth"])
    leaves = {fork: {n for n in nodes if n not in state["graphs"][fork] and not state["quantities"][n].get("process")}
              for fork, nodes in orders.items()}
    origins, references = {}, {}
    for fork, nodes in leaves.items():
        estimates = [state["estimates"][n] for n in nodes if n in state["estimates"]]
        estimates += [e for n in nodes for e in state.get("conditional_estimates", {}).get(n, {}).values()]
        origins[fork] = {a for e in estimates for a in e["ancestry"]}
        references[fork] = {s["id"] for s in sources if set(s["applies_to"]) & orders[fork]}
        origins[fork].update(a for s in sources if s["id"] in references[fork] for a in s["ancestry"])
    return [{"strategies": [a, b], "shared_leaves": sorted(leaves[a] & leaves[b]),
             "shared_ancestry": sorted(origins[a] & origins[b]),
             "shared_source_ids": sorted(references[a] & references[b]),
             "interpretation": "Detected overlap is not independent corroboration; absent overlap does not establish independence."}
            for a, b in combinations(sorted(leaves), 2)]


def review_template(run, state):
    return {"run_id": run["id"], "status": "provisional", "scope": "", "searches": [], "sources": [],
            "reconciliation": "", "alternative_model": "", "dependence": "", "uncertainty": "",
            "sensitivity": {"comparisons": [], "not_applicable_reason": ""},
            "stopping": {"reason": "", "remaining_gaps": []}, "warning_dispositions": [],
            "available_findings": run_findings(run, state)}


def validate_document(document, state):
    require(isinstance(document, dict), "Research review must be an object.")
    require(document.get("status") in {"reviewed", "provisional"}, "Review status must be reviewed or provisional.")
    for field in ("run_id", "scope", "reconciliation", "alternative_model", "dependence", "uncertainty"):
        nonblank(document.get(field), field)
    searches = document.get("searches")
    require(isinstance(searches, list), "Searches must be a list.")
    for search in searches:
        require(isinstance(search, dict), "Search must be an object.")
        for field in ("query", "outcome"):
            nonblank(search.get(field), "Search " + field)
    sources = document.get("sources")
    require(isinstance(sources, list), "Sources must be a list.")
    ids = set()
    for source in sources:
        require(isinstance(source, dict), "Source must be an object.")
        for field in SOURCE_FIELDS:
            nonblank(source.get(field), "Source " + field)
        require(source["id"] not in ids, "Source IDs must be unique.")
        ids.add(source["id"])
        require(isinstance(source.get("applies_to"), list) and source["applies_to"]
                and all(isinstance(n, str) and n in state["quantities"] for n in source["applies_to"]),
                "Each source must map to known model quantities through applies_to.")
        require(isinstance(source.get("ancestry"), list), "Source ancestry must be a list; use [] if unknown.")
        for origin in source["ancestry"]:
            nonblank(origin, "Ancestry")
    sensitivity = document.get("sensitivity")
    require(isinstance(sensitivity, dict) and isinstance(sensitivity.get("comparisons"), list), "Supply sensitivity comparisons.")
    require(isinstance(sensitivity.get("not_applicable_reason"), str), "Supply sensitivity not_applicable_reason (empty when tested).")
    require(sensitivity["comparisons"] or sensitivity["not_applicable_reason"].strip(),
            "Reference actual sensitivity runs or explain why sensitivity is not applicable.")
    for comparison in sensitivity["comparisons"]:
        require(isinstance(comparison, dict), "Sensitivity comparison must be an object.")
        for field in ("baseline_run", "variation_run", "reason"):
            nonblank(comparison.get(field), "Sensitivity " + field)
    stopping = document.get("stopping")
    require(isinstance(stopping, dict) and isinstance(stopping.get("remaining_gaps"), list), "Supply stopping reason and remaining_gaps.")
    nonblank(stopping.get("reason"), "Stopping rationale")
    for gap in stopping["remaining_gaps"]:
        nonblank(gap, "Remaining gap")
    if document["status"] == "reviewed":
        require(sources and searches, "Reviewed research requires a source ledger and search records.")
        require(not stopping["remaining_gaps"], "Material gaps require provisional status.")
    dispositions = document.get("warning_dispositions")
    require(isinstance(dispositions, list), "Warning dispositions must be a list.")
    seen = set()
    for entry in dispositions:
        require(isinstance(entry, dict), "Warning disposition must be an object.")
        for field in ("warning_id", "reason"):
            nonblank(entry.get(field), "Disposition " + field)
        require(entry["warning_id"] not in seen, "Duplicate warning disposition.")
        seen.add(entry["warning_id"])


def strip_provenance(value):
    if isinstance(value, dict):
        return {k: strip_provenance(v) for k, v in value.items()
                if k not in {"id", "recorded_at", "previous", "reason", "source", "note", "ancestry", "assumes", "asof", "definition"}}
    if isinstance(value, list):
        return [strip_provenance(v) for v in value]
    return value


def numerical_inputs(run, state):
    """Ignore provenance edits and RNG changes when recognizing sensitivity work."""
    nodes = set(run["leaf_estimates"]) | set(run.get("process_priors", {}))
    return {"marginals": {n: {"default": state["estimates"].get(n, {}).get("distribution"),
                             "given": {k: e["distribution"] for k, e in state.get("conditional_estimates", {}).get(n, {}).items()}}
                          for n in sorted(nodes)},
            "relations": {fork: {n: state["graphs"][fork][n]["expression"] for n in graph_order(state, fork, run["target"])
                                 if n in state["graphs"][fork]} for fork in run["forks"]},
            "bounds": {b["node"]: {k: state["bounds"][b["node"]][k] for k in ("lower", "upper", "clip")} for b in run["bounds"]},
            "merge": {k: run["merge"][k] for k in ("forks", "weights")} if run["merge"] else None,
            "scenario_groups": {g: {k: v["p"] for k, v in records.items()} for g, records in run.get("scenario_groups", {}).items()},
            "process_plan": strip_provenance(run.get("process_plan", {}))}


def sensitivity_results(document, get_run, get_state, final_run, recorded_at):
    results = []
    for comparison in document["sensitivity"]["comparisons"]:
        runs = [get_run(comparison[field]) for field in ("baseline_run", "variation_run")]
        states = [get_state(r["revision"]) for r in runs]
        require(all(r["target"] == final_run["target"] and r["units"] == final_run["units"] for r in runs),
                "Sensitivity runs must have the reviewed target and units.")
        bindings = [forecast_binding(r, s) for r, s in zip(runs, states)]
        require(bindings[0]["scope"] == bindings[1]["scope"], "Sensitivity runs must use the same outcome scope.")
        final_binding = forecast_binding(final_run, get_state(final_run["revision"]),
                                         definition=bindings[0]["definition"], decisions=bindings[0]["decisions"])
        require(final_binding["scope"] == bindings[0]["scope"], "Sensitivity scope must match a context in the reviewed run.")
        require(set(runs[0]["forks"]) == set(runs[1]["forks"]),
                "Comparing different strategies alone is not a sensitivity test; vary inputs or relations with the same forks.")
        for r in runs:
            require(r["revision"] <= final_run["revision"] and timestamp(r["created_at"]) <= timestamp(recorded_at),
                    "Sensitivity runs must exist before review and at or before the final model revision.")
        inputs = [numerical_inputs(r, s) for r, s in zip(runs, states)]
        changed = [key for key in inputs[0] if inputs[0][key] != inputs[1][key]]
        require(changed, "Sensitivity needs changed numerical inputs; a new seed, more draws, or new provenance alone is insufficient.")
        entries = [forecast_samples(r, b) for r, b in zip(runs, bindings)]
        results.append({**comparison, "run_sha256": [digest(r) for r in runs], "changed_components": changed,
                        "results": {method: {"baseline": reported_summary(entries[0][method]),
                                             "variation": reported_summary(entries[1][method]),
                                             "median_change": reported_summary(entries[1][method])["median"] - reported_summary(entries[0][method])["median"]}
                                    for method in sorted(entries[0].keys() & entries[1].keys())}})
    return results


def review_data(document, state, revision, get_run, get_state, recorded_at):
    validate_document(document, state)
    run = get_run(document["run_id"])
    frozen = get_state(run["revision"])
    require(run["revision"] <= revision and timestamp(run["created_at"]) <= timestamp(recorded_at), "Review cannot precede its run.")
    require(evidence_digest(state) == evidence_digest(frozen), "Model or evidence changed after this run. Sample again before review.", "stale_run")
    findings = run_findings(run, frozen)
    require({d["warning_id"] for d in document["warning_dispositions"]} <= {f["id"] for f in findings}, "Disposition references an unknown warning.")
    return {"engine": ENGINE, "document": deepcopy(document), "target": run["target"], "run_id": run["id"],
            "run_sha256": digest(run), "basis_sha256": evidence_digest(frozen), "reviewed_revision": revision,
            "findings": findings, "dependency_overlap": dependency_overlap(run, frozen, document["sources"]),
            "sensitivity_results": sensitivity_results(document, get_run, get_state, run, recorded_at),
            "verification": "Structure, run bindings, and computed comparisons checked; source truth, population mappings, independence, and research sufficiency remain agent judgments."}


def issuance_data(state, revision, review_name, get_run, get_state, *, method=None, coverages=(.8, .9), definition=None, decisions=None):
    require(review_name in state.get("research_reviews", {}), "Unknown research review.", "not_found")
    review = state["research_reviews"][review_name]
    run = get_run(review["run_id"])
    require(evidence_digest(state) == review["basis_sha256"], "Model or evidence changed. Sample and record a new review before issuing.", "stale_run")
    findings = review["findings"]
    require(not any(f["blocks_issuance"] for f in findings),
            "Fix invalid rate support, units, or scenario probabilities and resample before issuance; these findings cannot be waived.", "model_check_failed")
    handled = {d["warning_id"] for d in review["document"]["warning_dispositions"]}
    unresolved = [f for f in findings if f["id"] not in handled]
    if review["document"]["status"] == "reviewed":
        require(not unresolved, "Resolve or explicitly justify every remaining warning before reviewed issuance; use a provisional review for incomplete work.", "unresolved_findings")
    binding = forecast_binding(run, get_state(run["revision"]), definition=definition, decisions=decisions)
    entries = forecast_samples(run, binding)
    if method is None:
        require(len(entries) == 1, "Choose --method strategy:FORK or mixture for the issued headline; all strategies remain visible.", "ambiguous_result")
        method = next(iter(entries))
    require(method in entries, "Unknown issued method for this context.", "not_found")
    summaries = {key: reported_summary(values, coverages=coverages) for key, values in entries.items()}
    return {"engine": ENGINE, "issued_revision": revision, "review": review_name, "review_id": review["id"],
            "review_sha256": digest(review), "forecast": binding, "target": run["target"], "run_id": run["id"],
            "basis_sha256": review["basis_sha256"], "status": review["document"]["status"],
            "method": method, "coverages": [i["coverage"] for i in summaries[method]["intervals"]],
            "definition": definition, "decisions": decisions, "headline": summaries[method], "strategies": summaries,
            "unresolved_findings": unresolved, "dispositions": review["document"]["warning_dispositions"],
            "remaining_gaps": review["document"]["stopping"]["remaining_gaps"],
            "stopping_reason": review["document"]["stopping"]["reason"], "verification": review["verification"]}


def validate_research_records(state):
    for registry in ("research_reviews", "issued_reports"):
        records = state.get(registry, {})
        require(isinstance(records, dict), registry + " must be an object.")
        for key, record in records.items():
            require(isinstance(record, dict) and record.get("name") == key and record.get("engine") == ENGINE, "Invalid research record identity.")
            nonblank(record.get("id"), "Record ID")
            timestamp(record.get("created_at"))
            require(record.get("target") in state["quantities"], "Research record has an unknown target.")
            if registry == "research_reviews":
                validate_document(record.get("document"), state)


def validate_artifact_history(states, runs):
    from .calibration_validation import validate_artifact_history as validate_calibration_history
    validate_calibration_history(states, runs)
    run_map = {r["id"]: r for r in runs}
    def get_run(key):
        require(key in run_map, "Research record references an unknown run.")
        return run_map[key]
    def get_state(revision):
        require(type(revision) is int and 1 <= revision <= len(states), "Invalid research run revision.")
        return states[revision - 1]
    previous = {"research_reviews": {}, "issued_reports": {}}
    for revision, state in enumerate(states, 1):
        for registry, old in previous.items():
            records = state.get(registry, {})
            require(old.keys() <= records.keys(), "Research history was removed.")
            for key, record in records.items():
                if key in old:
                    require(record == old[key], "An immutable research record was changed.")
                    continue
                require(revision > 1, "Research records cannot appear in the initial revision.")
                before = states[revision - 2]
                if registry == "research_reviews":
                    expected = review_data(record["document"], before, revision - 1, get_run, get_state, record["created_at"])
                else:
                    expected = issuance_data(before, revision - 1, record["review"], get_run, get_state,
                                             method=record["method"], coverages=record["coverages"],
                                             definition=record["definition"], decisions=record["decisions"])
                    require(timestamp(record["created_at"]) >= timestamp(before["research_reviews"][record["review"]]["created_at"]), "Issuance predates review.")
                require(record == {**expected, **{k: record[k] for k in ("name", "id", "created_at")}},
                        "Research record does not match saved evidence or numerical results.")
            previous[registry] = records
