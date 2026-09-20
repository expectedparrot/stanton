"""Public input descriptions and validation of persisted model invariants."""

import calendar
import re
from datetime import date

from .common import canonical, finite, name, nonblank, require
from .distributions import Distribution
from .expressions import unit

SCHEMAS = {
    "quantity": {"type": "object", "required": ["name", "units", "definition"], "properties": {
        "name": {"type": "string"}, "units": {"type": "string"}, "definition": {"type": "string"},
        "space": {"enum": ["log", "linear", "logit"]}, "status": {"enum": ["known", "estimated", "target"]}}},
    "distribution": {"type": "object", "required": ["family", "parameters"], "additionalProperties": False,
        "properties": {"family": {"enum": ["point", "normal", "lognormal", "logitnormal", "empirical", "quantiles"]},
                       "parameters": {"type": "array"}}},
    "estimate": {"type": "object", "required": ["quantity", "distribution"], "properties": {
        "quantity": {"type": "string"}, "distribution": {"$ref": "#/$defs/distribution"},
        "source": {"type": "string"}, "reason": {"type": "string"}, "method": {"type": "string"},
        "assumes": {"type": "array", "items": {"type": "string"}},
        "kind": {"enum": ["epistemic", "aleatoric"]}, "note": {"type": "string"},
        "ancestry": {"type": "array", "items": {"type": "string"}}, "asof": {"type": ["string", "null"]}}},
    "relation": {"type": "object", "required": ["target", "expression"], "properties": {
        "target": {"type": "string"}, "expression": {"type": "string"}, "fork": {"type": "string"}}},
    "merge": {"type": "object", "required": ["target", "forks", "weights", "reason"], "properties": {
        "target": {"type": "string"}, "forks": {"type": "array", "items": {"type": "string"}},
        "weights": {"type": "array", "items": {"type": "number", "minimum": 0}}, "reason": {"type": "string"}}},
}

# Structured review documents use explicit evidence fields, not checklist booleans.
_REVIEW_TEXT = {"type": "string", "minLength": 1}
_SOURCE_TEXT_FIELDS = ("id", "reference", "claim", "population", "target_mapping", "method", "limitations",
                       "publication_date", "observation_period", "accessed_at")
SCHEMAS["research_review"] = {
    "type": "object",
    "required": ["run_id", "status", "scope", "searches", "sources", "reconciliation", "alternative_model",
                 "dependence", "uncertainty", "sensitivity", "stopping", "warning_dispositions"],
    "properties": {
        **{k: _REVIEW_TEXT for k in ("run_id", "scope", "reconciliation", "alternative_model", "dependence", "uncertainty")},
        "status": {"enum": ["reviewed", "provisional"]},
        "searches": {"type": "array", "items": {"type": "object", "required": ["query", "outcome"],
                     "properties": {k: _REVIEW_TEXT for k in ("query", "outcome")}}},
        "sources": {"type": "array", "items": {"type": "object", "required": [*_SOURCE_TEXT_FIELDS, "applies_to", "ancestry"],
                    "properties": {**{k: _REVIEW_TEXT for k in _SOURCE_TEXT_FIELDS},
                                   "applies_to": {"type": "array", "minItems": 1, "items": _REVIEW_TEXT},
                                   "ancestry": {"type": "array", "items": _REVIEW_TEXT}}}},
        "sensitivity": {"type": "object", "required": ["status", "comparisons", "reason"], "properties": {
            "comparisons": {"type": "array", "items": {"type": "object", "required": ["baseline_run", "variation_run", "reason"],
                            "properties": {k: _REVIEW_TEXT for k in ("baseline_run", "variation_run", "reason")}}},
            "status": {"enum": ["performed", "not_performed", "not_applicable"]}, "reason": _REVIEW_TEXT}},
        "stopping": {"type": "object", "required": ["reason", "remaining_gaps"], "properties": {
            "reason": _REVIEW_TEXT, "remaining_gaps": {"type": "array", "items": _REVIEW_TEXT}}},
        "warning_dispositions": {"type": "array", "items": {"type": "object", "required": ["warning_id", "reason"],
                                 "properties": {k: _REVIEW_TEXT for k in ("warning_id", "reason")}}},
        "available_findings": {"type": "array", "description": "Template hints only; authoritative findings are recomputed."}
    },
    "description": "Run-bound agent review. Reviewed status requires sources, searches, no remaining material gaps, and warning dispositions before issuance. Sensitivity comparisons need changed numerical inputs or a concrete not-applicable reason. Source truth and research sufficiency are not certified."
}

