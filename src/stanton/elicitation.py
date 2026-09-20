"""Frozen instruments, typed responses, and reviewable model proposals."""

from copy import deepcopy

from .common import digest, finite, name, nonblank, require
from .distributions import Distribution
from .expressions import UNITS, unit

RESPONSE_KINDS = {"asker", "human_panel", "llm_panel"}
SHAPES = {"linear": "normal", "log": "lognormal", "logit": "logitnormal"}
MODEL_EXCLUSIONS = {"schema_version", "surveys", "notes", "resolutions", "cohorts", "calibrations", "research_reviews", "issued_reports"}


def model_digest(state):
    """Survey administration and notes do not change the frozen numerical model."""
    return digest({key: value for key, value in state.items() if key not in MODEL_EXCLUSIONS})


def instrument_digest(instrument):
    return digest({key: value for key, value in instrument.items() if key != "sha256"})


def slot_for(state, node, coverage):
    require(node in state["quantities"], f"Unknown survey quantity: {node}", "not_found")
    quantity = state["quantities"][node]
    decision = state.get("decisions", {}).get(node)
    require(not quantity.get("process") and not any(node in graph for graph in state["graphs"].values()),
            f"Survey slot {node} must be a primitive quantity or decision.")
    require(not state.get("conditional_estimates", {}).get(node), "Conditional estimate elicitation is not supported; use an explicit conditional estimate.")
    kind = "decision" if decision else "leaf"
    previous = state["estimates"].get(node)
    source_definition = state.get("definitions", {}).get(previous.get("definition_id")) if previous else None
    return {"id": kind + "__" + node, "kind": kind, "node": node, "quantity": deepcopy(quantity),
            "decision": deepcopy(decision), "previous_estimate": deepcopy(previous), "source_definition": deepcopy(source_definition),
            "coverage": coverage, "shape": SHAPES[quantity["space"]]}


def select_slots(state, *, phase, budget, nodes, coverage, reask):
    require(phase in {"triage", "targeted"}, "Unknown survey phase.")
    require(type(budget) is int and 1 <= budget <= 100, "Survey budget must be 1–100 model slots.")
    require(0 < finite(coverage, "Coverage") < 1, "Coverage must lie between zero and one.")
    if nodes is not None:
        require(isinstance(nodes, (list, tuple)) and nodes and len(set(nodes)) == len(nodes), "Select distinct quantity names.")
        require(len(nodes) <= budget, "Explicit quantities exceed the slot budget.")
        slots = [slot_for(state, node, coverage) for node in nodes]
    else:
        decisions, leaves = [], []
        for node in sorted(state["quantities"]):
            quantity = state["quantities"][node]
            if quantity.get("process") or any(node in graph for graph in state["graphs"].values()):
                continue
            if node in state.get("decisions", {}):
                if phase == "triage" and state["decisions"][node]["status"] == "unasked":
                    decisions.append(slot_for(state, node, coverage))
            elif node not in state["estimates"] and not state.get("conditional_estimates", {}).get(node):
                leaves.append(slot_for(state, node, coverage))
        slots = decisions + leaves
        if not reask:
            unknown = set()
            for survey in state.get("surveys", {}).values():
                for response in survey["responses"].values():
                    for key, answer in response["answers"].items():
                        if answer["status"] == "unknown":
                            unknown.add(digest(survey["instrument"]["slots"][key]))
            slots = [slot for slot in slots if digest(slot) not in unknown]
        slots = slots[:budget]
    require(slots, "No eligible slots. Use explicit --nodes to revisit estimates or --reask to revisit recorded unknowns.", "no_open_slots")
    return {slot["id"]: slot for slot in slots}


def binding(instrument):
    return {"project_id": instrument["project_id"], "instrument_id": instrument["id"],
            "instrument_sha256": instrument["sha256"], "model_revision": instrument["model_revision"],
            "model_sha256": instrument["model_sha256"]}


def response_template(instrument):
    return {"schema_version": 1, **binding(instrument), "responses": [
        {"respondent": {"id": "replace_with_respondent_id", "kind": "asker"}, "iteration": 0,
         "answers": {key: {"status": "unanswered", "reason": ""} for key in instrument["slots"]}}]}


