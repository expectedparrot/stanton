"""Optional native EDSL compilation and strict, offline Results normalization."""

import contextlib
import sys
from copy import deepcopy

from .common import StantonError, require
from .elicitation import RESPONSE_KINDS, binding


def question_spec(instrument):
    questions, skips = [], []
    scenario = {"stanton_" + key: value for key, value in binding(instrument).items()}
    scenario["stanton_context"] = instrument["context"]
    for slot in instrument["slots"].values():
        node = slot["node"]
        prompt_key = "stanton_prompt_" + node
        quantity = slot["quantity"]
        scenario[prompt_key] = f"{node}: {quantity['definition']} (units: {quantity['units']})"
        if slot["source_definition"]:
            definition = slot["source_definition"]
            scenario[prompt_key] += f"; source scope: {definition['measure']}; inclusion predicates: {definition['predicates']}"
        prompt = "{{ scenario." + prompt_key + " }}"
        if slot["kind"] == "decision":
            questions.append({"question_name": slot["id"], "question_type": "multiple_choice",
                "question_text": prompt + ". Select an option, __open__ to report all options, __unknown__, or __unanswered__.",
                "question_options": list(slot["decision"]["options"]) + ["__open__", "__unknown__", "__unanswered__"]})
            scenario[prompt_key] += "; options: " + ", ".join(f"{k}={v}" for k, v in slot["decision"]["options"].items())
        else:
            status_name = "status__" + node
            questions.append({"question_name": status_name, "question_type": "multiple_choice",
                "question_text": prompt + ". Supply a point, an uncertainty interval, unknown (with a reason), or unanswered.",
                "question_options": ["point", "interval", "unknown", "unanswered"]})
            tail = (1 - slot["coverage"]) / 2 * 100
            for prefix, status, text in (
                ("leaf__", "point", "Give your point estimate in the stated units."),
                ("low__", "interval", f"Give the lower endpoint of a central {slot['coverage'] * 100:g}% interval ({tail:g}th percentile)."),
                ("high__", "interval", f"Give the upper endpoint ({100 - tail:g}th percentile), in the same units."),
            ):
                question = prefix + node
                questions.append({"question_name": question, "question_type": "numerical", "question_text": prompt + ". " + text})
                skips.append((question, "{{ " + status_name + ".answer }} != '" + status + "'"))
        questions.append({"question_name": "reason__" + node, "question_type": "free_text",
                          "question_text": prompt + ". Explain your evidence, assumptions, or why you cannot answer. Unknown and deliberately open answers require a reason."})
    return questions, skips, scenario


def compile_instrument(instrument):
    with contextlib.redirect_stdout(sys.stderr):
        try:
            import edsl
            from edsl import QuestionFreeText, QuestionMultipleChoice, QuestionNumerical, Scenario, Survey
        except ImportError as exc:
            raise StantonError("Install stanton[fielding] to compile EDSL surveys.", "missing_dependency") from exc
        specs, skips, context = question_spec(instrument)
        constructors = {"numerical": QuestionNumerical, "multiple_choice": QuestionMultipleChoice, "free_text": QuestionFreeText}
        questions = [constructors[spec["question_type"]](**{k: v for k, v in spec.items() if k != "question_type"}) for spec in specs]
        survey = Survey(questions)
        for question, expression in skips:
            survey.add_skip_rule(question, expression)
        scenario = Scenario(context)
        return {"schema_version": 1, "format": "stanton.edsl-survey", "edsl_version": edsl.__version__,
                "binding": binding(instrument), "survey": survey.to_dict(), "scenario": scenario.to_dict(),
                "question_count": len(questions), "execution": "external",
                "instructions": "Load Survey.from_dict and Scenario.from_dict. Attach an Agent with a stable name or stanton_respondent_id trait. Run explicitly elsewhere; import Results.to_dict JSON with the respondent kind."}


def normalize_results(instrument, payload, respondent_kind):
    require(respondent_kind in RESPONSE_KINDS, "EDSL import requires an explicit respondent kind.")
    require(payload.get("edsl_class_name") == "Results" and isinstance(payload.get("data"), list), "Expected Results.to_dict() JSON with inline scenarios.")
    specs, _, context = question_spec(instrument)
    supplied_questions = payload.get("survey", {}).get("questions", [])
    require(isinstance(supplied_questions, list) and len(supplied_questions) == len(specs), "Results survey does not match the instrument.", "response_mismatch")
    for spec, actual in zip(specs, supplied_questions):
        require(isinstance(actual, dict) and all(actual.get(k) == v for k, v in spec.items()), "Results question contract changed.", "response_mismatch")
    expected_names = {spec["question_name"] for spec in specs}
    rows = []
    for raw in payload["data"]:
        require(isinstance(raw, dict), "Each Results row must be an object.")
        scenario = raw.get("scenario", {})
        require(isinstance(scenario, dict) and all(scenario.get(k) == v for k, v in context.items()),
                "Results scenario does not match the instrument, model, and frozen prompts.", "response_mismatch")
        agent = raw.get("agent", {})
        require(isinstance(agent, dict) and isinstance(agent.get("traits", {}), dict), "Invalid EDSL agent metadata.")
        respondent_id = agent.get("traits", {}).get("stanton_respondent_id") or agent.get("name")
        require(isinstance(respondent_id, str) and respondent_id.strip(), "EDSL agent needs a stable name or stanton_respondent_id trait.")
        answer = raw.get("answer", {})
        require(isinstance(answer, dict) and answer.keys() <= expected_names, "Results contain unknown question answers.", "response_mismatch")
        validation = raw.get("validated_dict", {})
        require(isinstance(validation, dict) and all(validation.get(q) is not False for q, value in answer.items() if value is not None),
                "Results include an answer marked invalid by EDSL.")
        normalized = {}
        for slot_id, slot in instrument["slots"].items():
            node = slot["node"]
            reason = answer.get("reason__" + node)
            reason = "" if reason is None else reason
            if slot["kind"] == "decision":
                value = answer.get(slot_id)
                require(value is None or isinstance(value, str), "EDSL decision answer must be an option string.")
                special = {None: "unanswered", "__open__": "open", "__unknown__": "unknown", "__unanswered__": "unanswered"}
                item = {"status": special.get(value, "choice"), "reason": reason}
                if item["status"] == "choice":
                    item["option"] = value
            else:
                status = answer.get("status__" + node)
                status = "unanswered" if status is None else status
                item = {"status": status, "reason": reason}
                fields = {"value": "leaf__" + node} if status == "point" else {"low": "low__" + node, "high": "high__" + node} if status == "interval" else {}
                active = set(fields.values())
                require(all(answer.get(q) is None for q in {"leaf__" + node, "low__" + node, "high__" + node} - active),
                        "Results contain values for skipped numerical questions.")
                if fields:
                    item.update({key: answer.get(question) for key, question in fields.items()})
                    item["units"] = slot["quantity"]["units"]
            normalized[slot_id] = item
        rows.append({"respondent": {"id": respondent_id, "kind": respondent_kind}, "iteration": raw.get("iteration", 0),
                     "answers": normalized, "provenance": {"format": "edsl.Results", "edsl_version": payload.get("edsl_version"),
                                                           "raw_result": deepcopy(raw)}})
    return rows
