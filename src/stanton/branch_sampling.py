"""Joint scenarios with paired decision, definition, and strategy evaluations."""

import itertools

import numpy as np
import scipy

from .branches import layout, leaf_plan
from .common import digest, require
from .distributions import Distribution
from .expressions import UNITS, evaluate, magnitude, parse
from .lint import finding, lint
from .processes import (
    draw_processes,
    evaluate_generated,
    make_generators,
    process_plan,
    validate_draws,
    validate_growth_support,
)
from .sampling import select_forks, stream, summary

ENGINE_VERSION = "stanton.sampler.v3"


def evaluate_branch(state, branch, leaves, n, process_draws=None):
    values, arrays = {}, {}
    for node in branch["order"]:
        quantity = state["quantities"][node]
        if node in branch["excluded"]:
            arr = np.zeros(n)
        elif node in branch["decision_values"]:
            arr = np.full(n, branch["decision_values"][node], dtype=float)
        elif quantity.get("process"):
            arr = evaluate_generated(state, node, values, process_draws or {"growth": {}, "shares": {}}, n)
        elif node in state["graphs"][branch["fork"]]:
            tree, _ = parse(state["graphs"][branch["fork"]][node]["expression"])
            arr = magnitude(evaluate(tree, values), quantity["units"], n)
        else:
            arr = np.asarray(leaves[node], dtype=float)
        arrays[node] = arr
        values[node] = UNITS.Quantity(arr, quantity["units"])
    return arrays