def normalize_answer(slot, answer):
    require(isinstance(answer, dict), "Each slot answer must be an object.")
    status = answer.get("status")
    allowed = {"unknown", "unanswered", "choice", "open"} if slot["kind"] == "decision" else {"unknown", "unanswered", "point", "interval"}
    require(status in allowed, f"Invalid response status for {slot['id']}.")
    fields = {"status", "reason"}
    fields |= {"value", "units"} if status == "point" else {"low", "high", "units"} if status == "interval" else {"option"} if status == "choice" else set()
    require(set(answer) <= fields, f"Unexpected answer fields for {slot['id']}; skipped answers cannot carry values.")
    reason = answer.get("reason", "")
    require(isinstance(reason, str), "Answer reason must be text.")
    if status in {"unknown", "open"}:
        nonblank(reason, "Unknown/open response reason")
    result = {"status": status, "reason": reason}
    if status == "choice":
        require(answer.get("option") in slot["decision"]["options"], "Unknown decision option.")
        result["option"] = answer["option"]
    elif status in {"point", "interval"}:
        source_units = nonblank(answer.get("units"), "Answer units")
        target_units = slot["quantity"]["units"]
        require(unit(source_units).is_compatible_with(unit(target_units)), "Response units do not match the slot.", "unit_mismatch")
        for key in (["value"] if status == "point" else ["low", "high"]):
            value = finite(answer.get(key), "Answer " + key)
            result[key] = finite(UNITS.Quantity(value, source_units).to(target_units).magnitude)
        result["units"] = target_units
        if status == "interval":
            Distribution.from_interval(result["low"], result["high"], slot["coverage"], slot["shape"])
    return result


def proposal_value(slot, answer):
    status = answer["status"]
    if status in {"unknown", "unanswered"}:
        return None
    if status in {"open", "choice"}:
        return {"kind": "decision", "option": answer.get("option"), "leave_open": status == "open"}
    dist = (Distribution.from_point(answer["value"]) if status == "point" else
            Distribution.from_interval(answer["low"], answer["high"], slot["coverage"], slot["shape"]))
    return {"kind": "estimate", "distribution": dist.to_dict(), "units": slot["quantity"]["units"],
            "interpretation": "Respondent-supplied estimate; coverage and source accuracy are unverified."}


def normalize_response(instrument, raw):
    require(isinstance(raw, dict) and set(raw) <= {"respondent", "iteration", "answers", "provenance"}, "Invalid response row.")
    respondent = raw.get("respondent")
    require(isinstance(respondent, dict) and respondent.get("kind") in RESPONSE_KINDS, "Respondent needs an id and kind: asker, human_panel, or llm_panel.")
    respondent_id = nonblank(respondent.get("id"), "Respondent id")
    require(respondent_id == respondent["id"], "Respondent id must not have surrounding whitespace.")
    iteration = raw.get("iteration", 0)
    require(type(iteration) is int and iteration >= 0, "Response iteration must be a nonnegative integer.")
    answers = raw.get("answers")
    require(isinstance(answers, dict) and answers.keys() <= instrument["slots"].keys(), "Response contains unknown slot bindings.")
    normalized = {key: normalize_answer(slot, answers.get(key, {"status": "unanswered"}))
                  for key, slot in instrument["slots"].items()}
    response_id = "response_" + digest([instrument["id"], respondent["id"], iteration])[:32]
    return {"id": response_id, "respondent": deepcopy(respondent), "iteration": iteration, "answers": normalized}


