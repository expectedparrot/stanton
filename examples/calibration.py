"""Synthetic training-only spread fitting, explicit application, and test scoring."""

import argparse
import json
from pathlib import Path

from stanton import Distribution, Session
from stanton.common import now


def build(project):
    s = Session.create(project, title="Synthetic spread calibration")
    s.define("cost", units="USD", definition="Synthetic cost per independent building", status="target")
    runs, members = {}, []
    for split, low, high, seed in (("train", 80, 120, 42), ("test", 160, 240, 43)):
        s.estimate("cost", Distribution.from_interval(low, high), reason=f"Synthetic {split} forecast")
        runs[split] = s.sample("cost", n=500, seed=seed)
        members.append({"event": split, "group": split, "split": split, "run_id": runs[split]["id"]})
    s.cohort_define("buildings", members, units="USD", reason="Fixed synthetic cases with separate buildings in each split")
    s.resolve("cost", 140, event="train", run_id=runs["train"]["id"], units="USD", source="Synthetic training outcome", observed_at=now())
    fitted = s.calibration_fit("spread_v1", cohort="buildings", method="strategy:main", scales=[.5, 1, 2, 4],
                               reason="Assess direct-cost forecast spread on fixed training cases")
    overlay = s.calibration_apply("spread_v1", run_id=runs["test"]["id"], reason="Synthetic transfer to the second building")
    unresolved = s.calibration_evaluate("spread_v1")
    s.resolve("cost", 260, event="test", run_id=runs["test"]["id"], units="USD", source="Synthetic test outcome", observed_at=now())
    reports = {"fitted.json": fitted, "adjusted.json": overlay, "unresolved.json": unresolved,
               "comparison.json": s.calibration_evaluate("spread_v1")}
    for filename, report in reports.items():
        Path(project, filename).write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return {"runs": {split: run["id"] for split, run in runs.items()}, "artifacts": list(reports), "validation": s.validate()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    print(json.dumps(build(parser.parse_args().project), indent=2))
