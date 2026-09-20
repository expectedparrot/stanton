"""Synthetic renovation estimate: shared demand regimes, choices, and quote scope."""

import argparse
import json
from pathlib import Path

from stanton import Distribution, Session
from stanton.reports import report_context


def build(project):
    s = Session.create(project, title="Synthetic renovation scope comparison")
    for name, definition, predicates in (
        ("labor", "Synthetic labor cost before finish choice", None),
        ("materials", "Synthetic material cost before finish choice", None),
        ("disposal", "Synthetic optional disposal cost", {"disposal": True}),
        ("cost", "Synthetic total renovation cost under the selected scope", None),
    ):
        s.define(name, units="USD", definition=definition, predicates=predicates,
                 status="target" if name == "cost" else "estimated")
    s.scenario("quiet", p=.4, definition="Quiet demand regime", reason="Synthetic fixture", group="demand")
    s.scenario("busy", p=.6, definition="Busy demand regime", reason="Synthetic fixture", group="demand")
    for scenario, labor, materials in (("quiet", 10000, 3000), ("busy", 20000, 6000)):
        s.estimate("labor", Distribution.from_point(labor), given=scenario, reason="Synthetic fixture")
        s.estimate("materials", Distribution.from_point(materials), given=scenario, reason="Synthetic fixture")
    s.estimate("disposal", Distribution.from_interval(4000, 6000), reason="Synthetic disposal uncertainty")
    s.decision("finish", options={"standard": 1, "premium": 1.5}, definition="Asker-controlled finish choice", default="standard")
    s.choose("finish", leave_open=True, reason="Compare both options before choosing")
    s.relate("cost", "(labor + materials) * finish + disposal")
    s.definition("quoted", target="cost", measure="quoted renovation spend", predicates={"disposal": False}, owner="claimant", role="primary")
    s.definition("full", target="cost", measure="total renovation spend", predicates={"disposal": True})
    run = s.sample("cost", n=5000, seed=42, definitions="all", predicate_flips=True)
    context = report_context(s, "cost", run["id"])
    claim = s.check(30000, "cost", definition="quoted", run_id=run["id"])
    Path(project, "report-context.json").write_text(json.dumps(context, indent=2) + "\n")
    Path(project, "claim-check.json").write_text(json.dumps(claim, indent=2) + "\n")
    return {"run_id": run["id"], "claim_check": claim, "validation": s.validate()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    print(json.dumps(build(parser.parse_args().project), indent=2))
