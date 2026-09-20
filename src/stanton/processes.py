"""Global series and allocation nodes, with explicit dependency and sampling rules."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
from scipy.special import ndtr

from .common import finite, name, nonblank, require
from .distributions import Distribution
from .expressions import UNITS, magnitude, parse, unit


def selected_period(state, record):
    timestamp = datetime.fromisoformat(state["context"]["now"])
    require(timestamp.tzinfo is not None, "Periodic profiles require a timezone-aware query time.")
    local = timestamp.astimezone(ZoneInfo(state["context"]["timezone"]))
    return str(local.hour if record["index"] == "hour_of_day" else local.weekday())


def dependencies(state, fork, node, *, all_periods=False):
    process = state["quantities"][node].get("process")
    if not process:
        return parse(state["graphs"][fork][node]["expression"])[1] if node in state["graphs"][fork] else set()
    if process["kind"] == "allocation":
        return {state["allocations"][process["name"]]["total"]}
    record = state["series"][process["name"]]
    if record["kind"] == "periodic":
        return set(record["profile"].values()) if all_periods else {record["profile"][selected_period(state, record)]}
    period = process["period"]
    if period in record["anchors"]:
        return {record["anchors"][period]["quantity"]}
    index = record["periods"].index(period)
    return {record["nodes"][record["periods"][index - 1]]}


def validate_processes(state):
    expected = {}
    for key, record in state.get("series", {}).items():
        name(key)
        nonblank(record["definition"], "Series definition")
        nonblank(record["reason"], "Series modeling reason")
        require(record["kind"] in {"path", "periodic"}, "Unknown series kind.")
        if record["kind"] == "periodic":
            require(record["index"] in {"hour_of_day", "day_of_week"}, "Unsupported periodic index.")
            size = 24 if record["index"] == "hour_of_day" else 7
            require(set(record["profile"]) == {str(i) for i in range(size)}, "Periodic profile must cover every index value.")
            require(set(record["profile"].values()) <= state["quantities"].keys(), "Unknown profile quantity.")
            require(record["node"] in state["quantities"], "Missing periodic output quantity.")
            output_units = unit(state["quantities"][record["node"]]["units"])
            require(all(unit(state["quantities"][q]["units"]).is_compatible_with(output_units)
                        for q in record["profile"].values()), "Profile values must have compatible units.")
            expected[record["node"]] = {"kind": "series", "name": key}
        else:
            periods = record["periods"]
            require(isinstance(periods, list) and 2 <= len(periods) <= 256 and len(set(periods)) == len(periods),
                    "A path needs 2–256 distinct, equally spaced period labels.")
            require(all(isinstance(p, str) and re.fullmatch(r"[A-Za-z0-9_]+", p) for p in periods), "Period labels use letters, digits, and underscores.")
            require(record["mode"] in {"multiplicative", "additive"}, "Unknown path mode.")
            require(-1 <= finite(record["rho"]) <= 1, "AR(1) persistence must lie in [-1, 1].")
            require(set(record["nodes"]) == set(periods), "Path node registry does not match its periods.")
            require(periods[0] in record["anchors"] and set(record["anchors"]) <= set(periods), "Path needs an initial anchor and valid anchor periods.")
            growth = record["growth"]
            require(growth in state["quantities"] and growth not in state.get("decisions", {}) and
                    not state["quantities"][growth].get("process") and not state["quantities"][growth].get("predicates") and
                    all(growth not in graph for graph in state["graphs"].values()), "Growth prior must be a primitive distribution quantity.")
            output_units = unit(record["units"])
            required_units = unit("dimensionless") if record["mode"] == "multiplicative" else output_units
            require(unit(state["quantities"][growth]["units"]).is_compatible_with(required_units), "Growth prior has incompatible units.")
            for period, anchor in record["anchors"].items():
                require(anchor["quantity"] in state["quantities"], "Unknown path anchor quantity.")
                require(unit(state["quantities"][anchor["quantity"]]["units"]).is_compatible_with(output_units), "Path anchor has incompatible units.")
                nonblank(anchor["reason"], "Path anchor reason")
            for period, node in record["nodes"].items():
                require(node in state["quantities"] and unit(state["quantities"][node]["units"]) == output_units, "Missing or inconsistent series output.")
                expected[node] = {"kind": "series", "name": key, "period": period}
    for key, record in state.get("allocations", {}).items():
        name(key)
        nonblank(record["reason"], "Allocation reason")
        total = record["total"]
        require(total in state["quantities"] and total in state["estimates"], "Allocation requires a known point total.")
        require(not state.get("conditional_estimates", {}).get(total) and not state["quantities"][total].get("process") and
                not state["quantities"][total].get("predicates") and all(total not in graph for graph in state["graphs"].values()),
                "Allocation total must be an unmasked, unconditional point estimate.")
        dist = Distribution.from_dict(state["estimates"][total]["distribution"])
        require(dist.family == "point" and dist.parameters[0] >= 0, "Allocation total must be a nonnegative known point.")
        parts = record["parts"]
        require(isinstance(parts, dict) and 2 <= len(parts) <= 256, "Allocation needs 2–256 named parts.")
        for part, alpha in parts.items():
            require(finite(alpha, "Dirichlet concentration") > 0, "Dirichlet concentrations must be positive.")
            require(part in state["quantities"] and unit(state["quantities"][part]["units"]) == unit(state["quantities"][total]["units"]), "Allocation part units must match the total.")
            expected[part] = {"kind": "allocation", "name": key, "part": part}
    actual = {node: q["process"] for node, q in state["quantities"].items() if q.get("process")}
    require(actual == expected, "Generated quantity registry is inconsistent.")
    for node in actual:
        require(node not in state["estimates"] and node not in state.get("conditional_estimates", {}) and
                node not in state.get("decisions", {}) and all(node not in graph for graph in state["graphs"].values()),
                "Generated quantities cannot receive estimates, decisions, or fork-local relations.")


def process_plan(state, branches):
    plan = {"paths": {}, "allocations": {}, "periodic": {}}
    for branch in branches.values():
        for node in branch["order"]:
            if node in branch["excluded"]:
                continue
            process = state["quantities"][node].get("process")
            if not process:
                continue
            key = process["name"]
            if process["kind"] == "allocation":
                plan["allocations"][key] = state["allocations"][key]
                continue
            record = state["series"][key]
            if record["kind"] == "periodic":
                period = selected_period(state, record)
                plan["periodic"][key] = {"period": period, "quantity": record["profile"][period], "record": record}
                continue
            entry = plan["paths"].setdefault(key, {"record": record, "steps": 0})
            if process["period"] not in record["anchors"]:
                entry["steps"] = max(entry["steps"], record["periods"].index(process["period"]))
    return plan


def prior_value(state, node, uniforms, groups, leaf_groups, regimes):
    default = state["estimates"].get(node)
    if node not in leaf_groups:
        return Distribution.from_dict(default["distribution"]).ppf(uniforms)
    group = leaf_groups[node]
    result = np.empty(len(uniforms))
    for index, scenario in enumerate(groups[group]):
        mask = regimes[group] == index
        if np.any(mask):
            estimate = state.get("conditional_estimates", {}).get(node, {}).get(scenario, default)
            result[mask] = Distribution.from_dict(estimate["distribution"]).ppf(uniforms[mask])
    return result


def make_generators(plan, seed):
    from .sampling import stream
    generators = {}
    for key, path in plan["paths"].items():
        for period in path["record"]["periods"][1:path["steps"] + 1]:
            generators["series:" + key + ":" + period] = stream(seed, "series:" + key + ":" + period)
    for key in plan["allocations"]:
        generators["allocation:" + key] = stream(seed, "allocation:" + key)
    return generators


def draw_processes(state, plan, generators, n, groups, leaf_groups, regimes):
    draws = {"growth": {}, "shares": {}}
    for key, path in plan["paths"].items():
        record = path["record"]
        latent = None
        draws["growth"][key] = {}
        for period in record["periods"][1:path["steps"] + 1]:
            noise = generators["series:" + key + ":" + period].standard_normal(n)
            latent = noise if latent is None else record["rho"] * latent + np.sqrt(1 - record["rho"]**2) * noise
            uniforms = np.clip(ndtr(latent), np.nextafter(0.0, 1.0), np.nextafter(1.0, 0.0))
            values = prior_value(state, record["growth"], uniforms, groups, leaf_groups, regimes)
            target_units = "dimensionless" if record["mode"] == "multiplicative" else record["units"]
            values = magnitude(UNITS.Quantity(values, state["quantities"][record["growth"]]["units"]), target_units, n)
            if record["mode"] == "multiplicative":
                require(np.all(values > 0), "Multiplicative paths require strictly positive growth multipliers; use a positive-support prior.")
            draws["growth"][key][period] = values
    for key, allocation in plan["allocations"].items():
        parts = sorted(allocation["parts"])
        matrix = generators["allocation:" + key].dirichlet([allocation["parts"][p] for p in parts], size=n)
        require(np.all(np.isfinite(matrix)), "Dirichlet parameters produced nonfinite shares; revise concentrations.")
        draws["shares"][key] = {part: matrix[:, i] for i, part in enumerate(parts)}
    return draws


def evaluate_generated(state, node, values, draws, n):
    process = state["quantities"][node]["process"]
    output_units = state["quantities"][node]["units"]
    key = process["name"]
    if process["kind"] == "allocation":
        total = state["allocations"][key]["total"]
        return magnitude(values[total] * draws["shares"][key][process["part"]], output_units, n)
    record = state["series"][key]
    if record["kind"] == "periodic":
        return magnitude(values[record["profile"][selected_period(state, record)]], output_units, n)
    period = process["period"]
    if period in record["anchors"]:
        return magnitude(values[record["anchors"][period]["quantity"]], output_units, n)
    previous = record["nodes"][record["periods"][record["periods"].index(period) - 1]]
    growth = draws["growth"][key][period]
    result = values[previous] * growth if record["mode"] == "multiplicative" else values[previous] + UNITS.Quantity(growth, record["units"])
    return magnitude(result, output_units, n)


def validate_draws(plan, draws, n):
    require(set(draws) == {"growth", "shares"} and set(draws["growth"]) == set(plan["paths"]) and
            set(draws["shares"]) == set(plan["allocations"]), "Process draw registry mismatch.")
    for key, path in plan["paths"].items():
        require(set(draws["growth"][key]) == set(path["record"]["periods"][1:path["steps"] + 1]), "Saved growth periods do not match the path.")
        for values in draws["growth"][key].values():
            arr = np.asarray(values)
            require(arr.shape == (n,) and np.all(np.isfinite(arr)), "Invalid saved path growth.")
            if path["record"]["mode"] == "multiplicative":
                require(np.all(arr > 0), "Saved multiplicative growth is not positive.")
    for key, allocation in plan["allocations"].items():
        require(set(draws["shares"][key]) == set(allocation["parts"]), "Allocation share registry mismatch.")
        arrays = [np.asarray(draws["shares"][key][part]) for part in sorted(allocation["parts"])]
        require(all(a.shape == (n,) and np.all(np.isfinite(a) & (a >= 0) & (a <= 1)) for a in arrays), "Invalid saved allocation shares.")
        require(np.allclose(np.sum(arrays, axis=0), 1, rtol=0, atol=1e-12), "Allocation shares do not conserve the total.")


def validate_growth_support(state, plan, draws, groups, leaf_groups, regimes, n):
    for key, path in plan["paths"].items():
        if not path["steps"]:
            continue
        record = path["record"]
        node = record["growth"]
        default = state["estimates"].get(node)
        if node not in leaf_groups:
            partitions = [(np.ones(n, dtype=bool), default)]
        else:
            group = leaf_groups[node]
            partitions = [(np.asarray(regimes[group]) == i,
                           state.get("conditional_estimates", {}).get(node, {}).get(scenario, default))
                          for i, scenario in enumerate(groups[group])]
        target_units = "dimensionless" if record["mode"] == "multiplicative" else record["units"]
        for mask, estimate in partitions:
            if not np.any(mask):
                continue
            dist = Distribution.from_dict(estimate["distribution"])
            # Convert support to the same units as the saved process draws.
            support = UNITS.Quantity(dist.ppf(np.array([0, 1])), state["quantities"][node]["units"]).to(target_units).magnitude
            empirical = (UNITS.Quantity(dist.parameters, state["quantities"][node]["units"]).to(target_units).magnitude
                         if dist.family == "empirical" else None)
            for values in draws["growth"][key].values():
                values = np.asarray(values)[mask]
                require(np.all((values >= support[0]) & (values <= support[1])), "Saved growth falls outside its scenario prior support.")
                if empirical is not None:
                    require(np.all(np.isin(values, empirical)), "Saved growth falls outside empirical support.")
