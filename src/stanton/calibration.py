"""Explicit, reproducible spread fitting on a fixed training cohort."""

import numpy as np

from .common import digest, finite, require
from .expressions import UNITS, magnitude
from .scoring import active_resolutions, converted, empirical_score, forecast_samples, timestamp

ENGINE = "stanton.calibration.grid_spread.v1"
DEFAULT_SCALES = (.25, .5, .75, 1, 1.25, 1.5, 2, 3, 4)


def scale_grid(values):
    require(isinstance(values, (list, tuple)) and 1 <= len(values) <= 100, "Supply 1–100 candidate scales.")
    scales = sorted(finite(v, "Scale") for v in values)
    require(len(set(scales)) == len(scales) and scales[0] > 0 and 1 in scales,
            "Scales must be distinct, positive, and include the unadjusted scale 1.")
    require(scales[-1] <= np.sqrt(np.finfo(float).max), "Scale squared must be finite.")
    return scales


def spread(values, scale):
    values = np.asarray(values, dtype=float)
    require(values.ndim == 1 and values.size and np.all(np.isfinite(values)), "Invalid calibration samples.")
    center = np.quantile(values, .5, method="inverted_cdf")
    # Extended precision avoids overflow in the intermediate subtraction.
    adjusted = (np.longdouble(center) + np.longdouble(scale) * (values.astype(np.longdouble) - center)).astype(float)
    require(np.all(np.isfinite(adjusted)), "Calibration produced nonfinite samples.")
    return adjusted


def method_samples(run, binding, method, units):
    entries = forecast_samples(run, binding)
    require(method in entries, f"Saved forecast lacks selected method: {method}", "missing_method")
    return magnitude(UNITS.Quantity(entries[method], run["units"]), units, run["n"])


def eligibility(run, resolution, include_retrospective):
    if resolution is None:
        return "unresolved"
    if timestamp(resolution["observed_at"]) > timestamp(resolution["recorded_at"]):
        return "excluded_future_observation"
    if timestamp(run["created_at"]) >= timestamp(resolution["observed_at"]) and not include_retrospective:
        return "excluded_retrospective"
    return "scored"


def fit_data(state, revision, get_run, cohort, method, scales, include_retrospective):
    """Read only training members' forecasts and outcomes; never score test data."""
    require(cohort in state.get("cohorts", {}), "Unknown cohort.", "not_found")
    require(type(include_retrospective) is bool, "Retrospective inclusion must be explicit.")
    require(isinstance(method, str) and (method == "mixture" or method.startswith("strategy:")), "Select mixture or strategy:<name>.")
    scales = scale_grid(scales)
    bank = state["cohorts"][cohort]
    outcomes = active_resolutions(state)
    evidence, cases = [], []
    for member in bank["members"]:
        if member["split"] != "train":
            continue
        run = get_run(member["forecast"]["run_id"])
        resolution = outcomes.get(member["event"])
        status = eligibility(run, resolution, include_retrospective)
        evidence.append({"event": member["event"], "group": member["group"], "forecast": member["forecast"],
                         "status": status, "resolution_id": resolution["id"] if resolution else None,
                         "resolution_sha256": digest(resolution) if resolution else None})
        if status == "scored":
            values = method_samples(run, member["forecast"], method, bank["units"])
            outcome = converted(resolution["outcome"], resolution["units"], bank["units"])
            cases.append((values, outcome))
    require(cases, "No eligible resolved training events.", "empty_training_set")
    require(any(np.any(values != values[0]) for values, _ in cases),
            "Spread cannot be fitted to only point forecasts.", "unidentified_calibration")
    candidates = [{"scale": scale, "mean_crps": finite(float(np.mean([
        empirical_score(spread(values, scale), outcome, bank["coverages"])["crps"]
        for values, outcome in cases], dtype=np.longdouble)), "Training mean CRPS")} for scale in scales]
    # Exact ties prefer no adjustment, then the nearest scale and the smaller value.
    best = min(candidates, key=lambda row: (row["mean_crps"], abs(row["scale"] - 1), row["scale"]))
    return {"engine": ENGINE, "training_revision": revision, "cohort": cohort, "cohort_id": bank["id"],
            "method": method, "units": bank["units"], "space": "linear", "center": "empirical_median_inverted_cdf",
            "objective": "equal_event_mean_crps", "scales": scales, "candidates": candidates, "scale": best["scale"],
            "variance_multiplier": finite(best["scale"] ** 2, "Variance multiplier"),
            "include_retrospective": include_retrospective, "training_evidence": evidence,
            "n_events": len(cases), "n_groups": len({e["group"] for e in evidence if e["status"] == "scored"}),
            "grid_boundary": best["scale"] in (scales[0], scales[-1])}
