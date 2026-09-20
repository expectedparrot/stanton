"""Outcome evidence and immutable evaluation cohorts over saved forecasts."""

from copy import deepcopy

from .common import finite, identifier, name, nonblank, now, require
from .expressions import unit
from .scoring import (
    SCORER,
    active_resolutions,
    aggregate_cases,
    converted,
    coverage_levels,
    forecast_binding,
    score_resolution,
    timestamp,
)


class EvaluationOperations:
    def resolve(self, target, outcome, *, event, run_id, units, source, observed_at, definition=None,
                decisions=None, reason="", replaces=None):
        name(event)
        nonblank(run_id, "Saved run ID")
        nonblank(source, "Outcome source")
        require(isinstance(reason, str), "Resolution reason must be text.")
        observed_at = timestamp(observed_at).isoformat()
        run = self.store.run(run_id, target)
        frozen, _ = self.store.read(run["revision"])
        forecast = forecast_binding(run, frozen, definition=definition, decisions=decisions)
        record = {"id": identifier("resolution"), "event": event, "forecast": forecast,
                  "outcome": converted(outcome, units, run["units"]), "units": run["units"],
                  "supplied_outcome": finite(outcome, "Outcome"), "supplied_units": units, "source": source,
                  "observed_at": observed_at, "reason": reason, "replaces": replaces, "recorded_at": now()}
        def mutate(state):
            for cohort in state.get("cohorts", {}).values():
                for member in cohort["members"]:
                    require(member["event"] != event or member["forecast"]["scope"] == forecast["scope"],
                            "Outcome does not match this event's registered cohort scope.", "outcome_scope_mismatch")
            current = active_resolutions(state).get(event)
            if current:
                require(replaces == current["id"], "Event already resolved; correcting evidence requires --replaces with its current resolution ID.", "duplicate_resolution")
                nonblank(reason, "Correction reason")
                require(forecast == current["forecast"], "A correction must retain the original forecast and outcome scope.")
            else:
                require(replaces is None, "Cannot replace a resolution for an unknown event.")
            state.setdefault("resolutions", {})[record["id"]] = record
            state["schema_version"] = 5
            return {"resolution": record}
        return self._edit("resolve", mutate)

    def resolution_show(self, event, *, resolution_id=None):
        state, revision = self.store.read()
        record = self._resolution(state, event, resolution_id)
        return {"revision": revision, "resolution": record,
                "current_resolution_id": active_resolutions(state)[event]["id"],
                "history": [r for r in state["resolutions"].values() if r["event"] == event]}

    @staticmethod
    def _resolution(state, event, resolution_id=None):
        record = state.get("resolutions", {}).get(resolution_id) if resolution_id else active_resolutions(state).get(event)
        require(record is not None and record["event"] == event, "Unknown event or resolution.", "not_found")
        return record

    def score(self, event, *, resolution_id=None, run_id=None, units=None, coverages=(.5, .8, .95)):
        state, revision = self.store.read()
        resolution = self._resolution(state, event, resolution_id)
        original = resolution["forecast"]
        run = self.store.run(run_id or original["run_id"])
        frozen, _ = self.store.read(run["revision"])
        bound = forecast_binding(run, frozen, definition=original["definition"], decisions=original["decisions"])
        return {"working_revision": revision, **score_resolution(run, bound, resolution, units=units, coverages=coverages)}

    def cohort_define(self, cohort, members, *, units, reason, coverages=(.5, .8, .95)):
        name(cohort)
        nonblank(reason, "Cohort selection reason")
        unit(units)
        levels = coverage_levels(coverages)
        require(isinstance(members, list) and 1 <= len(members) <= 1000, "Cohort needs 1–1000 members.")
        bound = []
        for member in members:
            require(isinstance(member, dict) and set(member) <= {"event", "run_id", "group", "split", "definition", "decisions"}, "Invalid cohort member fields.")
            name(member.get("event"))
            name(member.get("group"))
            require(member.get("split") in {"train", "test"}, "Every member needs a train or test split.")
            require(member.get("run_id"), "Every member must reference a saved run ID.")
            run = self.store.run(member["run_id"])
            frozen, _ = self.store.read(run["revision"])
            forecast = forecast_binding(run, frozen, definition=member.get("definition"), decisions=member.get("decisions"))
            require(unit(run["units"]).is_compatible_with(unit(units)), "Cohort forecasts need compatible units.", "unit_mismatch")
            bound.append({"event": member["event"], "group": member["group"], "split": member["split"], "forecast": forecast})
        require(len({m["event"] for m in bound}) == len(bound), "Each event can appear only once in a cohort.")
        groups = {}
        for member in bound:
            require(member["group"] not in groups or groups[member["group"]] == member["split"], "Related-event groups cannot cross train/test splits.", "split_leakage")
            groups[member["group"]] = member["split"]
        def mutate(state):
            require(cohort not in state.get("cohorts", {}), "Cohort name already exists; register a new cohort to change membership.")
            outcomes = active_resolutions(state)
            for member in bound:
                outcome = outcomes.get(member["event"])
                require(outcome is None or member["forecast"]["scope"] == outcome["forecast"]["scope"], "Cohort member has a different outcome scope.", "outcome_scope_mismatch")
                member["resolution_at_registration"] = outcome["id"] if outcome else None
            record = {"id": identifier("cohort"), "name": cohort, "units": units, "reason": reason, "members": bound,
                      "coverages": levels, "created_at": now()}
            state.setdefault("cohorts", {})[cohort] = record
            state["schema_version"] = 5
            return {"cohort": record}
        return self._edit("cohort_define", mutate)

    def cohort_show(self, cohort, *, revision=None):
        state, revision = self.store.read(revision)
        require(cohort in state.get("cohorts", {}), "Unknown cohort.", "not_found")
        return {"revision": revision, "cohort": state["cohorts"][cohort]}

    def cohort_evaluate(self, cohort, *, revision=None, include_retrospective=False):
        require(type(include_retrospective) is bool, "Retrospective inclusion must be explicit.")
        state, revision = self.store.read(revision)
        require(cohort in state.get("cohorts", {}), "Unknown cohort.", "not_found")
        record = state["cohorts"][cohort]
        outcomes = active_resolutions(state)
        results = []
        for member in record["members"]:
            entry = deepcopy(member)
            resolution = outcomes.get(member["event"])
            if resolution is None:
                entry["status"] = "unresolved"
            else:
                run = self.store.run(member["forecast"]["run_id"])
                scored = score_resolution(run, member["forecast"], resolution, units=record["units"], coverages=record["coverages"])
                status = ("excluded_future_observation" if scored["future_observation"] else
                          "excluded_retrospective" if scored["retrospective"] and not include_retrospective else "scored")
                entry.update(status=status, score=scored,
                             registration_after_observation=timestamp(record["created_at"]) >= timestamp(resolution["observed_at"]))
            results.append(entry)
        splits = {}
        for split in ("train", "test"):
            members = [r for r in results if r["split"] == split]
            included = [r for r in members if r["status"] == "scored"]
            splits[split] = {"registered": len(members), "unresolved": sum(r["status"] == "unresolved" for r in members),
                             "excluded_retrospective": sum(r["status"] == "excluded_retrospective" for r in members),
                             "excluded_future_observation": sum(r["status"] == "excluded_future_observation" for r in members),
                             **aggregate_cases(included, record["coverages"])}
        return {"scorer": SCORER, "cohort": cohort, "cohort_id": record["id"], "revision": revision, "units": record["units"],
                "coverages": record["coverages"], "selection_reason": record["reason"],
                "include_retrospective": include_retrospective, "members": results, "splits": splits,
                "registered_with_known_outcomes": sum(m["resolution_at_registration"] is not None for m in record["members"]),
                "registered_after_observation": sum(m.get("registration_after_observation", False) for m in results),
                "interpretation": "Descriptive scores on fixed membership; train/test reports stay separate. Equal event weights, with related-group counts. Matched methods use the same scored events. No fitted calibration or independence guarantee."}