_DATE_WINDOW = {"type": "object", "required": ["start", "end"],
                "properties": {k: {"type": "string", "format": "date"} for k in ("start", "end")}}
_scope_fields = ("population", "geography", "counting_unit", "inclusions", "exclusions", "interpretation")
_review = SCHEMAS["research_review"]
_review["required"] += ["schema_version", "scope_details", "discrepancies", "numeric_checks", "input_dependencies"]
_review["properties"].update({
    "schema_version": {"const": 2},
    "scope_details": {"type": "object", "required": [*_scope_fields, "reference_period"],
                      "properties": {**{k: _REVIEW_TEXT for k in _scope_fields}, "reference_period": _DATE_WINDOW}},
    "discrepancies": {"type": "array", "items": {"type": "object", "required": ["id", "claim", "status", "source_ids", "explanation"],
                      "properties": {**{k: _REVIEW_TEXT for k in ("id", "claim", "explanation", "evidence")},
                                     "status": {"enum": ["resolved", "unresolved"]},
                                     "source_ids": {"type": "array", "items": _REVIEW_TEXT}}}},
    "numeric_checks": {"type": "array", "items": {"type": "object",
                       "required": ["id", "source_id", "numerator", "denominator", "reported_ratio", "denominator_population", "explanation"],
                       "properties": {**{k: _REVIEW_TEXT for k in ("id", "source_id", "denominator_population", "explanation")},
                                      "numerator": {"type": "number", "minimum": 0}, "denominator": {"type": "number", "exclusiveMinimum": 0},
                                      "reported_ratio": {"type": "number", "minimum": 0, "maximum": 1},
                                      "tolerance": {"type": "number", "minimum": 0, "maximum": .01, "default": .0001}}}},
    "input_dependencies": {"type": "array", "items": {"type": "object", "required": ["quantity", "depends_on", "reason"],
                           "properties": {"quantity": _REVIEW_TEXT, "reason": _REVIEW_TEXT,
                                          "depends_on": {"type": "array", "minItems": 1, "items": _REVIEW_TEXT}}}},
})
_source = _review["properties"]["sources"]["items"]
_source["required"] += ["observation_window", "temporal_status", "temporal_mapping"]
_source["properties"].update(observation_window={"anyOf": [_DATE_WINDOW, {"type": "null"}]},
                             temporal_status={"enum": ["aligned", "adjusted", "unresolved", "unknown"]},
                             temporal_mapping=_REVIEW_TEXT, temporal_evidence=_REVIEW_TEXT)
_review["description"] = "Schema 2 run-bound research review. Missing sensitivity and unresolved evidence require provisional issuance even if acknowledged. Not-applicable sensitivity is restricted to deterministic models and requires justification. Resolved discrepancies and time adjustments require supporting evidence. Source truth and research sufficiency remain agent judgments."

