"""Explicit research gaps and consistency checks; no automatic source verification."""

from datetime import date

from .common import digest, finite, nonblank, require
from .distributions import Distribution

SCOPE_FIELDS = ("population", "geography", "counting_unit", "inclusions", "exclusions", "interpretation")


def window(value, label):
    require(isinstance(value, dict), label + " requires start and end ISO dates.")
    require(all(isinstance(value.get(k), str) and value[k].strip() for k in ("start", "end")), label + " requires nonblank start/end ISO dates.")
    try:
        start, end = date.fromisoformat(value["start"]), date.fromisoformat(value["end"])
    except ValueError:
        require(False, label + " dates must use YYYY-MM-DD.")
    require(start <= end, label + " dates are reversed.")
    return start, end


def finding(code, message, *, gap=False, **context):
    body = {"code": code, "message": message, "requires_provisional": gap, "blocks_issuance": False, **context}
    return {"id": digest(body), **body}


def validate_review_fields(document, state):
    require(document.get("schema_version") == 2, "Use a fresh research template (schema 2); preserve its required fields.")
    scope = document.get("scope_details")
    require(isinstance(scope, dict), "Supply scope_details: population, geography, counting_unit, inclusions, exclusions, interpretation, reference_period.")
    for field in SCOPE_FIELDS:
        nonblank(scope.get(field), "scope_details." + field)
    window(scope.get("reference_period"), "Target reference period")
    sensitivity = document["sensitivity"]
    require(sensitivity.get("status") in {"performed", "not_performed", "not_applicable"},
            "Sensitivity status must be performed, not_performed, or not_applicable. Strategy comparison alone is not sensitivity.")
    nonblank(sensitivity.get("reason"), "Sensitivity reason")
    require(bool(sensitivity["comparisons"]) == (sensitivity["status"] == "performed"),
            "Performed sensitivity requires comparisons; omitted/inapplicable sensitivity must have no comparisons.")
    for source in document["sources"]:
        require("observation_window" in source, "Source needs observation_window (start/end dates, or null if unknown).")
        if source["observation_window"] is not None:
            window(source["observation_window"], "Source observation window")
        require(source.get("temporal_status") in {"aligned", "adjusted", "unresolved", "unknown"}, "Supply source temporal_status: aligned, adjusted, unresolved, unknown.")
        nonblank(source.get("temporal_mapping"), "Source temporal_mapping")
        if source["temporal_status"] == "adjusted":
            nonblank(source.get("temporal_evidence"), "Evidence supporting temporal adjustment")
    ids = {s["id"] for s in document["sources"]}
    for field in ("discrepancies", "numeric_checks", "input_dependencies"):
        require(isinstance(document.get(field), list), field + " must be a list; use [] when there are none.")
    seen = set()
    for item in document["discrepancies"]:
        require(isinstance(item, dict), "Each discrepancy must be an object.")
        for field in ("id", "claim", "explanation"):
            nonblank(item.get(field), "Discrepancy " + field)
        require(item["id"] not in seen, "Discrepancy IDs must be unique.")
        seen.add(item["id"])
        require(item.get("status") in {"resolved", "unresolved"}, "Discrepancy status must be resolved or unresolved.")
        require(isinstance(item.get("source_ids"), list) and set(item["source_ids"]) <= ids, "Discrepancy references unknown sources.")
        if item["status"] == "resolved":
            nonblank(item.get("evidence"), "Evidence resolving discrepancy (a possible explanation alone is insufficient)")
    seen = set()
    for item in document["numeric_checks"]:
        require(isinstance(item, dict), "Each numeric check must be an object.")
        for field in ("id", "denominator_population", "explanation"):
            nonblank(item.get(field), "Numeric check " + field)
        require(item["id"] not in seen and item.get("source_id") in ids, "Numeric check needs a unique ID and known source_id.")
        seen.add(item["id"])
        numerator, denominator = finite(item.get("numerator")), finite(item.get("denominator"))
        require(denominator > 0 and numerator >= 0, "Ratio checks require a positive denominator and nonnegative numerator.")
        ratio, tolerance = finite(item.get("reported_ratio")), finite(item.get("tolerance", .0001))
        require(0 <= ratio <= 1 and 0 <= tolerance <= .01, "Reported ratios use fractions [0,1]; rounding tolerance must lie in [0,.01].")
    for item in document["input_dependencies"]:
        require(isinstance(item, dict), "Each input dependency must be an object.")
        require(item.get("quantity") in state["quantities"], "Unknown dependent input.")
        require(isinstance(item.get("depends_on"), list) and item["depends_on"]
                and set(item["depends_on"]) <= state["quantities"].keys(), "Input dependencies require known quantities.")
        nonblank(item.get("reason"), "Input dependency reason")


