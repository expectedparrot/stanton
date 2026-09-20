"""Synthetic annual path, conserved budget, and query-time occupancy profile."""

import argparse
import json
from pathlib import Path

from stanton import Distribution, Session


def build(project):
    s = Session.create(project, title="Synthetic planning processes", timezone="America/New_York")
    for name, units, definition, target in (
        ("base", "USD", "Synthetic annual revenue at the initial period", False),
        ("growth", "dimensionless", "Annual revenue multiplier prior", False),
        ("future", "USD", "Revenue in 2029", True),
        ("budget", "USD", "Known total budget", False),
        ("allocated", "USD", "Sum of all budget parts", True),
        ("weekday", "person", "Synthetic weekday occupancy", False),
        ("weekend", "person", "Synthetic weekend occupancy", False),
    ):
        s.define(name, units=units, definition=definition, status="target" if target else "estimated")
    s.anchor("base", 100000, source="Synthetic fixture", asof="2026-01")
    s.estimate("growth", Distribution.from_interval(1.01, 1.10), reason="Synthetic central 80 percent interval")
    s.series("revenue", base="base", growth="growth", periods=[2026, 2027, 2028, 2029], rho=.7,
             definition="Annual revenue path", reason="Synthetic persistence assumption")
    s.relate_path("future", "revenue", at=2029)
    path_run = s.sample("future", n=2000, seed=42)
    s.anchor("budget", 100000, source="Synthetic fixture", asof="2026-01-01")
    s.allocate("budget", {"staff": 5, "equipment": 3, "reserve": 2}, allocation="spending",
               reason="Synthetic expected shares and concentration")
    s.relate("allocated", "staff + equipment + reserve")
    allocation_run = s.sample("allocated", n=2000, seed=42)
    s.estimate("weekday", Distribution.from_point(100), reason="Synthetic fixture")
    s.estimate("weekend", Distribution.from_point(20), reason="Synthetic fixture")
    s.periodic("occupancy", over="day_of_week", profile={i: "weekday" if i < 5 else "weekend" for i in range(7)},
               definition="Occupancy at query time", reason="Synthetic weekly pattern")
    s.context(at="2026-09-19T16:00:00+00:00")
    periodic_run = s.sample("occupancy", n=100, seed=42)
    reports = {"path": s.series_show("revenue", run_id=path_run["id"]),
               "allocation": s.allocation_show("spending", run_id=allocation_run["id"]),
               "periodic": s.series_show("occupancy", run_id=periodic_run["id"])}
    for name, report in reports.items():
        Path(project, name + "-report.json").write_text(json.dumps(report, indent=2) + "\n")
    return {"runs": {name: report["run_id"] for name, report in reports.items()}, "validation": s.validate()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    print(json.dumps(build(parser.parse_args().project), indent=2))