def validate_surveys(state):
    registry = state.get("surveys", {})
    require(isinstance(registry, dict), "Survey registry must be an object.")
    for key, survey in registry.items():
        name(key)
        instrument = survey["instrument"]
        require(instrument["schema_version"] == 1 and instrument["name"] == key and instrument["project_id"] == state["id"], "Invalid instrument identity.")
        require(type(instrument["model_revision"]) is int and instrument["model_revision"] > 0, "Invalid instrument model revision.")
        require(instrument_digest(instrument) == instrument["sha256"], "Instrument digest mismatch.", "integrity_error")
        require(instrument["phase"] in {"triage", "targeted"} and 1 <= len(instrument["slots"]) <= 100, "Invalid instrument slots.")
        for slot_id, slot in instrument["slots"].items():
            require(slot["kind"] in {"leaf", "decision"} and slot_id == slot["id"] == slot["kind"] + "__" + slot["node"], "Invalid slot identity.")
            require(slot["node"] == slot["quantity"]["name"] and slot["node"] in state["quantities"], "Invalid bound quantity.")
            require(slot["shape"] == SHAPES[slot["quantity"]["space"]] and 0 < finite(slot["coverage"]) < 1, "Invalid interval contract.")
            unit(slot["quantity"]["units"])
        expected_proposals = {}
        for response_id, response in survey["responses"].items():
            require(response["format"] in {"responses", "edsl"}, "Unknown stored response format.")
            if response["format"] == "edsl":
                from .edsl_bridge import normalize_results, question_spec
                provenance = response["raw"]["provenance"]
                reconstructed = {"edsl_class_name": "Results", "edsl_version": provenance["edsl_version"],
                                 "survey": {"questions": question_spec(instrument)[0]}, "data": [provenance["raw_result"]]}
                require(normalize_results(instrument, reconstructed, response["respondent"]["kind"])[0] == response["raw"],
                        "Stored response differs from raw EDSL answers.")
            normalized = normalize_response(instrument, response["raw"])
            require(response_id == response["id"] == normalized["id"] and all(response[k] == v for k, v in normalized.items()), "Response normalization mismatch.")
            require(response["raw_sha256"] == digest(response["raw"]), "Raw response digest mismatch.", "integrity_error")
            nonblank(response["source"], "Response source")
            for slot_id, answer in response["answers"].items():
                value = proposal_value(instrument["slots"][slot_id], answer)
                if value is not None:
                    proposal_id = "proposal_" + digest([response_id, slot_id])[:32]
                    expected_proposals[proposal_id] = (response_id, slot_id, value)
        require(set(expected_proposals) == set(survey["proposals"]), "Proposal registry mismatch.")
        for proposal_id, (response_id, slot_id, value) in expected_proposals.items():
            proposal = survey["proposals"][proposal_id]
            require(proposal["id"] == proposal_id and proposal["response_id"] == response_id and
                    proposal["slot_id"] == slot_id and proposal["value"] == value, "Proposal does not match its response.")
            require(proposal["status"] in {"pending", "applied", "rejected"}, "Unknown proposal status.")
            if proposal["status"] != "pending":
                nonblank(proposal["review_reason"], "Proposal review reason")
            if proposal["status"] == "applied":
                require(isinstance(proposal.get("write_back"), dict), "Applied proposal lacks its write-back record.")
                written = proposal["write_back"]
                if value["kind"] == "estimate":
                    require(written["distribution"] == value["distribution"] and written["elicitation"]["proposal_id"] == proposal_id,
                            "Written estimate does not match its proposal.")
                else:
                    require(written["selected"] == value["option"] and written["status"] == ("open" if value["leave_open"] else "selected"),
                            "Written decision does not match its proposal.")
    for records in (state["estimates"], state.get("decisions", {})):
        for record in records.values():
            reference = record.get("elicitation")
            if reference:
                require(reference["survey"] in registry, "Elicited value references an unknown survey.")
                survey = registry[reference["survey"]]
                proposal = survey["proposals"].get(reference["proposal_id"])
                require(proposal is not None and proposal["status"] == "applied" and proposal["write_back"] == record,
                        "Elicited value does not match its applied proposal.")


def validate_survey_history(states):
    """Check instrument bindings against actual archived revisions and transitions."""
    previous = {}
    for revision, state in enumerate(states, 1):
        surveys = state.get("surveys", {})
        require(previous.keys() <= surveys.keys(), "Historical surveys were removed.")
        for key, survey in surveys.items():
            instrument = survey["instrument"]
            origin = instrument["model_revision"]
            require(origin < revision, "Instrument must refer to an earlier model revision.")
            frozen = states[origin - 1]
            require(model_digest(frozen) == instrument["model_sha256"] and instrument["context"] == frozen["context"],
                    "Instrument does not match its archived model revision.")
            require(all(slot == slot_for(frozen, slot["node"], slot["coverage"]) for slot in instrument["slots"].values()),
                    "Instrument slot differs from its archived quantity or decision.")
            before = previous.get(key)
            if before is None:
                require(not survey["responses"] and not survey["proposals"], "A new instrument cannot already contain responses.")
                continue
            require(before["instrument"] == instrument, "An issued instrument was changed.")
            require(before["responses"].keys() <= survey["responses"].keys() and
                    all(survey["responses"][rid] == response for rid, response in before["responses"].items()), "Historical responses were changed.")
            require(before["proposals"].keys() <= survey["proposals"].keys(), "Historical proposals were removed.")
            if before["responses"].keys() != survey["responses"].keys():
                require(model_digest(states[revision - 2]) == instrument["model_sha256"], "Responses were ingested into a stale model.")
            for pid, proposal in survey["proposals"].items():
                old = before["proposals"].get(pid)
                if old is None:
                    require(proposal["status"] == "pending", "Imported proposals must start pending.")
                elif old["status"] != "pending":
                    require(old == proposal, "Reviewed proposals were changed.")
                elif proposal["status"] == "applied":
                    require(model_digest(states[revision - 2]) == instrument["model_sha256"], "Proposal was applied to a stale model.")
                    slot = instrument["slots"][proposal["slot_id"]]
                    written = state["decisions" if slot["kind"] == "decision" else "estimates"][slot["node"]]
                    require(written == proposal["write_back"], "Applied proposal did not write the recorded model value.")
        previous = surveys
