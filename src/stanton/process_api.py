"""Series and allocation project operations, shared by the CLI and Python API."""

from .common import identifier, name, now, require


class ProcessOperations:
    def series(self, series, *, base, growth, periods, rho, definition, reason, mode="multiplicative"):
        name(series)
        periods = [str(period) for period in periods]
        def mutate(state):
            require(series not in state.get("series", {}), "Series already exists.")
            require(base in state["quantities"], "Unknown initial anchor quantity.")
            require(periods, "Series periods must not be empty.")
            nodes = {period: series + "__" + period for period in periods}
            require(not (set(nodes.values()) & state["quantities"].keys()), "Generated series quantity name already exists.")
            units = state["quantities"][base]["units"]
            record = {"id": identifier("series"), "kind": "path", "definition": definition, "reason": reason,
                      "periods": periods, "nodes": nodes, "growth": growth, "rho": rho, "mode": mode, "units": units,
                      "anchors": {periods[0]: {"quantity": base, "reason": "Initial series anchor"}}, "recorded_at": now()}
            state.setdefault("series", {})[series] = record
            for period, node in nodes.items():
                name(node)
                state["quantities"][node] = {"name": node, "units": units, "definition": f"{definition}; period {period}",
                    "space": "linear" if mode == "additive" else state["quantities"][base]["space"], "status": "estimated",
                    "process": {"kind": "series", "name": series, "period": period}}
            state["schema_version"] = 3
            return {"series": series, **record}
        return self._edit("series", mutate)

    def series_anchor(self, series, period, quantity, *, reason):
        period = str(period)
        def mutate(state):
            require(series in state.get("series", {}) and state["series"][series]["kind"] == "path", "Unknown path series.")
            record = state["series"][series]
            require(period in record["periods"], "Unknown anchor period.")
            previous = record["id"]
            record.update(id=identifier("series"), previous=previous, recorded_at=now())
            record["anchors"][period] = {"quantity": quantity, "reason": reason}
            return {"series": series, **record}
        return self._edit("series_anchor", mutate)

    def periodic(self, series, *, over, profile, definition, reason, source=""):
        name(series)
        require(isinstance(profile, dict) and bool(profile), "Profile must map index values to quantity names.")
        profile = {str(key): value for key, value in profile.items()}
        def mutate(state):
            require(series not in state.get("series", {}) and series not in state["quantities"], "Series or output quantity already exists.")
            first = next(iter(profile.values()))
            require(first in state["quantities"], "Unknown profile quantity.")
            record = {"id": identifier("series"), "kind": "periodic", "index": over, "profile": profile, "node": series,
                      "definition": definition, "reason": reason, "source": source, "recorded_at": now()}
            state.setdefault("series", {})[series] = record
            state["quantities"][series] = {"name": series, "units": state["quantities"][first]["units"], "definition": definition,
                "space": state["quantities"][first]["space"], "status": "estimated", "process": {"kind": "series", "name": series}}
            state["schema_version"] = 3
            return {"series": series, **record}
        return self._edit("periodic", mutate)

    def relate_path(self, target, series, *, at=None, fork="main"):
        # Resolve inside the same transaction as the relation write.
        def mutate(state):
            require(series in state.get("series", {}), "Unknown series.")
            record = state["series"][series]
            if record["kind"] == "periodic":
                require(at is None, "Periodic series are evaluated using the saved query context; do not supply --at.")
                node = record["node"]
            else:
                period = str(at) if at is not None else record["periods"][-1]
                require(period in record["nodes"], "Unknown path period.")
                node = record["nodes"][period]
            require(target in state["quantities"] and fork in state["graphs"], "Unknown target or fork.")
            require(state["strategies"][fork]["status"] != "abandoned", "Cannot edit an abandoned strategy.")
            state["graphs"][fork][target] = {"id": identifier("relation"), "expression": node, "recorded_at": now()}
            return {"target": target, "fork": fork, "expression": node, "series": series}
        return self._edit("relate_path", mutate)

    def allocate(self, total, parts, *, allocation=None, reason, source=""):
        allocation = allocation or total + "_allocation"
        name(allocation)
        require(isinstance(parts, dict), "Parts must map quantity names to Dirichlet concentrations.")
        def mutate(state):
            require(total in state["quantities"], "Unknown allocation total.")
            require(allocation not in state.get("allocations", {}), "Allocation already exists.")
            require(not (parts.keys() & state["quantities"].keys()), "An allocation part quantity already exists.")
            units = state["quantities"][total]["units"]
            record = {"id": identifier("allocation"), "total": total, "parts": dict(parts), "reason": reason,
                      "source": source, "recorded_at": now()}
            state.setdefault("allocations", {})[allocation] = record
            for part in parts:
                name(part)
                state["quantities"][part] = {"name": part, "units": units, "definition": f"{part} share of conserved total {total}",
                    "space": "linear", "status": "estimated", "process": {"kind": "allocation", "name": allocation, "part": part}}
            state["schema_version"] = 3
            return {"allocation": allocation, **record}
        return self._edit("allocate", mutate)

    def series_show(self, series, *, run_id=None):
        from .process_reports import series_show
        return series_show(self, series, run_id)

    def allocation_show(self, allocation, *, run_id=None):
        from .process_reports import allocation_show
        return allocation_show(self, allocation, run_id)
