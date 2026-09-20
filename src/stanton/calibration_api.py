"""Immutable fitted artifacts and explicit overlays on saved forecasts."""

from .calibration import DEFAULT_SCALES, eligibility, fit_data, method_samples, spread
from .common import digest, identifier, name, nonblank, now, require
from .sampling import summary
from .scoring import active_resolutions, aggregate_cases, converted, empirical_score, forecast_binding, timestamp


class CalibrationOperations:
    def calibration_fit(self, calibration, *, cohort, method, reason, scales=DEFAULT_SCALES,
                        include_retrospective=False):
        name(calibration)
        nonblank(reason, "Calibration selection reason")
        state, revision = self.store.read()
        fitted = fit_data(state, revision, self.store.run, cohort, method, scales, include_retrospective)
        record = {"id": identifier("calibration"), "name": calibration, "reason": reason, "created_at": now(), **fitted}
        def mutate(current):
            require(digest(current) == digest(state), "Project changed during calibration fitting; retry.", "stale_revision")
            require(calibration not in current.get("calibrations", {}), "Calibration already exists; fit under a new name.")
            current.setdefault("calibrations", {})[calibration] = record
            current["schema_version"] = 6
            return {"calibration": record}
        return self._edit("calibration_fit", mutate)

    def calibration_show(self, calibration, *, revision=None):
        state, revision = self.store.read(revision)
        require(calibration in state.get("calibrations", {}), "Unknown calibration.", "not_found")
        return {"revision": revision, "calibration": state["calibrations"][calibration]}

    def calibration_apply(self, calibration, *, run_id, reason, definition=None, decisions=None):
        nonblank(reason, "Application reason")
        artifact = self.calibration_show(calibration)["calibration"]
        run = self.store.run(run_id)
        state, _ = self.store.read(run["revision"])
        bound = forecast_binding(run, state, definition=definition, decisions=decisions)
        # Validate compatible units, but retain the saved forecast's units in the overlay.
        converted(0, run["units"], artifact["units"])
        raw = method_samples(run, bound, artifact["method"], run["units"])
        adjusted = spread(raw, artifact["scale"])
        target_bound = state["bounds"].get(run["target"])
        support = None
        warnings = list(run["warnings"])
        if target_bound:
            support = {"bound": target_bound,
                       "below": int(sum(adjusted < target_bound["lower"])) if target_bound["lower"] is not None else 0,
                       "above": int(sum(adjusted > target_bound["upper"])) if target_bound["upper"] is not None else 0}
            if support["below"] or support["above"]:
                warnings.append({"code": "adjusted-bound-violation", "message": "Adjusted draws violate saved target bounds; no clipping was applied."})
        body = {"schema_version": 1, "calibration": artifact, "calibration_sha256": digest(artifact),
                "forecast": bound, "reason": reason, "units": run["units"], "method": artifact["method"],
                "raw_samples": raw.tolist(), "adjusted_samples": adjusted.tolist(),
                "raw_summary": summary(raw), "adjusted_summary": summary(adjusted),
                "target_support": support, "warnings": warnings,
                "interpretation": "Explicit scalar output overlay. Original run is unchanged. Linear spread scaling does not enforce model bounds or joint constraints; inspect support before use. Transfer to this forecast is a supplied modeling judgment, not a calibration guarantee."}
        return {**body, "sha256": digest(body)}

    def calibration_evaluate(self, calibration, *, revision=None):
        state, revision = self.store.read(revision)
        artifact = self.calibration_show(calibration, revision=revision)["calibration"]
        bank = state["cohorts"][artifact["cohort"]]
        outcomes = active_resolutions(state)
        known_before_fit = {r["event"] for r in state.get("resolutions", {}).values()
                            if timestamp(r["recorded_at"]) <= timestamp(artifact["created_at"])}
        results = []
        for member in bank["members"]:
            # Training scores use the exact evidence used to fit, even after corrections.
            evidence = next((e for e in artifact["training_evidence"] if e["event"] == member["event"]), None)
            resolution = (state["resolutions"].get(evidence["resolution_id"]) if evidence else outcomes.get(member["event"]))
            run = self.store.run(member["forecast"]["run_id"])
            status = evidence["status"] if evidence else eligibility(run, resolution, artifact["include_retrospective"])
            entry = {**member, "status": status, "resolution_id": resolution["id"] if resolution else None}
            if resolution:
                entry["observation_before_fit"] = timestamp(resolution["observed_at"]) <= timestamp(artifact["created_at"])
                entry["evidence_before_fit"] = member["event"] in known_before_fit
                entry["registration_after_observation"] = timestamp(bank["created_at"]) >= timestamp(resolution["observed_at"])
            if status == "scored":
                raw = method_samples(run, member["forecast"], artifact["method"], artifact["units"])
                outcome = converted(resolution["outcome"], resolution["units"], artifact["units"])
                entry["score"] = {"scores": {
                    "raw": empirical_score(raw, outcome, bank["coverages"]),
                    "adjusted": empirical_score(spread(raw, artifact["scale"]), outcome, bank["coverages"])}}
            results.append(entry)
        splits = {}
        for split in ("train", "test"):
            members = [e for e in results if e["split"] == split]
            splits[split] = {"registered": len(members),
                             **{status: sum(e["status"] == status for e in members) for status in
                                ("unresolved", "excluded_retrospective", "excluded_future_observation")},
                             "observations_before_fit": sum(e.get("observation_before_fit", False) for e in members),
                             "evidence_before_fit": sum(e.get("evidence_before_fit", False) for e in members),
                             **aggregate_cases([e for e in members if e["status"] == "scored"], bank["coverages"])}
        return {"calibration": artifact, "calibration_sha256": digest(artifact), "revision": revision,
                "units": artifact["units"], "coverages": bank["coverages"], "members": results, "splits": splits,
                "interpretation": "Raw and adjusted forecasts use identical events. Training evidence is pinned; test evidence is current at the selected revision and never used by the fitter. Test outcomes observed before fitting are post-hoc diagnostics. Repeated artifact selection using test scores can invalidate a holdout interpretation."}
