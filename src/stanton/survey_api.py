"""Survey lifecycle operations; imports propose changes and review applies them."""

from copy import deepcopy

from .common import canonical, digest, identifier, name, nonblank, now, require
from .elicitation import (
    binding,
    instrument_digest,
    model_digest,
    normalize_response,
    proposal_value,
    response_template,
    select_slots,
)


def get_survey(state, survey):
    require(survey in state.get("surveys", {}), "Unknown survey.", "not_found")
    return state["surveys"][survey]


def require_current(state, instrument):
    require(model_digest(state) == instrument["model_sha256"],
            "Survey is stale: the model changed after drafting. Draft a new instrument; old responses remain available for audit.",
            "stale_survey")


class SurveyOperations:
    def survey_draft(self, survey, *, phase="targeted", budget=10, nodes=None, coverage=.8, reask=False):
        name(survey)
        frozen, revision = self.store.read()
        instrument = {"schema_version": 1, "id": identifier("survey"), "name": survey, "project_id": frozen["id"],
                      "model_revision": revision, "model_sha256": model_digest(frozen), "phase": phase,
                      "context": deepcopy(frozen["context"]),
                      "selection": "Explicit quantities" if nodes is not None else "Unasked decisions first in triage, then missing primitive estimates in name order; no sensitivity or VoI ranking.",
                      "slots": select_slots(frozen, phase=phase, budget=budget, nodes=nodes, coverage=coverage, reask=reask),
                      "created_at": now()}
        instrument["sha256"] = instrument_digest(instrument)
        def mutate(state):
            require_current(state, instrument)
            require(survey not in state.get("surveys", {}), "Survey name already exists; use a new name for a new instrument.")
            state.setdefault("surveys", {})[survey] = {"instrument": instrument, "responses": {}, "proposals": {}}
            state["schema_version"] = 4
            return {"instrument": instrument, "response_template": response_template(instrument)}
        return self._edit("survey_draft", mutate)

    def survey_show(self, survey):
        state, revision = self.store.read()
        record = get_survey(state, survey)
        instrument = record["instrument"]
        return {"revision": revision, "instrument": instrument, "stale": model_digest(state) != instrument["model_sha256"],
                "response_template": response_template(instrument), "responses": len(record["responses"]),
                "proposals": {status: sum(p["status"] == status for p in record["proposals"].values())
                              for status in ("pending", "applied", "rejected")}}

    def survey_compile(self, survey):
        from .edsl_bridge import compile_instrument
        state, _ = self.store.read()
        instrument = get_survey(state, survey)["instrument"]
        require_current(state, instrument)
        return compile_instrument(instrument)

    def survey_ingest(self, survey, payload, *, source, format="responses", respondent_kind=None):
        nonblank(source, "Response source")
        require(format in {"responses", "edsl"}, "Unknown response format.")
        require(isinstance(payload, dict), "Responses must be a JSON object.")
        require(len(canonical(payload).encode()) <= 20_000_000, "Response import exceeds 20 MB; split the batch.")
        def mutate(state):
            record = get_survey(state, survey)
            instrument = record["instrument"]
            require_current(state, instrument)
            if format == "edsl":
                from .edsl_bridge import normalize_results
                rows = normalize_results(instrument, payload, respondent_kind)
            else:
                require(respondent_kind is None, "Respondent kind belongs in each portable response row.")
                require(payload.get("schema_version") == 1 and all(payload.get(k) == v for k, v in binding(instrument).items()),
                        "Response bundle does not match the frozen instrument and model revision.", "response_mismatch")
                rows = payload.get("responses")
            require(isinstance(rows, list) and 1 <= len(rows) <= 1000, "Import 1–1000 response rows per batch.")
            response_ids, proposal_ids = [], []
            for raw in rows:
                normalized = normalize_response(instrument, raw)
                response_id = normalized["id"]
                require(response_id not in record["responses"], "Duplicate respondent and iteration for this instrument.", "duplicate_response")
                received = now()
                response = {**normalized, "raw": deepcopy(raw), "raw_sha256": digest(raw), "format": format,
                            "source": source, "received_at": received}
                record["responses"][response_id] = response
                response_ids.append(response_id)
                for slot_id, answer in normalized["answers"].items():
                    value = proposal_value(instrument["slots"][slot_id], answer)
                    if value is None:
                        continue
                    proposal_id = "proposal_" + digest([response_id, slot_id])[:32]
                    record["proposals"][proposal_id] = {"id": proposal_id, "response_id": response_id, "slot_id": slot_id,
                        "value": value, "status": "pending", "created_at": received}
                    proposal_ids.append(proposal_id)
            return {"survey": survey, "response_ids": response_ids, "proposal_ids": proposal_ids,
                    "model_changed": False, "next": "Inspect survey review, then apply selected proposals together."}
        return self._edit("survey_ingest", mutate)

    def survey_review(self, survey):
        state, revision = self.store.read()
        record = get_survey(state, survey)
        conflicts = {}
        for proposal in record["proposals"].values():
            if proposal["status"] == "pending":
                conflicts.setdefault(proposal["slot_id"], []).append(proposal["id"])
        return {"revision": revision, "survey": survey, "instrument": record["instrument"],
                "stale": model_digest(state) != record["instrument"]["model_sha256"],
                "responses": record["responses"], "proposals": record["proposals"],
                "conflicts": {slot: ids for slot, ids in conflicts.items() if len(ids) > 1},
                "interpretation": "Respondents and repeated iterations are retained separately. Synthetic responses are uncalibrated; no automatic pooling or interval widening."}

    def survey_apply(self, survey, proposals, *, reason):
        return self._review_proposals(survey, proposals, reason, apply=True)

    def survey_reject(self, survey, proposals, *, reason):
        return self._review_proposals(survey, proposals, reason, apply=False)

    def _review_proposals(self, survey, proposals, reason, *, apply):
        nonblank(reason, "Review reason")
        def mutate(state):
            record = get_survey(state, survey)
            instrument = record["instrument"]
            if apply:
                require_current(state, instrument)
            selected = ([key for key, p in record["proposals"].items() if p["status"] == "pending"]
                        if proposals == "all" else proposals)
            require(isinstance(selected, (list, tuple)) and selected and len(set(selected)) == len(selected), "Select distinct proposal IDs or all.")
            require(set(selected) <= record["proposals"].keys(), "Unknown proposal.", "not_found")
            pending = [record["proposals"][key] for key in selected]
            require(all(p["status"] == "pending" for p in pending), "Only pending proposals can be reviewed.", "duplicate_review")
            if apply:
                require(len({p["slot_id"] for p in pending}) == len(pending), "Conflicting responses: choose only one proposal per slot. No automatic pooling.", "conflicting_proposals")
            for proposal in pending:
                proposal.update(status="applied" if apply else "rejected", review_reason=reason, reviewed_at=now())
                if not apply:
                    continue
                slot = instrument["slots"][proposal["slot_id"]]
                node = slot["node"]
                response = record["responses"][proposal["response_id"]]
                respondent = response["respondent"]
                provenance = {"survey": survey, "instrument_id": instrument["id"], "instrument_sha256": instrument["sha256"],
                              "model_revision": instrument["model_revision"], "response_id": response["id"],
                              "proposal_id": proposal["id"], "respondent": respondent, "iteration": response["iteration"],
                              "calibrated": False}
                value = proposal["value"]
                if value["kind"] == "decision":
                    written = state["decisions"][node]
                    written.update(status="open" if value["leave_open"] else "selected", selected=value["option"],
                                   reason=reason, elicitation=provenance)
                else:
                    old = state["estimates"].get(node)
                    answer = response["answers"][slot["id"]]
                    written = {"id": identifier("estimate"), "quantity": node, "distribution": value["distribution"],
                               "source": f"{response['source']}; respondent {respondent['id']} ({respondent['kind']})",
                               "reason": reason, "method": "survey", "assumes": [], "kind": "epistemic",
                               "note": answer["reason"], "asof": None, "ancestry": [response["id"]],
                               "anchor_kind": None, "recorded_at": now(), "previous": old["id"] if old else None,
                               "elicitation": provenance}
                    if slot["source_definition"]:
                        written.update(definition_id=slot["previous_estimate"]["definition_id"],
                                       definition_revision=slot["source_definition"]["id"])
                    state["estimates"][node] = written
                proposal["write_back"] = deepcopy(written)
            return {"survey": survey, "proposal_ids": list(selected), "status": "applied" if apply else "rejected",
                    "model_changed": apply}
        return self._edit("survey_apply" if apply else "survey_reject", mutate)