def research_findings(document, run, frozen, overlap):
    findings = []
    for pair in overlap:
        if any(pair.get(k) for k in ("shared_leaves", "shared_ancestry", "shared_source_ids", "shared_evidence_quantities")):
            findings.append(finding("shared-strategy-evidence", "Strategies share evidence. Their agreement does not establish independent corroboration; retain this limitation in the final answer.", **pair))
    sensitivity = document["sensitivity"]
    if sensitivity["status"] == "not_performed":
        findings.append(finding("sensitivity-not-performed", "Consequential assumptions have not been stress-tested with saved input variations.", gap=True, reason=sensitivity["reason"]))
    elif sensitivity["status"] == "not_applicable":
        estimates = [frozen["estimates"][k] for k in set(run["leaf_estimates"]) | set(run.get("process_priors", {})) if k in frozen["estimates"]]
        estimates += [e for k in run["leaf_estimates"] for e in frozen.get("conditional_estimates", {}).get(k, {}).values()]
        deterministic = all(Distribution.from_dict(e["distribution"]).family == "point" for e in estimates)
        deterministic &= not bool(run.get("process_plan", {}).get("allocations"))
        deterministic &= all(sum(v["p"] > 0 for v in group.values()) <= 1 for group in run.get("scenario_groups", {}).values())
        deterministic &= len({value for values in run["samples"].values() for value in values}) == 1
        require(deterministic, "Sensitivity is not inapplicable to this uncertain model. Save input variations, or mark not_performed and issue provisionally.", "sensitivity_required")
        findings.append(finding("sensitivity-not-applicable", "Agent declares sensitivity inapplicable to this deterministic model; the reason is not independently verified.", reason=sensitivity["reason"]))
    target_start, target_end = window(document["scope_details"]["reference_period"], "Target reference period")
    for source in document["sources"]:
        observed = source["observation_window"]
        status = source["temporal_status"]
        if observed is None:
            require(status in {"unknown", "unresolved"}, "Unknown observation dates cannot be declared aligned or adjusted.")
        else:
            start, end = window(observed, "Source observation window")
            if start < target_start or end > target_end:
                require(status != "aligned", "Source observation dates extend outside the target period; document an adjustment or mark unresolved.", "temporal_mismatch")
        if status in {"unknown", "unresolved"}:
            findings.append(finding("unresolved-source-period", "Source timing is not reconciled with the target reference period.", gap=True, source_id=source["id"], explanation=source["temporal_mapping"]))
        elif status == "adjusted":
            findings.append(finding("source-period-adjustment", "Source data were mapped across observation periods; disclose the adjustment and evidence.", source_id=source["id"], explanation=source["temporal_mapping"], evidence=source["temporal_evidence"]))
    for item in document["discrepancies"]:
        if item["status"] == "unresolved":
            findings.append(finding("unresolved-source-discrepancy", item["claim"], gap=True, discrepancy_id=item["id"], source_ids=item["source_ids"], explanation=item["explanation"]))
    for item in document["numeric_checks"]:
        calculated = item["numerator"] / item["denominator"]
        if abs(calculated - item["reported_ratio"]) > item.get("tolerance", .0001):
            findings.append(finding("source-ratio-mismatch", "Reported share does not match the supplied numerator and denominator. Reconcile the denominator population before treating this as resolved.", gap=True, check_id=item["id"], source_id=item["source_id"], calculated_ratio=calculated, reported_ratio=item["reported_ratio"], denominator_population=item["denominator_population"]))
    return findings


def presentation(record, review=None):
    """Current read-only warnings around immutable historical artifacts."""
    warnings = list(record.get("findings", record.get("unresolved_findings", [])))
    status = record.get("status", record.get("document", {}).get("status"))
    if status == "provisional":
        warnings.append({"code": "provisional-result", "message": "Provisional result; disclose research gaps with the headline."})
    if record["engine"] == "stanton.research-review.v1":
        warnings.append({"code": "legacy-research-review", "message": "Historical review predates explicit sensitivity and scope checks. Create a new review before issuing a new conclusion."})
        basis = review or record
        for pair in basis.get("dependency_overlap", []):
            if any(pair.get(k) for k in ("shared_leaves", "shared_ancestry", "shared_source_ids")):
                warnings.append(finding("shared-strategy-evidence", "Historical strategies share evidence; do not describe their agreement as independent corroboration.", **pair))
        if not basis.get("sensitivity_results"):
            warnings.append({"code": "sensitivity-not-performed", "message": "Historical review contains no saved sensitivity comparisons."})
    return warnings
