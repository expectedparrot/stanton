"""Validate outcome evidence, frozen cohort bindings, and append-only history."""

from .common import finite, name, nonblank, require
from .expressions import unit
from .scoring import active_resolutions, converted, coverage_levels, forecast_binding, timestamp


def validate_evaluations(state):
    resolutions = state.get("resolutions", {})
    cohorts = state.get("cohorts", {})
    require(isinstance(resolutions, dict) and isinstance(cohorts, dict), "Evaluation registries must be objects.")
    successors = set()
    events = set()
    for key, record in resolutions.items():
        require(key == record["id"], "Resolution identity mismatch.")
        name(record["event"])
        events.add(record["event"])
        finite(record["outcome"], "Outcome")
        require(record["units"] == record["forecast"]["units"] and
                converted(record["supplied_outcome"], record["supplied_units"], record["units"]) == record["outcome"], "Resolution unit conversion mismatch.")
        nonblank(record["source"], "Outcome source")
        require(isinstance(record["reason"], str), "Resolution reason must be text.")
        timestamp(record["observed_at"])
        timestamp(record["recorded_at"])
        predecessor = record["replaces"]
        if predecessor is not None:
            require(predecessor in resolutions and predecessor not in successors and predecessor != key, "Invalid resolution correction chain.")
            previous = resolutions[predecessor]
            require(previous["event"] == record["event"] and previous["forecast"] == record["forecast"], "Correction changed the outcome binding.")
            require(timestamp(previous["recorded_at"]) <= timestamp(record["recorded_at"]), "Correction predates its predecessor.")
            nonblank(record["reason"], "Correction reason")
            successors.add(predecessor)
        seen = {key}
        while predecessor is not None:
            require(predecessor in resolutions and predecessor not in seen, "Cyclic resolution correction chain.")
            seen.add(predecessor)
            predecessor = resolutions[predecessor]["replaces"]
    require(len(resolutions) - len(successors) == len(events), "Each event must have one current resolution.")
    for key, record in cohorts.items():
        name(key)
        require(record["name"] == key, "Cohort identity mismatch.")
        nonblank(record["reason"], "Cohort reason")
        unit(record["units"])
        timestamp(record["created_at"])
        require(coverage_levels(record["coverages"]) == record["coverages"], "Invalid cohort interval contract.")
        members = record["members"]
        require(isinstance(members, list) and 1 <= len(members) <= 1000 and len({m["event"] for m in members}) == len(members), "Cohort must contain distinct events.")
        groups = {}
        for member in members:
            name(member["event"])
            name(member["group"])
            require(member["split"] in {"train", "test"}, "Unknown cohort split.")
            require(member["group"] not in groups or groups[member["group"]] == member["split"], "Related groups cross train/test splits.")
            groups[member["group"]] = member["split"]
            require(unit(member["forecast"]["units"]).is_compatible_with(unit(record["units"])), "Cohort has incompatible units.")
            known = member["resolution_at_registration"]
            if known:
                require(known in resolutions and resolutions[known]["event"] == member["event"], "Unknown registration-time resolution.")
            for resolution in resolutions.values():
                if resolution["event"] == member["event"]:
                    require(member["forecast"]["scope"] == resolution["forecast"]["scope"], "Cohort and resolution scopes differ.")


def validate_evaluation_history(states, runs):
    run_map = {run["id"]: run for run in runs}
    previous = {"resolutions": {}, "cohorts": {}}
    checked = set()

    def check_binding(bound, revision):
        require(bound["run_id"] in run_map, "Outcome or cohort references an unknown saved run.")
        run = run_map[bound["run_id"]]
        require(run["revision"] < revision, "Forecast must precede its resolution or cohort registration revision.")
        cache_key = (bound["run_sha256"], bound["context_key"])
        # Always compare metadata; cache only the expensive run hashing operation.
        if cache_key not in checked:
            expected = forecast_binding(run, states[run["revision"] - 1], definition=bound["definition"], decisions=bound["decisions"])
            checked.add(cache_key)
            expected_bindings[cache_key] = expected
        require(bound == expected_bindings[cache_key], "Frozen forecast binding does not match the saved run.")

    expected_bindings = {}
    for revision, state in enumerate(states, 1):
        for registry in ("resolutions", "cohorts"):
            records = state.get(registry, {})
            require(previous[registry].keys() <= records.keys(), "Evaluation history records were removed.")
            for key, record in records.items():
                if key in previous[registry]:
                    require(record == previous[registry][key], "An immutable evaluation record was changed.")
                    continue
                before = states[revision - 2] if revision > 1 else {}
                active = active_resolutions(before)
                if registry == "resolutions":
                    check_binding(record["forecast"], revision)
                    current = active.get(record["event"])
                    require(record["replaces"] == (current["id"] if current else None), "Resolution did not correct the current evidence.")
                    require(timestamp(record["forecast"]["created_at"]) <= timestamp(record["recorded_at"]), "Resolution predates its saved forecast.")
                else:
                    for member in record["members"]:
                        check_binding(member["forecast"], revision)
                        known = active.get(member["event"])
                        require(member["resolution_at_registration"] == (known["id"] if known else None), "Cohort registration hid an already known outcome.")
                        require(timestamp(member["forecast"]["created_at"]) <= timestamp(record["created_at"]), "Cohort predates its saved forecast.")
            previous[registry] = records
