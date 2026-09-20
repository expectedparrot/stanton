"""Validate immutable calibration evidence and reproduce the selected grid fit."""

from .calibration import ENGINE, fit_data, scale_grid
from .common import finite, name, nonblank, require
from .scoring import timestamp


def validate_calibrations(state):
    records = state.get("calibrations", {})
    require(isinstance(records, dict), "Calibrations must be an object.")
    for key, record in records.items():
        name(key)
        require(record["name"] == key and record["engine"] == ENGINE, "Invalid calibration identity or engine.")
        nonblank(record["id"], "Calibration ID")
        nonblank(record["reason"], "Calibration reason")
        timestamp(record["created_at"])
        require(record["cohort"] in state.get("cohorts", {}), "Unknown calibration cohort.")
        require(scale_grid(record["scales"]) == record["scales"] and record["scale"] in record["scales"], "Invalid fitted scale.")
        finite(record["variance_multiplier"])
        require(type(record["training_revision"]) is int and record["training_revision"] > 0, "Invalid training revision.")


def validate_artifact_history(states, runs):
    from .evaluation_validation import validate_evaluation_history
    validate_evaluation_history(states, runs)
    run_map = {run["id"]: run for run in runs}
    previous = {}
    for revision, state in enumerate(states, 1):
        records = state.get("calibrations", {})
        require(previous.keys() <= records.keys(), "Calibration history was removed.")
        for key, record in records.items():
            if key in previous:
                require(record == previous[key], "An immutable calibration was changed.")
                continue
            require(record["training_revision"] == revision - 1, "Calibration must use the preceding project revision.")
            expected = fit_data(states[revision - 2], revision - 1, run_map.__getitem__, record["cohort"],
                                record["method"], record["scales"], record["include_retrospective"])
            require(record == {**expected, **{k: record[k] for k in ("id", "name", "reason", "created_at")}},
                    "Calibration fit or training evidence does not match saved history.")
            bank = state["cohorts"][record["cohort"]]
            require(timestamp(record["created_at"]) >= timestamp(bank["created_at"]), "Calibration predates its cohort.")
            for evidence in record["training_evidence"]:
                if evidence["resolution_id"]:
                    resolution = state["resolutions"][evidence["resolution_id"]]
                    require(timestamp(record["created_at"]) >= timestamp(resolution["recorded_at"]), "Calibration predates training evidence.")
        previous = records
