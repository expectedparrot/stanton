"""Mechanical findings, never source verification or a calibration certificate."""

from collections import defaultdict
from datetime import date

import numpy as np

from .common import StantonError
from .distributions import Distribution
from .expressions import UNITS, evaluate, magnitude, parse
from .schemas import date_range, graph_order


def finding(code, message, **context):
    return {"code": code, "message": message, **context}


def lint(state):
    warnings, citations = [], defaultdict(set)
    estimates = list(state["estimates"].items())
    estimates += [(node, estimate) for node, values in state.get("conditional_estimates", {}).items() for estimate in values.values()]
    for node, est in estimates:
        warning_start = len(warnings)
        if not est["source"].strip() and not est["reason"].strip():
            warnings.append(finding("unsourced-leaf", "Estimate has neither a source nor a reason.", node=node))
        if est["anchor_kind"] and not est["source"].strip():
            warnings.append(finding("empty-source-slot", "Anchor source is blank.", node=node))
        dist = Distribution.from_dict(est["distribution"])
        space = state["quantities"][node]["space"]
        points = dist.ppf(np.array([0, 1]))
        # Zero is a limiting quantile, not a supported value, for these open-support families.
        crosses_zero = dist.family == "normal" or (dist.family not in {"lognormal", "logitnormal"} and points[0] <= 0)
        if space == "log" and crosses_zero:
            warnings.append(finding("support-crosses-zero", "Log-tagged quantity has support at or below zero.", node=node))
        if space == "logit" and (points[0] < 0 or points[1] > 1):
            warnings.append(finding("support-outside-rate", "Logit-tagged quantity has support outside [0, 1].", node=node,
                                    remedy="Re-estimate with --shape logitnormal (strictly interior interval endpoints), or explicitly bounded samples/quantiles. Then sample again; do not clip invalid rate draws after sampling."))
        for assumption in est["assumes"]:
            citations[assumption].add(node)
        cutoff = state["context"].get("asof")
        if cutoff and est["asof"]:
            start, end = date_range(est["asof"])
            if start > date.fromisoformat(cutoff):
                warnings.append(finding("future-leak", "Source dates follow the project information cutoff.", node=node))
            elif end > date.fromisoformat(cutoff):
                warnings.append(finding("possible-future-leak", "Source date range overlaps the information cutoff.", node=node))
        if est.get("definition_id") and est.get("definition_revision") != state["definitions"][est["definition_id"]]["id"]:
            warnings.append(finding("stale-definition-tag", "Estimate retains an older definition revision.", node=node))
        if est.get("elicitation", {}).get("respondent", {}).get("kind") == "llm_panel":
            warnings.append(finding("synthetic-elicitation", "Estimate comes from a synthetic respondent; its accuracy and interval coverage are uncalibrated.", node=node))
        for warning in warnings[warning_start:]:
            warning.update(estimate_id=est["id"], given=est.get("given"))
    from .elicitation import model_digest
    for survey, record in state.get("surveys", {}).items():
        if any(p["status"] == "pending" for p in record["proposals"].values()) and model_digest(state) != record["instrument"]["model_sha256"]:
            warnings.append(finding("stale-survey-proposals", "Pending responses belong to an older model; draft a new instrument before applying them.", survey=survey))
    for series, record in state.get("series", {}).items():
        if record["kind"] != "path":
            continue
        for period, anchor in record["anchors"].items():
            for node, estimate in estimates:
                if node == anchor["quantity"] and estimate["asof"]:
                    start, end = date_range(estimate["asof"])
                    if start != end:
                        warnings.append(finding("fuzzy-anchor-time", "Anchor date range is preserved as provenance; path periods do not propagate date uncertainty.",
                                                series=series, period=period, node=node, estimate_id=estimate["id"]))
    for assumption, leaves in citations.items():
        code = "orphan-assumption" if len(leaves) == 1 else "unresolved-dependence"
        message = ("Assumption is cited by exactly one estimate." if len(leaves) == 1 else
                   "Shared textual citations do not set numerical correlation; use a shared factor in relations.")
        warnings.append(finding(code, message, assumption=assumption, nodes=sorted(leaves)))
    for scenario, record in state.get("scenarios", {}).items():
        if not record["reason"].strip():
            warnings.append(finding("unsourced-scenario-p", "Scenario probability has no recorded reason.", scenario=scenario))
    for group in state.get("scenario_groups", {}):
        total = sum(record["p"] for record in state.get("scenarios", {}).values() if record["group"] == group)
        if abs(total - 1) > 1e-12:
            warnings.append(finding("incomplete-scenarios", "Group probabilities must sum to one before sampling.", group=group, probability_sum=total))
    for decision, record in state.get("decisions", {}).items():
        if record["status"] == "unasked":
            warnings.append(finding("unasked-decision", "Decision remains unasked; all options will be reported separately.", decision=decision))
    for definition, record in state.get("definitions", {}).items():
        if record["owner"] == "reconstructed":
            warnings.append(finding("reconstructed-definition", "Confidence is provenance, not an automatic numerical uncertainty adjustment; model alternative definitions or uncertain bridges explicitly.",
                                    definition=definition, confidence=record["confidence"]))
    for bridge, record in state.get("bridges", {}).items():
        if any(record[direction + "_revision"] != state["definitions"][record[direction]]["id"] for direction in ("from", "to")):
            warnings.append(finding("stale-definition-bridge", "Bridge retains an older endpoint definition; review the conversion.", node=bridge))
    for fork, graph in state["graphs"].items():
        if state["strategies"][fork]["status"] == "abandoned":
            continue
        values = {}
        for node in sorted(set(graph) & ({key for key, _ in estimates})):
            warnings.append(finding("overridden-estimate", "A relation overrides this node's direct estimate or anchor in this fork; the estimate is not a constraint or a lower bound.",
                                    node=node, fork=fork,
                                    remedy="Use a separate evidence leaf and relate it explicitly, or use bound TARGET --lower VALUE --reason TEXT if the population mapping supports a bound. Bounds warn unless --clip is specified."))
        for node in graph_order(state, fork):
            q = state["quantities"][node]
            try:
                if node not in graph:
                    values[node] = UNITS.Quantity(np.ones(1), q["units"])
                else:
                    tree, deps = parse(graph[node]["expression"])
                    if not deps <= values.keys():
                        continue
                    arr = magnitude(evaluate(tree, values), q["units"], 1)
                    values[node] = UNITS.Quantity(arr, q["units"])
            except StantonError as exc:
                if exc.code == "unit_mismatch":
                    warnings.append(finding("unit-mismatch", str(exc), node=node, fork=fork))
                # A representative value can hit a singularity in a valid model.
    for target, merge in state["merges"].items():
        origins = defaultdict(set)
        for fork in merge["forks"]:
            for node in graph_order(state, fork, target):
                if node not in state["graphs"][fork] and node in state["estimates"]:
                    for ancestor in state["estimates"][node]["ancestry"]:
                        origins[ancestor].add(fork)
        for ancestor, forks in origins.items():
            if len(forks) > 1:
                warnings.append(finding("shared-ancestor", "Merged strategies share declared ancestry; weights are unchanged.",
                                        target=target, ancestor=ancestor, forks=sorted(forks)))
    return warnings
