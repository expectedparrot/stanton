"""Offline synthetic demonstration; the destination must be a new project."""

import argparse
import json

from stanton import Distribution, Session


def build(path):
    session = Session.create(path, title="Synthetic facility cost estimate")
    for name, units, definition, status in (
        ("base", "USD", "Synthetic baseline annual cost", "known"),
        ("growth", "dimensionless", "Annual operating growth multiplier excluding inflation", "estimated"),
        ("inflation", "dimensionless", "Shared cumulative price-level multiplier", "estimated"),
        ("rebuilt", "USD", "Synthetic future alternate cost before inflation", "estimated"),
        ("cost", "USD", "Nominal annual operating cost three years after baseline", "target"),
    ):
        session.define(name, units=units, definition=definition, status=status)
    session.anchor("base", 100000, source="Synthetic example fixture", asof="2026-09")
    session.estimate("growth", Distribution.from_interval(1.03, 1.10), reason="Synthetic judgment")
    session.estimate("inflation", Distribution.from_interval(.98, 1.06), reason="Synthetic common factor")
    session.estimate("rebuilt", Distribution.from_interval(210000, 240000), source="Synthetic alternate costing inputs")
    session.relate("cost", "base * growth**3 * inflation")
    session.fork("cost", "extrapolation")
    session.fork("cost", "costing")
    session.relate("cost", "rebuilt * inflation", fork="costing")
    session.fork("cost", "reference_class")
    session.abandon("reference_class", "No comparable facilities in this synthetic fixture")
    session.note("cost", "The disagreement needs investigation; neither method is established as correct.")
    session.bound("cost", upper=200000, reason="Provisional planning ceiling; inspect exceedances")
    session.merge("cost", ["extrapolation", "costing"], [.5, .5], reason="Equal illustrative weights")
    run = session.sample("cost", seed=42)
    return session.show("cost", run_id=run["id"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    args = parser.parse_args()
    print(json.dumps(build(args.project), indent=2))
