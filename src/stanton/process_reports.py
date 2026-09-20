"""Read saved process realizations without drawing new paths or reallocating totals."""

import numpy as np

from .branch_sampling import evaluate_branch
from .common import require
from .sampling import summary


def series_show(session, series, run_id=None):
    run = session.store.run(run_id) if run_id else None
    state, revision = session.store.read(run["revision"] if run else None)
    require(series in state.get("series", {}), "Unknown series.", "not_found")
    record = state["series"][series]
    result = {"series": series, "revision": revision, "run_id": run_id, "record": record}
    if not run:
        return result
    require(run.get("schema_version") == 3 and (series in run["process_plan"]["paths"] or series in run["process_plan"]["periodic"]),
            "Series was not used by this saved run.", "not_found")
    branches = {}
    for key, branch in run["branches"].items():
        arrays = evaluate_branch(state, branch, run["leaf_samples"], run["n"], run["process_draws"])
        periods = record["nodes"] if record["kind"] == "path" else {run["process_plan"]["periodic"][series]["period"]: record["node"]}
        values = {period: summary(arrays[node]) for period, node in periods.items() if node in arrays}
        if values:
            branches[key] = values
    result["branches"] = branches
    result["growth"] = {period: summary(values) for period, values in run["process_draws"]["growth"].get(series, {}).items()}
    result["scenario_frequencies"] = run["scenario_frequencies"]
    result["context"] = run["context"]
    return result


def allocation_show(session, allocation, run_id=None):
    run = session.store.run(run_id) if run_id else None
    state, revision = session.store.read(run["revision"] if run else None)
    require(allocation in state.get("allocations", {}), "Unknown allocation.", "not_found")
    record = state["allocations"][allocation]
    result = {"allocation": allocation, "revision": revision, "run_id": run_id, "record": record}
    if not run:
        return result
    require(run.get("schema_version") == 3 and allocation in run["process_draws"]["shares"], "Allocation was not used by this saved run.")
    shares = run["process_draws"]["shares"][allocation]
    total = state["estimates"][record["total"]]["distribution"]["parameters"][0]
    result.update(total=total, units=state["quantities"][record["total"]]["units"],
                  shares={part: summary(values) for part, values in shares.items()},
                  parts={part: summary(np.asarray(values) * total) for part, values in shares.items()},
                  max_conservation_error=float(np.max(np.abs(np.sum([np.asarray(v) * total for v in shares.values()], axis=0) - total))),
                  interpretation="Complete underlying partition; a definition mask can exclude parts from a reported subtotal.")
    return result