SCHEMAS["quantity"]["properties"]["predicates"] = {"type": "object", "additionalProperties": {"type": "boolean"}}
SCHEMAS["estimate"]["properties"].update(given={"type": ["string", "null"]}, definition_id={"type": ["string", "null"]})
SCHEMAS.update({
    "calibration": {"type": "object", "required": ["calibration", "cohort", "method", "reason"], "properties": {
        "calibration": {"type": "string"}, "cohort": {"type": "string"},
        "method": {"type": "string", "pattern": "^(mixture|strategy:[A-Za-z][A-Za-z0-9_]*)$"},
        "reason": {"type": "string", "minLength": 1}, "include_retrospective": {"type": "boolean", "default": False},
        "scales": {"type": "array", "minItems": 1, "maxItems": 100, "uniqueItems": True,
                   "contains": {"const": 1}, "items": {"type": "number", "exclusiveMinimum": 0}}}},
    "resolution": {"type": "object", "required": ["target", "outcome", "event", "run_id", "units", "source", "observed_at"], "properties": {
        "target": {"type": "string"}, "event": {"type": "string"}, "run_id": {"type": "string"}, "outcome": {"type": "number"},
        "units": {"type": "string"}, "source": {"type": "string", "minLength": 1}, "observed_at": {"type": "string", "format": "date-time"},
        "definition": {"type": ["string", "null"]}, "decisions": {"type": "object", "additionalProperties": {"type": "string"}},
        "reason": {"type": "string"}, "replaces": {"type": ["string", "null"]}}},
    "cohort": {"type": "object", "required": ["cohort", "members", "units", "reason"], "properties": {
        "cohort": {"type": "string"}, "units": {"type": "string"}, "reason": {"type": "string", "minLength": 1},
        "coverages": {"type": "array", "minItems": 1, "maxItems": 20, "uniqueItems": True,
                      "items": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1}},
        "members": {"type": "array", "minItems": 1, "maxItems": 1000, "items": {"type": "object", "additionalProperties": False,
            "required": ["event", "run_id", "group", "split"], "properties": {"event": {"type": "string"}, "run_id": {"type": "string"},
                "group": {"type": "string"}, "split": {"enum": ["train", "test"]}, "definition": {"type": ["string", "null"]},
                "decisions": {"type": "object", "additionalProperties": {"type": "string"}}}}}}},
    "survey": {"type": "object", "required": ["survey"], "properties": {
        "survey": {"type": "string"}, "phase": {"enum": ["triage", "targeted"]},
        "budget": {"type": "integer", "minimum": 1, "maximum": 100},
        "nodes": {"type": "array", "uniqueItems": True, "minItems": 1, "items": {"type": "string"}},
        "coverage": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1}, "reask": {"type": "boolean"}}},
    "survey_responses": {"type": "object", "required": ["schema_version", "project_id", "instrument_id", "instrument_sha256", "model_revision", "model_sha256", "responses"],
        "properties": {"schema_version": {"const": 1}, "project_id": {"type": "string"}, "instrument_id": {"type": "string"},
            "instrument_sha256": {"type": "string"}, "model_revision": {"type": "integer", "minimum": 1}, "model_sha256": {"type": "string"},
            "responses": {"type": "array", "minItems": 1, "maxItems": 1000, "items": {
                "type": "object", "required": ["respondent", "answers"], "additionalProperties": False,
                "properties": {"respondent": {"type": "object", "required": ["id", "kind"], "properties": {
                    "id": {"type": "string", "minLength": 1}, "kind": {"enum": ["asker", "human_panel", "llm_panel"]}}},
                    "iteration": {"type": "integer", "minimum": 0}, "provenance": {"type": "object"},
                    "answers": {"type": "object", "additionalProperties": {"type": "object", "required": ["status"],
                        "properties": {"status": {"enum": ["point", "interval", "choice", "open", "unknown", "unanswered"]},
                            "value": {"type": "number"}, "low": {"type": "number"}, "high": {"type": "number"},
                            "units": {"type": "string"}, "option": {"type": "string"}, "reason": {"type": "string"}}}}}}}}},
    "series": {"type": "object", "required": ["series", "base", "growth", "periods", "rho", "definition", "reason"], "properties": {
        "series": {"type": "string"}, "base": {"type": "string"}, "growth": {"type": "string"},
        "periods": {"type": "array", "minItems": 2, "maxItems": 256, "uniqueItems": True, "items": {"type": "string"}},
        "rho": {"type": "number", "minimum": -1, "maximum": 1}, "mode": {"enum": ["multiplicative", "additive"]},
        "definition": {"type": "string"}, "reason": {"type": "string"}}},
    "periodic": {"type": "object", "required": ["series", "over", "profile", "definition", "reason"], "properties": {
        "series": {"type": "string"}, "over": {"enum": ["hour_of_day", "day_of_week"]},
        "profile": {"type": "object", "additionalProperties": {"type": "string"}},
        "definition": {"type": "string"}, "reason": {"type": "string"}, "source": {"type": "string"}}},
    "allocation": {"type": "object", "required": ["total", "parts", "reason"], "properties": {
        "total": {"type": "string"}, "allocation": {"type": "string"},
        "parts": {"type": "object", "minProperties": 2, "maxProperties": 256,
                  "additionalProperties": {"type": "number", "exclusiveMinimum": 0}},
        "reason": {"type": "string"}, "source": {"type": "string"}}},
    "scenario": {"type": "object", "required": ["scenario", "p", "definition"], "properties": {
        "scenario": {"type": "string"}, "p": {"type": "number", "minimum": 0, "maximum": 1},
        "definition": {"type": "string"}, "group": {"type": "string"}, "reason": {"type": "string"}}},
    "decision": {"type": "object", "required": ["decision", "options", "definition"], "properties": {
        "decision": {"type": "string"}, "options": {"type": "object", "minProperties": 2, "additionalProperties": {"type": "number"}},
        "definition": {"type": "string"}, "units": {"type": "string"}, "default": {"type": ["string", "null"]}}},
    "definition": {"type": "object", "required": ["definition", "target", "measure", "predicates"], "properties": {
        "definition": {"type": "string"}, "target": {"type": "string"}, "measure": {"type": "string"},
        "predicates": {"type": "object", "additionalProperties": {"type": "boolean"}},
        "owner": {"enum": ["asker", "claimant", "reconstructed"]}, "role": {"enum": ["primary", "branch"]},
        "confidence": {"enum": [None, "high", "medium", "low", "unknown"]}, "source": {"type": "string"}}},
})

