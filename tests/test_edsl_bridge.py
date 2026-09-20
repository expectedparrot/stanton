import socket
from copy import deepcopy

import pytest

from stanton import Session, StantonError

pytest.importorskip("edsl")


@pytest.fixture
def native(tmp_path, monkeypatch):
    def network_forbidden(*args, **kwargs):
        pytest.fail("Offline EDSL compilation and ingestion attempted a network connection")
    monkeypatch.setattr(socket.socket, "connect", network_forbidden)
    from edsl import Agent, Model, Results, Scenario, Survey
    from edsl.results import Result
    session = Session.create(tmp_path / "edsl")
    session.define("amount", units="USD", definition="Synthetic amount")
    session.decision("choice", options={"small": 1, "large": 2}, definition="Controlled size")
    session.survey_draft("ask", phase="triage")
    compiled = session.survey_compile("ask")
    survey = Survey.from_dict(compiled["survey"])
    scenario = Scenario.from_dict(compiled["scenario"])
    result = Result(agent=Agent(name="persona", traits={"stanton_respondent_id": "expert1", "expertise": "Synthetic fixture"}),
                    model=Model("test"), scenario=scenario, iteration=0,
                    answer={"decision__choice": "__open__", "reason__choice": "Compare sizes",
                            "status__amount": "interval", "leaf__amount": None,
                            "low__amount": 80, "high__amount": 120, "reason__amount": "Synthetic judgment"})
    results = Results(survey=survey, data=[result])
    return session, survey, results.to_dict()


def test_native_roundtrip_skip_logic_raw_results_and_iterations(native):
    session, survey, payload = native
    assert survey.next_question("status__amount", {"status__amount": "unknown"}).question_name == "reason__amount"
    assert survey.next_question("status__amount", {"status__amount": "point"}).question_name == "leaf__amount"
    assert survey.next_question("status__amount", {"status__amount": "interval"}).question_name == "low__amount"
    second = deepcopy(payload["data"][0])
    second["iteration"] = 1
    payload["data"].append(second)
    imported = session.survey_ingest("ask", payload, format="edsl", respondent_kind="llm_panel", source="Offline synthetic results")
    assert len(imported["response_ids"]) == 2
    review = session.survey_review("ask")
    assert len(review["conflicts"]["leaf__amount"]) == 2
    first = review["responses"][imported["response_ids"][0]]
    assert first["raw"]["provenance"]["raw_result"] == payload["data"][0]
    assert first["respondent"]["id"] == "expert1"
    selected = [key for key, value in review["proposals"].items() if value["response_id"] == first["id"]]
    session.survey_apply("ask", selected, reason="Use the first synthetic iteration")
    assert session.store.read()[0]["decisions"]["choice"]["status"] == "open"
    assert session.validate()["ok"]


@pytest.mark.parametrize("change", ["scenario", "prompt", "question", "binding", "skipped", "anonymous", "kind", "invalid", "reason_type", "status_type"])
def test_native_wrong_instrument_or_invalid_answers_are_rejected(native, change):
    session, _, payload = native
    kind = "human_panel"
    if change == "scenario":
        payload["data"][0]["scenario"]["stanton_model_revision"] += 1
    elif change == "prompt":
        payload["data"][0]["scenario"]["stanton_prompt_amount"] = "A different quantity"
    elif change == "question":
        payload["survey"]["questions"][0]["question_text"] = "Different question"
    elif change == "binding":
        payload["data"][0]["answer"]["leaf__other"] = 100
    elif change == "skipped":
        payload["data"][0]["answer"]["leaf__amount"] = 100
    elif change == "anonymous":
        payload["data"][0]["agent"] = {}
    elif change == "invalid":
        payload["data"][0]["validated_dict"] = {"low__amount": False}
    elif change == "reason_type":
        payload["data"][0]["answer"]["reason__amount"] = False
    elif change == "status_type":
        payload["data"][0]["answer"]["status__amount"] = 0
    else:
        kind = None
    before = session.store.read()
    with pytest.raises(StantonError):
        session.survey_ingest("ask", payload, format="edsl", respondent_kind=kind, source="Fixture")
    assert session.store.read() == before
