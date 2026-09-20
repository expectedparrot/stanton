"""Deterministic decision/definition branches and explicit scenario coverage."""

import itertools
import math

from .common import require
from .schemas import graph_order


def masked_order(state, fork, target, predicates):
    """Do not demand estimates or additional predicates below an excluded node."""
    from .processes import dependencies
    excluded, visited = set(), set()

    def visit(node):
        if node in visited:
            return
        visited.add(node)
        conditions = state["quantities"][node].get("predicates", {})
        require(not conditions or predicates is not None,
                f"Quantity {node} has inclusion predicates; select a definition.", "missing_definition")
        if conditions:
            require(conditions.keys() <= predicates.keys(), f"Definition lacks predicates for {node}: " +
                    ", ".join(sorted(conditions.keys() - predicates.keys())), "missing_predicate")
            if any(predicates[key] != value for key, value in conditions.items()):
                excluded.add(node)
                return
        for dependency in dependencies(state, fork, node):
            visit(dependency)

    visit(target)
    return graph_order(state, fork, target, excluded=excluded), sorted(excluded)


def layout(state, target, forks, definitions=None, decisions=None, predicate_flips=False):
    registry = state.get("definitions", {})
    if definitions == "all":
        definitions = sorted(key for key, value in registry.items() if value["target"] == target)
        require(definitions, "No definitions are registered for this target.")
    elif isinstance(definitions, str):
        definitions = [definitions]
    elif definitions is None:
        definitions = [key for key, value in registry.items() if value["target"] == target and value["role"] == "primary"]
    require(isinstance(definitions, (list, tuple)) and len(set(definitions)) == len(definitions), "Definitions must be distinct.")
    require(set(definitions) <= registry.keys(), "Unknown definition.", "not_found")
    require(all(registry[key]["target"] == target for key in definitions), "Definition belongs to another target.")
    contexts = {}
    for definition in definitions or [None]:
        record = registry[definition] if definition else None
        contexts[definition or ""] = {"definition": definition, "definition_revision": record["id"] if record else None,
                                      "predicates": dict(record["predicates"]) if record else None, "flip": None}
        if predicate_flips and record:
            for predicate, value in sorted(record["predicates"].items()):
                contexts[f"{definition}~{predicate}"] = {"definition": definition, "definition_revision": record["id"],
                    "predicates": {**record["predicates"], predicate: not value}, "flip": predicate}
    require(not predicate_flips or definitions, "Predicate flips require a definition.")
    reachable = set()
    for context in contexts.values():
        for fork in forks:
            reachable.update(masked_order(state, fork, target, context["predicates"])[0])
    decision_registry = state.get("decisions", {})
    relevant = sorted(reachable & decision_registry.keys())
    selections = decisions or {}
    require(isinstance(selections, dict) and selections.keys() <= set(relevant), "Decision selections must reference decisions used by this target.")
    options = []
    for decision in relevant:
        record = decision_registry[decision]
        if decision in selections:
            require(selections[decision] in record["options"], f"Unknown option for {decision}.")
            options.append([selections[decision]])
        elif record["status"] == "selected":
            options.append([record["selected"]])
        else:
            # A recommended default is metadata, not an implied choice by the asker.
            options.append(sorted(record["options"]))
    count = len(contexts) * math.prod(len(values) for values in options) * len(forks)
    require(count <= 64, "Run would exceed 64 branches; select fewer definitions or decision options.")
    branches = {}
    for context_key, context in contexts.items():
        for combination in itertools.product(*options):
            selected = dict(zip(relevant, combination))
            suffix = "[" + ",".join(f"{key}={value}" for key, value in selected.items()) + "]" if selected else ""
            key = context_key + suffix
            for fork in forks:
                order, excluded = masked_order(state, fork, target, context["predicates"])
                branches[fork + ("@" + key if key else "")] = {
                    **context, "context_key": key, "fork": fork, "decisions": selected,
                    "decision_values": {d: decision_registry[d]["options"][option] for d, option in selected.items()},
                    "order": order, "excluded": excluded,
                }
    return branches


def leaf_plan(state, branches):
    from .processes import process_plan
    leaves = sorted({node for branch in branches.values() for node in branch["order"]
                     if node not in branch["excluded"] and node not in state["graphs"][branch["fork"]]
                     and node not in branch["decisions"] and not state["quantities"][node].get("process")})
    plan = process_plan(state, branches)
    priors = {path["record"]["growth"] for path in plan["paths"].values() if path["steps"]}
    conditional = state.get("conditional_estimates", {})
    groups = {}
    leaf_groups = {}
    for node in sorted(set(leaves) | priors):
        conditions = conditional.get(node, {})
        group_names = {state["scenarios"][scenario]["group"] for scenario in conditions}
        require(len(group_names) <= 1, "Each leaf may condition on only one scenario group.")
        if not group_names:
            require(node in state["estimates"], f"Missing estimates for: {node}", "incomplete_model")
            continue
        group = next(iter(group_names))
        records = {key: value for key, value in sorted(state["scenarios"].items()) if value["group"] == group}
        require(math.isclose(math.fsum(record["p"] for record in records.values()), 1, abs_tol=1e-12, rel_tol=0),
                f"Scenario group {group} probabilities must sum to one.", "incomplete_scenarios")
        for scenario, record in records.items():
            require(record["p"] == 0 or scenario in conditions or node in state["estimates"],
                    f"Missing conditional estimate for {node} given {scenario}; supply it or an explicit unconditional fallback.",
                    "incomplete_scenarios")
        groups[group] = records
        leaf_groups[node] = group
    if len(groups) > 1:
        require(all(state["scenario_groups"][group]["independence_reason"].strip() for group in groups),
                "Multiple scenario groups require recorded independence reasons; otherwise encode a single joint regime group.",
                "unspecified_scenario_dependence")
    return leaves, groups, leaf_groups