for _schema in SCHEMAS.values():
    _schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
SCHEMAS["estimate"]["$defs"] = {"distribution": SCHEMAS["distribution"]}


def date_range(value):
    """Inclusive year/month/day precision, optionally start..end."""
    def part(text):
        require(isinstance(text, str) and re.fullmatch(r"\d{4}(-\d{2}){0,2}", text), "Use YYYY, YYYY-MM, YYYY-MM-DD, or a date range.")
        fields = [int(x) for x in text.split("-")]
        year = fields[0]
        month = fields[1] if len(fields) > 1 else 1
        day = fields[2] if len(fields) > 2 else 1
        low = date(year, month, day)
        last_month = month if len(fields) > 1 else 12
        last_day = day if len(fields) > 2 else calendar.monthrange(year, last_month)[1]
        return low, date(year, last_month, last_day)

    pieces = value.split("..")
    require(len(pieces) <= 2, "Invalid date range.")
    low, high = part(pieces[0])[0], part(pieces[-1])[1]
    require(low <= high, "Date range is reversed.")
    return low, high


def graph_order(state, fork, target=None, *, excluded=(), all_periods=False):
    from .processes import dependencies
    require(fork in state["graphs"], f"Unknown fork: {fork}", "not_found")
    graph = state["graphs"][fork]
    order, active, done = [], set(), set()

    def visit(node):
        require(node in state["quantities"], f"Unknown quantity: {node}", "not_found")
        require(node not in active, f"Cycle involving {node} in fork {fork}.", "cycle")
        if node in done:
            return
        active.add(node)
        if node not in excluded:
            for dependency in sorted(dependencies(state, fork, node, all_periods=all_periods)):
                visit(dependency)
        active.remove(node)
        done.add(node)
        order.append(node)

    roots = set(graph) | {node for node, q in state["quantities"].items() if q.get("process")}
    for node in ([target] if target else sorted(roots)):
        visit(node)
    return order