def sample_branches(state, target, n=20000, seed=0, fork=None, definitions=None, decisions=None, predicate_flips=False):
    require(type(n) is int and 1 <= n <= 200000, "Sample count must be an integer from 1 to 200000.")
    require(type(seed) is int and 0 <= seed < 2**64, "Seed must be an integer in [0, 2**64).")
    forks = select_forks(state, target, fork)
    branches = layout(state, target, forks, definitions, decisions, predicate_flips)
    require(n * len(branches) <= 2000000, "Run exceeds two million branch draws; reduce sample count or branch selection.")
    leaf_names, groups, leaf_groups = leaf_plan(state, branches)
    plan = process_plan(state, branches)
    process_cells = sum(path["steps"] for path in plan["paths"].values()) + sum(len(a["parts"]) for a in plan["allocations"].values())
    require(n * (len(branches) + len(leaf_names) + process_cells) <= 4000000,
            "Run exceeds four million stored draws; reduce sample count, branches, or process size.")
    process_generators = make_generators(plan, seed)
    accepted_processes = {"growth": {key: {p: [] for p in path["record"]["periods"][1:path["steps"] + 1]}
                                     for key, path in plan["paths"].items()},
                          "shares": {key: {p: [] for p in allocation["parts"]} for key, allocation in plan["allocations"].items()}}
    defaults = {key: Distribution.from_dict(state["estimates"][key]["distribution"])
                for key in leaf_names if key in state["estimates"]}
    conditional = {key: {given: Distribution.from_dict(estimate["distribution"]) for given, estimate in
                        state.get("conditional_estimates", {}).get(key, {}).items()} for key in leaf_names}
    generators = {key: stream(seed, "leaf:" + key) for key in leaf_names}
    regime_generators = {group: stream(seed, "scenario:" + group) for group in groups}
    accepted = {key: [] for key in leaf_names}
    accepted_regimes = {group: [] for group in groups}
    raw_regime_counts = {group: np.zeros(len(records), dtype=int) for group, records in groups.items()}
    outputs, raw_outputs = {key: [] for key in branches}, {key: [] for key in branches}
    bounds = {(key, node): {"branch": key, "fork": branch["fork"], "node": node, "violations": 0, "draws": 0,
                           **state["bounds"][node]} for key, branch in branches.items() for node in branch["order"]
              if node in state["bounds"] and node not in branch["excluded"]}
    warnings = lint(state)
    for key, branch in branches.items():
        branch_paths = process_plan(state, {key: branch})["paths"]
        prior_nodes = {path["record"]["growth"] for path in branch_paths.values() if path["steps"]}
        for node in sorted(set(branch["order"]) | prior_nodes):
            if node in branch["excluded"]:
                continue
            estimates = [state["estimates"].get(node)] + list(state.get("conditional_estimates", {}).get(node, {}).values())
            for estimate in filter(None, estimates):
                tagged = estimate.get("definition_id")
                if tagged and (tagged != branch["definition"] or branch["flip"]):
                    warnings.append(finding("def-drift", "Estimate is tagged to a different definition; inspect any declared bridge explicitly.",
                                            node=node, branch=key, estimate_definition=tagged))
    kept, attempted = 0, 0
    while kept < n and attempted < 20 * n:
        regimes = {}
        for group, records in groups.items():
            regimes[group] = regime_generators[group].choice(len(records), size=n, p=[record["p"] for record in records.values()])
            raw_regime_counts[group] += np.bincount(regimes[group], minlength=len(records))
        leaves = {}
        for key in leaf_names:
            uniforms = np.clip(generators[key].random(n), np.nextafter(0.0, 1.0), np.nextafter(1.0, 0.0))
            if key not in leaf_groups:
                values = defaults[key].ppf(uniforms)
            else:
                group = leaf_groups[key]
                values = np.empty(n)
                for index, scenario in enumerate(groups[group]):
                    selected = regimes[group] == index
                    if np.any(selected):
                        distribution = conditional[key].get(scenario, defaults.get(key))
                        values[selected] = distribution.ppf(uniforms[selected])
            require(np.all(np.isfinite(values)), f"Leaf {key} produced nonfinite draws.", "invalid_arithmetic")
            leaves[key] = values
        process_draws = draw_processes(state, plan, process_generators, n, groups, leaf_groups, regimes)
        keep = np.ones(n, dtype=bool)
        candidates = {}
        for key, branch in branches.items():
            arrays = evaluate_branch(state, branch, leaves, n, process_draws)
            for node in branch["order"]:
                if (key, node) not in bounds:
                    continue
                bound, values = bounds[key, node], arrays[node]
                violates = np.zeros(n, dtype=bool)
                if bound["lower"] is not None:
                    violates |= values < bound["lower"]
                if bound["upper"] is not None:
                    violates |= values > bound["upper"]
                bound["violations"] += int(violates.sum())
                bound["draws"] += n
                if bound["clip"]:
                    keep &= ~violates
            candidates[key] = arrays[target]
            raw_outputs[key].append(candidates[key])
        indices = np.flatnonzero(keep)[:n - kept]
        for key in leaf_names:
            accepted[key].append(leaves[key][indices])
        for key in branches:
            outputs[key].append(candidates[key][indices])
        for group in groups:
            accepted_regimes[group].append(regimes[group][indices])
        for kind, processes in process_draws.items():
            for process, columns in processes.items():
                for column, values in columns.items():
                    accepted_processes[kind][process][column].append(values[indices])
        kept += len(indices)
        attempted += n
    require(kept == n, f"Truncation retained only {kept}/{n} requested draws after {attempted} attempts; revise bounds or the model.",
            "low_bound_acceptance")
    outputs = {key: np.concatenate(parts) for key, parts in outputs.items()}
    accepted = {key: np.concatenate(parts) for key, parts in accepted.items()}
    accepted_regimes = {group: np.concatenate(parts) for group, parts in accepted_regimes.items()}
    process_draws = {kind: {key: {column: np.concatenate(parts).tolist() for column, parts in columns.items()}
                           for key, columns in processes.items()} for kind, processes in accepted_processes.items()}
    for bound in bounds.values():
        bound["violation_mass"] = bound["violations"] / bound["draws"]
        if bound["violations"]:
            warnings.append(finding("bound-violation", "Samples violate a declared bound before truncation.", **bound))
    for left, right in itertools.combinations(branches, 2):
        if branches[left]["context_key"] != branches[right]["context_key"]:
            continue
        a, b = outputs[left], outputs[right]
        space = state["quantities"][target]["space"]
        if space == "log" and np.all(a > 0) and np.all(b > 0):
            a, b = np.log(a), np.log(b)
        else:
            space = "linear"
        qa, qb = np.percentile(a, [10, 50, 90]), np.percentile(b, [10, 50, 90])
        if abs(qa[1] - qb[1]) > max((qa[2] - qa[0]) / 2, (qb[2] - qb[0]) / 2):
            warnings.append(finding("divergent-strategies", "Strategy medians differ by more than the larger central-80% half-width.",
                                    forks=[branches[left]["fork"], branches[right]["fork"]], branches=[left, right], space=space))
    mixtures = {}
    merge = state["merges"].get(target) if fork is None else None
    if merge:
        # Identical method selections in every context keep comparisons paired.
        choices = stream(seed, "mixture:" + target).choice(len(forks), size=n, p=merge["weights"])
        for context in sorted({branch["context_key"] for branch in branches.values()}):
            members = [next(key for key, branch in branches.items() if branch["fork"] == f and branch["context_key"] == context) for f in forks]
            values = np.stack([outputs[key] for key in members])[choices, np.arange(n)]
            mixtures[context] = {"branches": members, "samples": values.tolist(), "summary": summary(values), "choices": choices.tolist()}
    only_mixture = next(iter(mixtures.values())) if len(mixtures) == 1 else None
    prior_names = {path["record"]["growth"] for path in plan["paths"].values() if path["steps"]}
    return {"schema_version": 3, "engine": ENGINE_VERSION, "numpy": np.__version__, "scipy": scipy.__version__,
            "generator": "PCG64", "state_sha256": digest(state), "target": target, "seed": seed, "n": n,
            "units": state["quantities"][target]["units"], "context": state["context"], "forks": forks, "branches": branches,
            "selection": {"fork": fork, "definitions": definitions, "decisions": decisions, "predicate_flips": predicate_flips},
            "leaf_estimates": {key: {"default": state["estimates"].get(key, {}).get("id"),
                "given": {s: e["id"] for s, e in state.get("conditional_estimates", {}).get(key, {}).items()}} for key in leaf_names},
            "process_plan": plan, "process_draws": process_draws,
            "process_priors": {key: {"default": state["estimates"].get(key, {}).get("id"),
                "given": {s: e["id"] for s, e in state.get("conditional_estimates", {}).get(key, {}).items()}} for key in prior_names},
            "scenario_groups": groups, "scenario_draws": {group: values.tolist() for group, values in accepted_regimes.items()},
            "scenario_frequencies": {group: {scenario: {"p": records[scenario]["p"],
                "unconditioned": float(raw_regime_counts[group][i] / attempted),
                "retained": float(np.mean(accepted_regimes[group] == i))} for i, scenario in enumerate(records)} for group, records in groups.items()},
            "summaries": {key: summary(values) for key, values in outputs.items()},
            "unconditioned_summaries": {key: summary(np.concatenate(parts)) for key, parts in raw_outputs.items()},
            "merged_summary": only_mixture["summary"] if only_mixture else None, "mixtures": mixtures,
            "samples": {key: values.tolist() for key, values in outputs.items()},
            "leaf_samples": {key: values.tolist() for key, values in accepted.items()},
            "merged_samples": only_mixture["samples"] if only_mixture else None,
            "mixture_choices": only_mixture["choices"] if only_mixture else None, "merge": merge,
            "bounds": list(bounds.values()), "attempted": attempted,
            "conditioning": "joint rows satisfying all --clip bounds in every selected strategy, decision, and definition branch",
            "warnings": warnings}


