"""Scores for frozen empirical forecasts, with explicit outcome scope and timing."""

from copy import deepcopy
from datetime import datetime, timezone

import numpy as np

from .common import digest, finite, require
from .expressions import UNITS, magnitude

SCORER = "stanton.scoring.v1"


def timestamp(value):
    require(isinstance(value, str), "Observation time must be an ISO timestamp.")
    parsed = datetime.fromisoformat(value)
    require(parsed.tzinfo is not None, "Observation time must include a timezone.")
    return parsed.astimezone(timezone.utc)


def coverage_levels(values):
    require(isinstance(values, (list, tuple)) and 1 <= len(values) <= 20, "Supply 1–20 distinct interval coverages.")
    levels = [finite(p, "Coverage") for p in values]
    require(len(set(levels)) == len(levels) and all(0 < p < 1 for p in levels), "Coverages must be distinct and lie strictly between zero and one.")
    return sorted(levels)


def empirical_score(samples, outcome, coverages=(.5, .8, .95)):
    """Exact empirical-CDF CRPS; no quadratic pairwise matrix or unbiased correction."""
    values = np.asarray(samples, dtype=float)
    require(values.ndim == 1 and values.size and np.all(np.isfinite(values)), "Scores require finite scalar sample draws.")
    outcome = finite(outcome, "Outcome")
    levels = coverage_levels(coverages)
    values = np.sort(values)
    # The integrand is constant between observations and the realized outcome.
    grid = np.sort(np.append(values, outcome)).astype(np.longdouble)
    cdf = np.searchsorted(values, grid[:-1], side="right") / len(values)
    crps = np.sum(np.diff(grid) * (cdf - (grid[:-1] >= outcome))**2)
    intervals = []
    for p in levels:
        alpha = 1 - p
        low, high = np.quantile(values, [alpha / 2, 1 - alpha / 2], method="inverted_cdf")
        width = np.longdouble(high) - low
        penalty = 2 / alpha * max(np.longdouble(low) - outcome, np.longdouble(outcome) - high, 0)
        intervals.append({"coverage": p, "lower": float(low), "upper": float(high), "covered": bool(low <= outcome <= high),
                          "width": finite(float(width), "Interval width"), "score": finite(float(width + penalty), "Interval score")})
    median = float(np.quantile(values, .5, method="inverted_cdf"))
    below, equal = float(np.mean(values < outcome)), float(np.mean(values == outcome))
    return {"n_draws": len(values), "outcome": outcome, "crps": finite(float(crps), "CRPS"), "median": median,
            "absolute_error": finite(float(abs(np.longdouble(median) - outcome)), "Absolute error"),
            "pit_interval": [below, below + equal], "pit_midrank": below + equal / 2, "intervals": intervals}


def branch_registry(run):
    return run.get("branches", {fork: {"fork": fork, "definition": None, "definition_revision": None, "flip": None,
                                       "decisions": {}, "context_key": "", "predicates": None} for fork in run["forks"]})


def forecast_binding(run, state, *, definition=None, decisions=None):
    branches = branch_registry(run)
    require(decisions is None or isinstance(decisions, dict), "Decision selection must map names to options.")
    selected = {key: b for key, b in branches.items() if b["flip"] is None and
                (definition is None or b["definition"] == definition) and
                all(b["decisions"].get(key) == value for key, value in (decisions or {}).items())}
    require(selected, "Saved run has no matching definition and decision context.", "not_found")
    require(len({b["context_key"] for b in selected.values()}) == 1,
            "Outcome context is ambiguous; select one definition and all unresolved decisions.", "ambiguous_outcome")
    meta = next(iter(selected.values()))
    scope = {"target": run["target"], "quantity": deepcopy(state["quantities"][run["target"]]),
             "definition": deepcopy(state.get("definitions", {}).get(meta["definition"])), "predicates": meta["predicates"],
             "decisions": {key: {"option": option, "value": state["decisions"][key]["options"][option],
                                 "quantity": deepcopy(state["quantities"][key])} for key, option in meta["decisions"].items()},
             "query_time": run["context"]["now"], "timezone": run["context"]["timezone"]}
    return {"run_id": run["id"], "run_sha256": digest(run),
            "model_revision": run["revision"], "model_sha256": run["state_sha256"], "created_at": run["created_at"],
            "definition": meta["definition"], "decisions": meta["decisions"], "context_key": meta["context_key"],
            "scope": scope, "units": run["units"], "branches": sorted(selected)}