def validate_state(state):
    require(isinstance(state, dict) and state.get("schema_version") in {1, 2, 3, 4, 5, 6, 7}, "Unsupported state schema.")
    canonical(state)
    for field in ("quantities", "estimates", "assumptions", "graphs", "strategies", "bounds", "merges", "notes"):
        require(isinstance(state.get(field), dict), f"State requires {field}.")
    require("main" in state["graphs"] and set(state["graphs"]) == set(state["strategies"]), "Invalid graph registry.")
    for key, q in state["quantities"].items():
        name(key)
        require(q["name"] == key, "Quantity identity mismatch.")
        nonblank(q["definition"], "Definition")
        unit(q["units"])
        require(q["space"] in {"log", "linear", "logit"}, "Unknown space.")
        require(q["status"] in {"known", "estimated", "target"}, "Unknown quantity status.")
        for predicate, included in q.get("predicates", {}).items():
            name(predicate)
            require(type(included) is bool, "Inclusion predicates must be boolean.")
    for key, assumption in state["assumptions"].items():
        name(key)
        nonblank(assumption["definition"], "Assumption definition")
    estimates = list(state["estimates"].items())
    for key, conditionals in state.get("conditional_estimates", {}).items():
        require(isinstance(conditionals, dict), "Conditional estimates must be an object.")
        require(set(conditionals) <= set(state.get("scenarios", {})), "Unknown conditioning scenario.")
        groups = {state["scenarios"][scenario]["group"] for scenario in conditionals}
        require(len(groups) <= 1, "One leaf can condition on one scenario group; encode joint regimes explicitly.")
        estimates.extend((key, est) for est in conditionals.values())
    for key, est in estimates:
        require(key in state["quantities"], "Estimate references an unknown quantity.")
        Distribution.from_dict(est["distribution"])
        require(est["kind"] in {"epistemic", "aleatoric"}, "Unknown uncertainty kind.")
        nonblank(est["method"], "Method")
        for field in ("source", "reason", "note"):
            require(isinstance(est[field], str), f"Estimate {field} must be text.")
        require(isinstance(est["assumes"], list) and set(est["assumes"]) <= set(state["assumptions"]), "Unknown assumption citation.")
        require(isinstance(est["ancestry"], list), "Ancestry must be an array.")
        for ancestor in est["ancestry"]:
            nonblank(ancestor, "Ancestor")
        if est["asof"] is not None:
            date_range(est["asof"])
        if est.get("definition_id"):
            require(est["definition_id"] in state.get("definitions", {}), "Unknown estimate definition.")
    for group, record in state.get("scenario_groups", {}).items():
        name(group)
        nonblank(record["definition"], "Scenario group definition")
        require(isinstance(record["independence_reason"], str), "Independence reason must be text.")
    for scenario, record in state.get("scenarios", {}).items():
        name(scenario)
        require(record["group"] in state.get("scenario_groups", {}), "Unknown scenario group.")
        require(0 <= finite(record["p"]) <= 1, "Scenario probability must be in [0, 1].")
        nonblank(record["definition"], "Scenario definition")
        require(isinstance(record["reason"], str), "Scenario reason must be text.")
    for decision, record in state.get("decisions", {}).items():
        require(decision in state["quantities"], "Decision requires a quantity.")
        require(decision not in state["estimates"] and decision not in state.get("conditional_estimates", {}) and
                all(decision not in graph for graph in state["graphs"].values()), "Decisions cannot be sampled or derived.")
        require(not state["quantities"][decision].get("predicates"), "Decisions cannot be masked by definitions.")
        require(isinstance(record["options"], dict) and len(record["options"]) >= 2, "Decision requires at least two named options.")
        for option, value in record["options"].items():
            name(option)
            finite(value)
        require(record["default"] is None or record["default"] in record["options"], "Unknown default option.")
        require(record["status"] in {"unasked", "selected", "open"}, "Invalid decision status.")
        require((record["status"] == "selected" and record["selected"] in record["options"]) or
                (record["status"] != "selected" and record["selected"] is None), "Invalid decision selection.")
        if record["status"] != "unasked":
            nonblank(record["reason"], "Decision disposition reason")
    primary = set()
    for definition, record in state.get("definitions", {}).items():
        name(definition)
        require(record["target"] in state["quantities"], "Definition requires a target quantity.")
        nonblank(record["measure"], "Base measure")
        require(record["owner"] in {"asker", "claimant", "reconstructed"}, "Unknown definition owner.")
        require(record["confidence"] in {None, "high", "medium", "low", "unknown"}, "Invalid reconstruction confidence.")
        if record["owner"] == "reconstructed":
            require(record["confidence"] is not None, "Reconstructed definitions need a confidence tag.")
            nonblank(record["source"], "Reconstruction source")
        require(record["role"] in {"primary", "branch"}, "Definition role must be primary or branch.")
        if record["role"] == "primary":
            require(record["target"] not in primary, "Only one primary definition is allowed per target.")
            primary.add(record["target"])
        require(isinstance(record["predicates"], dict), "Definition predicates must be an object.")
        for predicate, included in record["predicates"].items():
            name(predicate)
            require(type(included) is bool, "Definition predicates must be boolean.")
    for bridge, record in state.get("bridges", {}).items():
        require(bridge in state["quantities"] and bridge in state["estimates"], "Bridge requires a quantity and estimate.")
        require(record["from"] in state.get("definitions", {}) and record["to"] in state.get("definitions", {}), "Unknown bridge definitions.")
        require(record["from"] != record["to"], "Bridge endpoints must differ.")
    from .processes import validate_processes
    validate_processes(state)
    from .elicitation import validate_surveys
    validate_surveys(state)
    from .evaluation_validation import validate_evaluations
    validate_evaluations(state)
    from .calibration_validation import validate_calibrations
    validate_calibrations(state)
    from .research_records import validate_research_records
    validate_research_records(state)
    for key in state["graphs"]:
        name(key)
        require(state["strategies"][key]["status"] in {"active", "merged", "abandoned"}, "Unknown strategy status.")
        graph_order(state, key, all_periods=True)
    for key, bound in state["bounds"].items():
        require(key in state["quantities"], "Bound references an unknown quantity.")
        low, high = bound["lower"], bound["upper"]
        require(low is not None or high is not None, "Bound needs an endpoint.")
        if low is not None:
            finite(low)
        if high is not None:
            finite(high)
        require(low is None or high is None or low <= high, "Bound endpoints are reversed.")
        nonblank(bound["reason"], "Bound reason")
        require(type(bound["clip"]) is bool, "Clip must be boolean.")
    for key, merge in state["merges"].items():
        require(key in state["quantities"], "Merge references an unknown target.")
        forks, weights = merge["forks"], merge["weights"]
        require(len(forks) >= 2 and len(forks) == len(set(forks)) and set(forks) <= set(state["graphs"]), "Merge needs distinct known forks.")
        require(len(weights) == len(forks) and all(finite(w) >= 0 for w in weights), "Invalid merge weights.")
        require(abs(sum(weights) - 1) <= 1e-12, "Merge weights must sum to one; normalization is never implicit.")
        nonblank(merge["reason"], "Merge reason")
