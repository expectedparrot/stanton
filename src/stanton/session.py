"""Public project operations shared by Python callers and the CLI."""

import locale
from copy import deepcopy
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .calibration_api import CalibrationOperations
from .common import identifier, name, nonblank, now, require
from .distributions import Distribution
from .evaluation_api import EvaluationOperations
from .lint import lint
from .process_api import ProcessOperations
from .sampling import sample as sample_model
from .sampling import validate_run
from .schemas import validate_state
from .store import Store
from .survey_api import SurveyOperations


class Session(ProcessOperations, SurveyOperations, EvaluationOperations, CalibrationOperations):
    def __init__(self, project=".", *, expected_revision=None):
        self.store = Store(project)
        self.expected_revision = expected_revision

    @classmethod
    def create(cls, project, *, title="Estimation project", timezone="UTC", asof=None):
        ZoneInfo(timezone)
        if asof:
            date.fromisoformat(asof)
        session = cls(project)
        state = {"schema_version": 6, "id": identifier("project"), "title": nonblank(title, "Title"),
                 "context": {"now": now(), "timezone": timezone, "locale": locale.getlocale()[0], "asof": asof},
                 "quantities": {}, "estimates": {}, "assumptions": {}, "graphs": {"main": {}},
                 "strategies": {"main": {"status": "active", "target": None, "reason": "Initial relation graph."}},
                 "bounds": {}, "merges": {}, "notes": {}, "scenario_groups": {}, "scenarios": {},
                 "conditional_estimates": {}, "decisions": {}, "definitions": {}, "bridges": {}, "series": {}, "allocations": {},
                 "surveys": {}, "resolutions": {}, "cohorts": {}, "calibrations": {}}
        session.store.init(state)
        return session

    def _edit(self, operation, mutate):
        def checked(state):
            original_version = state["schema_version"]
            result = mutate(state)
            state["schema_version"] = max(original_version, state["schema_version"])
            validate_state(state)
            return result
        return self.store.edit(operation, checked, self.expected_revision)

    def define(self, quantity, *, units, definition, space="log", status="estimated", predicates=None):
        name(quantity)
        def mutate(state):
            require(quantity not in state["quantities"], f"Quantity already exists: {quantity}")
            state["quantities"][quantity] = {"name": quantity, "units": units, "definition": definition,
                                               "space": space, "status": status}
            if predicates is not None:
                state["quantities"][quantity]["predicates"] = dict(predicates)
                state["schema_version"] = 2
            return {"quantity": state["quantities"][quantity]}
        return self._edit("define", mutate)

    def assumption(self, assumption, definition):
        name(assumption)
        def mutate(state):
            require(assumption not in state["assumptions"], "Assumption already exists.")
            state["assumptions"][assumption] = {"definition": nonblank(definition, "Definition")}
            return {"assumption": assumption}
        return self._edit("assumption", mutate)

    def estimate(self, quantity, distribution, *, source="", reason="", method="judgment", assumes=(),
                 kind="epistemic", note="", asof=None, ancestry=(), anchor_kind=None, given=None, definition_id=None):
        distribution = Distribution.from_dict(distribution.to_dict() if isinstance(distribution, Distribution) else distribution)
        def mutate(state):
            require(quantity in state["quantities"], f"Define quantity {quantity} first.", "not_found")
            require(quantity not in state.get("decisions", {}), "Decisions cannot receive stochastic estimates.")
            if given:
                require(given in state.get("scenarios", {}), "Unknown conditioning scenario.", "not_found")
                registry = state.setdefault("conditional_estimates", {}).setdefault(quantity, {})
                previous = registry.get(given)
            else:
                previous = state["estimates"].get(quantity)
            estimate = {"id": identifier("estimate"), "quantity": quantity, "distribution": distribution.to_dict(),
                        "source": source, "reason": reason, "method": method, "assumes": list(assumes),
                        "kind": kind, "note": note, "asof": asof, "ancestry": list(ancestry),
                        "anchor_kind": anchor_kind, "recorded_at": now(), "previous": previous["id"] if previous else None}
            if given:
                estimate["given"] = given
                state["schema_version"] = 2
            if definition_id:
                require(definition_id in state.get("definitions", {}), "Unknown estimate definition.", "not_found")
                estimate.update(definition_id=definition_id, definition_revision=state["definitions"][definition_id]["id"])
                state["schema_version"] = 2
            require(anchor_kind in {None, "point", "derived"}, "First release supports point and derived anchors.")
            if given:
                registry[given] = estimate
            else:
                state["estimates"][quantity] = estimate
            return {"estimate": estimate}
        return self._edit("estimate", mutate)

    def anchor(self, quantity, value, *, source, asof, ancestry=(), note="", kind="point", definition_id=None, given=None):
        nonblank(source, "Anchor source")
        nonblank(asof, "Anchor as-of date")
        return self.estimate(quantity, Distribution.from_point(value), source=source, asof=asof,
                             ancestry=ancestry, note=note, method="anchor", anchor_kind=kind, definition_id=definition_id, given=given)

    def scenario_group(self, group, *, definition, independence_reason=""):
        name(group)
        def mutate(state):
            state["schema_version"] = 2
            state.setdefault("scenario_groups", {})[group] = {"definition": definition, "independence_reason": independence_reason}
            return {"group": group, **state["scenario_groups"][group]}
        return self._edit("scenario_group", mutate)

    def scenario(self, scenario, *, p, definition, reason="", group="default"):
        name(scenario)
        name(group)
        def mutate(state):
            state["schema_version"] = 2
            state.setdefault("scenario_groups", {}).setdefault(group, {"definition": f"Mutually exclusive regimes in {group}", "independence_reason": ""})
            record = {"id": identifier("scenario"), "p": p, "definition": definition, "reason": reason, "group": group}
            state.setdefault("scenarios", {})[scenario] = record
            return {"scenario": scenario, **record}
        return self._edit("scenario", mutate)

    def decision(self, decision, *, options, definition, units="dimensionless", default=None):
        name(decision)
        def mutate(state):
            require(decision not in state["quantities"], "Decision quantity already exists.")
            state["schema_version"] = 2
            state["quantities"][decision] = {"name": decision, "definition": definition, "units": units, "space": "linear", "status": "known"}
            state.setdefault("decisions", {})[decision] = {"options": dict(options), "default": default,
                "status": "unasked", "selected": None, "reason": ""}
            return {"decision": decision, **state["decisions"][decision]}
        return self._edit("decision", mutate)

    def choose(self, decision, *, option=None, leave_open=False, reason):
        def mutate(state):
            require(decision in state.get("decisions", {}), "Unknown decision.", "not_found")
            require((option is not None) != bool(leave_open), "Select one option or leave the decision deliberately open.")
            record = state["decisions"][decision]
            record.pop("elicitation", None)
            record.update(status="open" if leave_open else "selected", selected=option, reason=reason)
            return {"decision": decision, **record}
        return self._edit("decision_disposition", mutate)

    def definition(self, definition, *, target, measure, predicates, owner="asker", role="branch", confidence=None, source=""):
        name(definition)
        def mutate(state):
            state["schema_version"] = 2
            registry = state.setdefault("definitions", {})
            previous = registry.get(definition)
            registry[definition] = {"id": identifier("definition"), "target": target, "measure": measure,
                "predicates": dict(predicates), "owner": owner, "role": role, "confidence": confidence, "source": source,
                "previous": previous["id"] if previous else None, "recorded_at": now()}
            return {"definition": definition, **registry[definition]}
        return self._edit("definition", mutate)

    def bridge(self, quantity, from_definition, to_definition, distribution, *, source, reason=""):
        name(quantity)
        nonblank(source, "Bridge source")
        distribution = Distribution.from_dict(distribution.to_dict() if isinstance(distribution, Distribution) else distribution)
        def mutate(state):
            require(quantity not in state["quantities"], "Bridge quantity already exists; revise its estimate with estimate.")
            require(from_definition in state.get("definitions", {}) and to_definition in state.get("definitions", {}), "Unknown bridge definition.")
            state["schema_version"] = 2
            state["quantities"][quantity] = {"name": quantity, "units": "dimensionless", "space": "log", "status": "estimated",
                "definition": f"Multiplicative conversion from {from_definition} to {to_definition}"}
            state["estimates"][quantity] = {"id": identifier("estimate"), "quantity": quantity, "distribution": distribution.to_dict(),
                "source": source, "reason": reason, "method": "definition_bridge", "assumes": [], "kind": "epistemic", "note": "",
                "asof": None, "ancestry": [], "anchor_kind": None, "recorded_at": now(), "previous": None}
            state.setdefault("bridges", {})[quantity] = {"from": from_definition, "to": to_definition,
                "from_revision": state["definitions"][from_definition]["id"], "to_revision": state["definitions"][to_definition]["id"]}
            return {"bridge": quantity, **state["bridges"][quantity], "estimate": state["estimates"][quantity]}
        return self._edit("bridge", mutate)

    def relate(self, target, expression, *, fork="main"):
        def mutate(state):
            require(target in state["quantities"] and fork in state["graphs"], "Unknown target or fork.", "not_found")
            require(state["strategies"][fork]["status"] != "abandoned", "Cannot edit an abandoned strategy.")
            state["graphs"][fork][target] = {"id": identifier("relation"), "expression": expression, "recorded_at": now()}
            return {"target": target, "fork": fork, "expression": expression}
        return self._edit("relate", mutate)

    def fork(self, target, strategy, *, source="main", reason=""):
        name(strategy)
        def mutate(state):
            require(target in state["quantities"] and source in state["graphs"], "Unknown target or source fork.", "not_found")
            require(strategy not in state["graphs"], "Fork already exists.")
            state["graphs"][strategy] = deepcopy(state["graphs"][source])
            state["strategies"][strategy] = {"status": "active", "target": target, "reason": reason, "source": source}
            return {"fork": strategy, "target": target, "leaves": "global"}
        return self._edit("fork", mutate)

    def abandon(self, strategy, reason):
        def mutate(state):
            require(strategy in state["strategies"] and strategy != "main", "Unknown strategy or main cannot be abandoned.")
            state["strategies"][strategy].update(status="abandoned", reason=nonblank(reason, "Abandonment reason"))
            return {"strategy": strategy, **state["strategies"][strategy]}
        return self._edit("abandon", mutate)

    def note(self, node, text):
        def mutate(state):
            require(any(node in state.get(registry, {}) for registry in
                        ("quantities", "strategies", "assumptions", "scenarios", "scenario_groups", "definitions", "series", "allocations", "surveys")), "Unknown node.", "not_found")
            note = {"text": nonblank(text, "Note"), "recorded_at": now()}
            state["notes"].setdefault(node, []).append(note)
            return {"node": node, "note": note}
        return self._edit("note", mutate)

    def bound(self, target, *, lower=None, upper=None, reason, clip=False):
        def mutate(state):
            state["bounds"][target] = {"lower": lower, "upper": upper, "reason": reason, "clip": clip}
            return {"target": target, "bound": state["bounds"][target]}
        return self._edit("bound", mutate)

    def merge(self, target, forks, weights, *, reason):
        def mutate(state):
            state["merges"][target] = {"forks": list(forks), "weights": list(weights), "reason": reason, "method": "mixture"}
            for fork in forks:
                require(fork in state["strategies"] and state["strategies"][fork]["status"] != "abandoned", "Merge needs non-abandoned forks.")
                state["strategies"][fork]["status"] = "merged"
            return {"target": target, "merge": state["merges"][target]}
        return self._edit("merge", mutate)

    def context(self, *, at=None):
        if at is None:
            state, revision = self.store.read()
            return {"revision": revision, **state["context"]}
        parsed = datetime.fromisoformat(at)
        require(parsed.tzinfo is not None, "Query time must include a timezone.")
        def mutate(state):
            state["context"]["now"] = parsed.isoformat()
            return {"context": state["context"]}
        return self._edit("context", mutate)

    def sample(self, target, *, n=20000, seed=0, fork=None, definitions=None, decisions=None, predicate_flips=False):
        state, revision = self.store.read()
        require(self.expected_revision is None or self.expected_revision == revision, "Project revision changed.", "stale_revision")
        return self.store.put_run(sample_model(state, target, n=n, seed=seed, fork=fork, definitions=definitions,
                                              decisions=decisions, predicate_flips=predicate_flips), revision)

    def check(self, claim, target, *, definition=None, run_id=None):
        from .checks import check_claim
        run = self.store.run(run_id, target)
        result = check_claim(run, claim, definition)
        _, revision = self.store.read()
        return {**result, "working_revision": revision, "newer_working_revision": revision != run["revision"]}

    def show(self, target=None, *, run_id=None, quantiles=(5, 25, 50, 75, 95)):
        from .reports import show
        run = self.store.run(run_id, target)
        _, revision = self.store.read()
        return show(run, revision, quantiles)

    def audit(self, target, *, run_id=None):
        from .reports import audit
        run = self.store.run(run_id, target) if run_id else None
        state, revision = self.store.read(run["revision"] if run else None)
        return audit(state, revision, target, run)

    def lint(self):
        state, revision = self.store.read()
        return {"revision": revision, "warnings": lint(state)}

    def status(self):
        state, revision = self.store.read()
        return {"project": str(self.store.root), "title": state["title"], "revision": revision,
                "quantities": list(state["quantities"]), "estimates": len(state["estimates"]),
                "strategies": state["strategies"], "scenarios": state.get("scenarios", {}),
                "decisions": state.get("decisions", {}), "definitions": state.get("definitions", {}),
                "series": state.get("series", {}), "allocations": state.get("allocations", {}),
                "surveys": {key: {"instrument_id": survey["instrument"]["id"], "responses": len(survey["responses"]),
                                   "proposals": len(survey["proposals"])} for key, survey in state.get("surveys", {}).items()},
                "resolutions": len(state.get("resolutions", {})), "cohorts": list(state.get("cohorts", {})),
                "calibrations": list(state.get("calibrations", {})),
                "warnings": lint(state)}

    def validate(self):
        from .calibration_validation import validate_artifact_history
        from .elicitation import validate_survey_history
        return self.store.validate(validate_state, validate_run, validate_survey_history, validate_artifact_history)

    def save(self, path):
        return self.store.export(path)

    def load(self, path):
        from .calibration_validation import validate_artifact_history
        from .elicitation import validate_survey_history
        return self.store.restore(path, validate_state, validate_run, validate_survey_history, validate_artifact_history)