def converted(value, source_units, target_units):
    return float(magnitude(UNITS.Quantity([finite(value)], source_units), target_units, 1)[0])


def active_resolutions(state):
    records = state.get("resolutions", {})
    superseded = {r["replaces"] for r in records.values() if r["replaces"] is not None}
    return {r["event"]: r for key, r in records.items() if key not in superseded}


def forecast_samples(run, binding):
    """Named empirical forecasts for exactly one bound definition/decision context."""
    entries = {"strategy:" + branch_registry(run)[key]["fork"]: run["samples"][key] for key in binding["branches"]}
    if run.get("schema_version") == 1:
        if run["merged_samples"] is not None:
            entries["mixture"] = run["merged_samples"]
    elif binding["context_key"] in run["mixtures"]:
        entries["mixture"] = run["mixtures"][binding["context_key"]]["samples"]
    return entries


def score_resolution(run, binding, resolution, *, units=None, coverages=(.5, .8, .95)):
    require(binding["scope"] == resolution["forecast"]["scope"], "Forecast and outcome definitions, decisions, or query contexts differ.", "outcome_scope_mismatch")
    units = units or run["units"]
    outcome = converted(resolution["outcome"], resolution["units"], units)
    entries = forecast_samples(run, binding)
    scores = {key: empirical_score(magnitude(UNITS.Quantity(values, run["units"]), units, run["n"]), outcome, coverages)
              for key, values in entries.items()}
    retrospective = timestamp(run["created_at"]) >= timestamp(resolution["observed_at"])
    future_observation = timestamp(resolution["observed_at"]) > timestamp(resolution["recorded_at"])
    warnings = list(run["warnings"])
    if retrospective:
        warnings.append({"code": "forecast-after-outcome", "message": "Forecast was saved at or after the reported observation time; score is retrospective."})
    if future_observation:
        warnings.append({"code": "future-observation-time", "message": "The supplied observation time is later than evidence recording; review the timestamp and source."})
    return {"scorer": SCORER, "event": resolution["event"], "resolution_id": resolution["id"], "run_id": run["id"],
            "forecast": binding, "units": units, "outcome": outcome, "source": resolution["source"],
            "observed_at": resolution["observed_at"], "retrospective": retrospective, "future_observation": future_observation, "scores": scores,
            "quantile_method": "inverted_cdf", "score_direction": "lower is better", "warnings": warnings,
            "interpretation": "Scores evaluate the saved empirical distribution against supplied evidence; they do not establish source truth or calibration."}


def aggregate_cases(cases, coverages):
    """Use identical events for every compared method; never count branches as events."""
    if not cases:
        return {"n_events": 0, "n_groups": 0, "method_availability": {}, "matched_methods": {}}
    availability = {method: sum(method in case["score"]["scores"] for case in cases)
                    for case in cases for method in case["score"]["scores"]}
    methods = {}
    def average(values):
        return finite(float(np.mean(np.asarray(values, dtype=np.longdouble))), "Mean score")
    for method, count in sorted(availability.items()):
        if count != len(cases):
            continue
        rows = [case["score"]["scores"][method] for case in cases]
        methods[method] = {"n_events": count, "mean_crps": average([r["crps"] for r in rows]),
                           "mean_absolute_error": average([r["absolute_error"] for r in rows]),
                           "intervals": [{"nominal_coverage": p, "covered": sum(r["intervals"][i]["covered"] for r in rows),
                               "empirical_coverage": float(np.mean([r["intervals"][i]["covered"] for r in rows])),
                               "mean_width": average([r["intervals"][i]["width"] for r in rows]),
                               "mean_score": average([r["intervals"][i]["score"] for r in rows])} for i, p in enumerate(coverages)]}
    return {"n_events": len(cases), "n_groups": len({c["group"] for c in cases}), "method_availability": availability, "matched_methods": methods}
