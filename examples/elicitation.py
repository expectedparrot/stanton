"""Collect synthetic roof inputs, review proposals, and preserve their evidence."""

import argparse
import json
from copy import deepcopy
from pathlib import Path

from stanton import Session


def build(project, *, edsl=False):
    s = Session.create(project, title="Synthetic roof elicitation")
    s.define("area", units="meter**2", definition="Roof surface area", space="linear")
    s.define("rate", units="USD/meter**2", definition="Installed price per unit area")
    s.define("cost", units="USD", definition="Total roof cost", status="target")
    s.decision("finish", options={"standard": 1, "premium": 2}, definition="Chosen finish")
    s.relate("cost", "area*rate*finish")
    template = s.survey_draft("owner_input", phase="triage", budget=3)["response_template"]
    artifacts = {"response-template.json": template}
    if edsl:
        artifacts["owner-input.edsl.json"] = s.survey_compile("owner_input")
    payload = deepcopy(template)
    payload["responses"][0] = {"respondent": {"id": "synthetic_owner", "kind": "asker"}, "iteration": 0, "answers": {
        "leaf__area": {"status": "point", "value": 100, "units": "meter**2", "reason": "Synthetic measurement"},
        "leaf__rate": {"status": "interval", "low": 80, "high": 120, "units": "USD/meter**2", "reason": "Synthetic central 80 percent range"},
        "decision__finish": {"status": "open", "reason": "Compare both finishes before choosing"}}}
    artifacts["responses.json"] = payload
    s.survey_ingest("owner_input", payload, source="Synthetic owner interview")
    artifacts["proposal-review.json"] = s.survey_review("owner_input")
    s.survey_apply("owner_input", "all", reason="Use these synthetic inputs and compare finishes")
    run = s.sample("cost", n=2000, seed=42)
    artifacts["audit.json"] = s.audit("cost", run_id=run["id"])
    for name, data in artifacts.items():
        Path(project, name).write_text(json.dumps(data, indent=2) + "\n")
    return {"run_id": run["id"], "artifacts": list(artifacts), "validation": s.validate()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    parser.add_argument("--edsl", action="store_true", help="Also compile the optional native EDSL instrument")
    args = parser.parse_args()
    print(json.dumps(build(args.project, edsl=args.edsl), indent=2))
