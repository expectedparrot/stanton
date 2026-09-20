"""Reproducible shared-leaf Monte Carlo evaluation of a frozen model."""

import hashlib

import numpy as np

from .common import digest, require
from .expressions import UNITS, evaluate, magnitude, parse
from .schemas import graph_order

ENGINE_VERSION = "stanton.sampler.v1"


def stream(seed, key):
    words = np.frombuffer(hashlib.sha256(f"{seed}:{key}".encode()).digest(), dtype="<u4")
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(words.tolist())))


def summary(values, quantiles=(5, 25, 50, 75, 95)):
    values = np.asarray(values, dtype=float)
    require(values.size > 0 and np.all(np.isfinite(values)), "Cannot summarize empty or nonfinite samples.")
    require(all(0 <= q <= 100 for q in quantiles), "Quantiles must lie in [0, 100].")
    return {"n": len(values), "mean": float(np.mean(values)), "std": float(np.std(values)),
            "quantiles": {f"p{q:g}": float(np.percentile(values, q)) for q in quantiles},
            "min": float(np.min(values)), "max": float(np.max(values))}


def select_forks(state, target, fork=None):
    require(target in state["quantities"], f"Unknown target: {target}", "not_found")
    if fork is not None:
        forks = [fork]
    elif target in state["merges"]:
        forks = state["merges"][target]["forks"]
    else:
        forks = [key for key, spec in state["strategies"].items()
                 if spec["status"] != "abandoned" and spec.get("target") == target]
        if not forks:
            forks = ["main"]
    require(all(f in state["graphs"] for f in forks), "Unknown fork.", "not_found")
    require(all(state["strategies"][f]["status"] != "abandoned" for f in forks),
            "Requested run includes an abandoned strategy; revise the merge or select another fork.")
    return forks


def sample(state, target, n=20000, seed=0, fork=None, **kwargs):
    from .branch_sampling import sample_branches
    return sample_branches(state, target, n=n, seed=seed, fork=fork, **kwargs)


def validate_run(run, state):
    if run.get("schema_version") in {2, 3}:
        from .branch_sampling import validate_branch_run
        return validate_branch_run(run, state)
    require(run["schema_version"] == 1 and run["state_sha256"] == digest(state), "Run does not match its frozen revision.")
    require(run["target"] in state["quantities"] and set(run["forks"]) == set(run["samples"]), "Invalid run target/forks.")
    require(type(run["n"]) is int and 1 <= run["n"] <= 200000, "Invalid run size.")
    for key, estimate_id in run["leaf_estimates"].items():
        require(state["estimates"][key]["id"] == estimate_id, "Run estimate identity mismatch.")
    orders = {f: graph_order(state, f, run["target"]) for f in run["forks"]}
    expected_leaves = {node for f in run["forks"] for node in orders[f] if node not in state["graphs"][f]}
    require(expected_leaves == set(run["leaf_samples"]) == set(run["leaf_estimates"]), "Run leaf registry mismatch.")
    for values in [*run["samples"].values(), *run["leaf_samples"].values()]:
        require(len(values) == run["n"] and np.all(np.isfinite(values)), "Invalid stored sample array.")
    for fork, values in run["samples"].items():
        require(summary(values) == run["summaries"][fork], "Stored summary does not match samples.")
        calculated = {}
        for node in orders[fork]:
            q = state["quantities"][node]
            if node in state["graphs"][fork]:
                tree, _ = parse(state["graphs"][fork][node]["expression"])
                arr = magnitude(evaluate(tree, calculated), q["units"], run["n"])
            else:
                arr = np.asarray(run["leaf_samples"][node])
            calculated[node] = UNITS.Quantity(arr, q["units"])
            bound = state["bounds"].get(node)
            if bound and bound["clip"]:
                require((bound["lower"] is None or np.all(arr >= bound["lower"])) and
                        (bound["upper"] is None or np.all(arr <= bound["upper"])), "Stored draws violate a conditioning bound.")
        require(np.allclose(calculated[run["target"]].magnitude, values, rtol=1e-12, atol=0),
                "Stored target samples do not match their model and shared leaves.")
    if run["merged_samples"] is not None:
        require(len(run["merged_samples"]) == run["n"] and summary(run["merged_samples"]) == run["merged_summary"],
                "Invalid merged samples or summary.")
        choices = np.asarray(run["mixture_choices"])
        require(choices.shape == (run["n"],) and choices.dtype.kind in "iu" and
                np.all((choices >= 0) & (choices < len(run["forks"]))), "Invalid mixture selection array.")
        expected = np.stack([run["samples"][f] for f in run["forks"]])[choices, np.arange(run["n"])]
        require(np.array_equal(expected, run["merged_samples"]), "Mixture does not select its recorded components.")