def validate_branch_run(run, state):
    require(run["state_sha256"] == digest(state), "Run does not match its frozen revision.")
    require(type(run["n"]) is int and 1 <= run["n"] <= 200000, "Invalid run size.")
    forks = select_forks(state, run["target"], run["selection"]["fork"])
    branches = layout(state, run["target"], forks, run["selection"]["definitions"], run["selection"]["decisions"], run["selection"]["predicate_flips"])
    require(forks == run["forks"] and branches == run["branches"] and set(branches) == set(run["samples"]), "Run branch registry mismatch.")
    leaves, groups, leaf_groups = leaf_plan(state, branches)
    if run["schema_version"] == 3:
        plan = process_plan(state, branches)
        require(plan == run["process_plan"], "Run process plan does not match its frozen model.")
        validate_draws(plan, run["process_draws"], run["n"])
        prior_names = {path["record"]["growth"] for path in plan["paths"].values() if path["steps"]}
        expected_priors = {key: {"default": state["estimates"].get(key, {}).get("id"),
            "given": {s: e["id"] for s, e in state.get("conditional_estimates", {}).get(key, {}).items()}} for key in prior_names}
        require(run["process_priors"] == expected_priors, "Run growth prior revisions do not match the frozen model.")
    require(set(leaves) == set(run["leaf_samples"]) == set(run["leaf_estimates"]), "Run leaf registry mismatch.")
    require(groups == run["scenario_groups"] and set(groups) == set(run["scenario_draws"]), "Run scenario registry mismatch.")
    for group, records in groups.items():
        draws = np.asarray(run["scenario_draws"][group])
        require(draws.shape == (run["n"],) and draws.dtype.kind in "iu" and np.all((draws >= 0) & (draws < len(records))), "Invalid scenario draws.")
        require(all(record["p"] > 0 or not np.any(draws == i) for i, record in enumerate(records.values())), "Zero-probability scenario was sampled.")
        require(set(run["scenario_frequencies"][group]) == set(records), "Scenario frequency registry mismatch.")
        for i, (scenario, record) in enumerate(records.items()):
            frequency = run["scenario_frequencies"][group][scenario]
            require(frequency["p"] == record["p"] and frequency["retained"] == float(np.mean(draws == i)), "Scenario frequencies disagree with saved draws.")
            require(0 <= frequency["unconditioned"] <= 1, "Invalid unconditioned scenario frequency.")
        require(abs(sum(f["unconditioned"] for f in run["scenario_frequencies"][group].values()) - 1) <= 1e-12,
                "Unconditioned scenario frequencies do not sum to one.")
    if run["schema_version"] == 3:
        validate_growth_support(state, plan, run["process_draws"], groups, leaf_groups, run["scenario_draws"], run["n"])
    for node in leaves:
        expected = {"default": state["estimates"].get(node, {}).get("id"),
                    "given": {s: e["id"] for s, e in state.get("conditional_estimates", {}).get(node, {}).items()}}
        require(run["leaf_estimates"][node] == expected, "Run estimate identity mismatch.")
    for values in [*run["samples"].values(), *run["leaf_samples"].values()]:
        require(np.asarray(values).shape == (run["n"],) and np.all(np.isfinite(values)), "Invalid stored sample array.")
    for node in leaves:
        values = np.asarray(run["leaf_samples"][node])
        if node not in leaf_groups:
            partitions = [(np.ones(run["n"], dtype=bool), state["estimates"][node])]
        else:
            group = leaf_groups[node]
            partitions = [(np.asarray(run["scenario_draws"][group]) == i,
                           state.get("conditional_estimates", {}).get(node, {}).get(scenario, state["estimates"].get(node)))
                          for i, scenario in enumerate(groups[group])]
        for mask, estimate in partitions:
            if not np.any(mask):
                continue
            dist = Distribution.from_dict(estimate["distribution"])
            draws = values[mask]
            if dist.family == "point":
                require(np.all(draws == dist.parameters[0]), "Leaf draws disagree with the recorded scenario point estimate.")
            elif dist.family == "empirical":
                require(np.all(np.isin(draws, dist.parameters)), "Leaf draws fall outside empirical support.")
            elif dist.family == "quantiles":
                require(np.all((draws >= dist.parameters[0][1]) & (draws <= dist.parameters[-1][1])), "Leaf draws fall outside quantile support.")
            elif dist.family == "lognormal":
                require(np.all(draws >= 0), "Lognormal draws must be nonnegative in floating-point arithmetic.")
            elif dist.family == "logitnormal":
                require(np.all((draws >= 0) & (draws <= 1)), "Logit-normal draws must lie in [0, 1].")
    for key, branch in branches.items():
        require(summary(run["samples"][key]) == run["summaries"][key], "Stored summary does not match samples.")
        calculated = evaluate_branch(state, branch, run["leaf_samples"], run["n"], run.get("process_draws"))
        require(np.allclose(calculated[run["target"]], run["samples"][key], rtol=1e-12, atol=0), "Stored samples do not match their branch model.")
        for node, arr in calculated.items():
            bound = state["bounds"].get(node)
            if bound and bound["clip"] and node not in branch["excluded"]:
                require((bound["lower"] is None or np.all(arr >= bound["lower"])) and
                        (bound["upper"] is None or np.all(arr <= bound["upper"])), "Stored draws violate a conditioning bound.")
    expected_merge = state["merges"].get(run["target"]) if run["selection"]["fork"] is None else None
    require(run["merge"] == expected_merge, "Run merge metadata mismatch.")
    contexts = {branch["context_key"] for branch in branches.values()} if expected_merge else set()
    require(contexts == set(run["mixtures"]), "Missing or unexpected mixtures.")
    first_choices = None
    for context, mixture in run["mixtures"].items():
        members = [next(key for key, branch in branches.items() if branch["fork"] == f and branch["context_key"] == context) for f in forks]
        require(members == mixture["branches"], "Mixture crosses decision or definition branches.")
        choices = np.asarray(mixture["choices"])
        require(choices.shape == (run["n"],) and choices.dtype.kind in "iu" and np.all((choices >= 0) & (choices < len(members))), "Invalid mixture selections.")
        if first_choices is None:
            first_choices = choices
        else:
            require(np.array_equal(first_choices, choices), "Mixture choices must be paired across contexts.")
        values = np.stack([run["samples"][key] for key in members])[choices, np.arange(run["n"])]
        require(np.array_equal(values, mixture["samples"]) and summary(values) == mixture["summary"], "Invalid mixture samples or summary.")
    only = next(iter(run["mixtures"].values())) if len(run["mixtures"]) == 1 else None
    require(run["merged_samples"] == (only["samples"] if only else None) and
            run["merged_summary"] == (only["summary"] if only else None) and
            run["mixture_choices"] == (only["choices"] if only else None), "Ambiguous or inconsistent merged-result aliases.")
