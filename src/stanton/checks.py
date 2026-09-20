"""Empirical claim placement and paired predicate-flip diagnostics."""

import numpy as np

from .common import finite, require
from .sampling import summary


def placement(values, claim):
    values = np.asarray(values, dtype=float)
    below = float(np.mean(values < claim))
    equal = float(np.mean(values == claim))
    lo, hi = np.percentile(values, [5, 95])
    return {"claim": claim, "percentile": 100 * (below + .5 * equal),
            "percentile_interval": [100 * below, 100 * (below + equal)], "equal_mass": equal,
            "verdict": "below_p5" if claim < lo else "above_p95" if claim > hi else "within_p5_p95",
            "interval": {"p5": float(lo), "p95": float(hi)},
            "interpretation": "Placement in the supplied model, not a truth verdict or calibrated significance test."}


def check_claim(run, claim, definition=None):
    claim = finite(claim, "Claim")
    entries = {}
    branches = run.get("branches", {fork: {"fork": fork, "definition": None, "flip": None, "decisions": {},
                                           "context_key": "", "predicates": None} for fork in run["forks"]})
    for key, branch in branches.items():
        entries[key] = {"metadata": branch, "samples": run["samples"][key], "kind": "strategy"}
    mixtures = run.get("mixtures", {})
    if mixtures:
        for key, mixture in mixtures.items():
            entries["mixture@" + key] = {"metadata": branches[mixture["branches"][0]], "samples": mixture["samples"], "kind": "mixture"}
    elif run.get("schema_version") == 1 and run["merged_samples"] is not None:
        entries["mixture"] = {"metadata": next(iter(branches.values())), "samples": run["merged_samples"], "kind": "mixture"}
    selected = {key: entry for key, entry in entries.items() if entry["metadata"]["flip"] is None and
                (definition is None or entry["metadata"]["definition"] == definition)}
    require(selected, "Saved run has no matching definition. Sample the target with --definitions NAME first.", "not_found")
    results = {}
    for key, entry in selected.items():
        meta = entry["metadata"]
        baseline = placement(entry["samples"], claim)
        flips = {}
        for predicate in meta.get("predicates") or {}:
            candidate = next((other for other in entries.values() if other["kind"] == entry["kind"] and
                other["metadata"]["definition"] == meta["definition"] and other["metadata"]["flip"] == predicate and
                other["metadata"]["decisions"] == meta["decisions"] and
                (entry["kind"] == "mixture" or other["metadata"]["fork"] == meta["fork"])), None)
            if candidate is None:
                flips[predicate] = {"status": "not_evaluated", "action": "Sample with --predicate-flips to save paired comparisons."}
            else:
                alternative = placement(candidate["samples"], claim)
                flips[predicate] = {"status": "evaluated", **alternative,
                    "changes_verdict": baseline["verdict"] != alternative["verdict"],
                    "paired_difference": summary(np.asarray(candidate["samples"]) - np.asarray(entry["samples"]))}
        results[key] = {"kind": entry["kind"], "fork": meta["fork"] if entry["kind"] == "strategy" else None,
                        "definition": meta["definition"], "definition_revision": meta.get("definition_revision"),
                        "decisions": meta["decisions"], **baseline, "predicate_flips": flips}
    return {"run_id": run["id"], "revision": run["revision"], "target": run["target"], "units": run["units"],
            "n": run["n"], "claim": claim, "results": results, "warnings": run["warnings"]}
