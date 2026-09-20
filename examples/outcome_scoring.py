"""Synthetic saved forecasts, resolved outcomes, and a fixed train/test cohort."""

import argparse
import json
from pathlib import Path

from stanton import Distribution, Session
from stanton.common import now


def build(project):
    s = Session.create(project, title="Synthetic cost forecast evaluation")
    s.define("cost", units="USD", definition="Synthetic cost of an independent roof case", status="target")
    runs, members = {}, []
    for letter, low, high, split in (("a", 80, 120, "train"), ("b", 160, 240, "test"), ("c", 320, 480, "test")):
        s.estimate("cost", Distribution.from_interval(low, high), reason=f"Synthetic forecast for roof {letter.upper()}")
        run = s.sample("cost", n=2000, seed=42)
        runs[letter] = run
        members.append({"event": f"roof_{letter}", "run_id": run["id"], "group": f"building_{letter}", "split": split})
    s.cohort_define("roofs", members, units="USD", reason="Fixed synthetic cases with separate buildings in train and test")
    for letter, outcome in (("a", 110), ("b", 260)):
        s.resolve("cost", outcome, event=f"roof_{letter}", run_id=runs[letter]["id"], units="USD",
                  source=f"Synthetic observed cost for roof {letter.upper()}", observed_at=now())
    reports = {"members.json": members, "cohort.json": s.cohort_show("roofs"),
               "roof-a-score.json": s.score("roof_a"), "roof-b-score.json": s.score("roof_b"),
               "evaluation-report.json": s.cohort_evaluate("roofs")}
    for name, report in reports.items():
        Path(project, name).write_text(json.dumps(report, indent=2) + "\n")
    return {"runs": {letter: run["id"] for letter, run in runs.items()}, "artifacts": list(reports), "validation": s.validate()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    print(json.dumps(build(parser.parse_args().project), indent=2))
