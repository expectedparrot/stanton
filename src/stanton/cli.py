"""JSON-first CLI over the same public operations used from Python."""

import argparse
import json
import sqlite3
import sys
import zlib
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

from .common import StantonError, read_json, require
from .distributions import Distribution
from .guidance import GUIDE, next_actions
from .reports import report_context
from .research import research_workflow
from .schemas import SCHEMAS
from .session import Session


class Parser(argparse.ArgumentParser):
    def error(self, message):
        if "--asof" in message:
            message += " Example: stanton anchor NAME --value 100 --source 'SOURCE' --asof 2026-01-01"
        elif "--text" in message:
            message += " Note text is positional: stanton note TARGET 'RESEARCH SUMMARY'"
        elif "--status" in message:
            message += " For report issue, status comes from review.json; set its status to provisional or reviewed, then save a new research review."
        raise StantonError(message, "invalid_arguments")

    def parse_known_args(self, args=None, namespace=None):
        # Python 3.11 otherwise loses nargs='*' positionals after an option.
        if getattr(self, "intermixed", False) and not getattr(self, "_parsing_intermixed", False):
            self._parsing_intermixed = True
            try:
                return self.parse_known_intermixed_args(args, namespace)
            finally:
                self._parsing_intermixed = False
        return super().parse_known_args(args, namespace)


def csv(text, cast=str):
    return [cast(value.strip()) for value in text.split(",") if value.strip()]


def assignments(text, cast=str):
    result = {}
    for item in csv(text):
        parts = item.split("=", 1)
        require(len(parts) == 2 and parts[0].strip() and parts[1].strip(), "Use comma-separated name=value pairs.")
        key, value = (part.strip() for part in parts)
        require(key not in result, f"Duplicate assignment: {key}")
        result[key] = cast(value)
    return result


def boolean(text):
    require(text.lower() in {"true", "false"}, "Predicate values must be true or false.")
    return text.lower() == "true"


def parser():
    shared = Parser(add_help=False)
    shared.add_argument("--project", default=argparse.SUPPRESS, help="Project directory (default: current directory)")
    shared.add_argument("--expect-revision", type=int, default=argparse.SUPPRESS)
    shared.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Versioned JSON output (the default)")
    root = Parser(prog="stanton", description="Sourced numerical estimates with inspectable uncertainty", parents=[shared])
    commands = root.add_subparsers(dest="command", required=True)

    def add(key, **kwargs):
        return commands.add_parser(key, parents=[shared], **kwargs)

    p = add("init", help="Create a local estimation project")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--title", default="Estimation project")
    p.add_argument("--timezone", default="UTC")
    p.add_argument("--asof", help="Information cutoff, YYYY-MM-DD")
    add("version")
    add("guide", help="Read the high-effort agent research contract and command reference")
    p = add("schema")
    p.add_argument("kind", nargs="?", choices=sorted(SCHEMAS))
    for key in ("status", "next", "validate", "lint"):
        add(key)
    p = add("define", help="Define a named scalar and its units")
    p.add_argument("name")
    p.add_argument("--units", required=True)
    p.add_argument("--def", dest="definition", required=True)
    p.add_argument("--space", choices=["log", "linear", "logit"], default="log")
    p.add_argument("--status", choices=["known", "estimated", "target"], default="estimated")
    p.add_argument("--when", help="Inclusion predicates, e.g. commerce=true,adult=false")
    p = add("assumption", help="Register a textual assumption (not a sampled factor)")
    p.add_argument("name")
    p.add_argument("--def", dest="definition", required=True)
    p = add("estimate", help="Add or revise a distribution with provenance")
    p.add_argument("name", nargs="?")
    shape = p.add_mutually_exclusive_group(required=True)
    shape.add_argument("--interval", nargs=2, type=float, metavar=("LOW", "HIGH"))
    shape.add_argument("--value", type=float)
    shape.add_argument("--samples", help="JSON file containing an array of samples")
    shape.add_argument("--quantiles", help="Percent:value pairs, e.g. 5:10,50:20,95:40; bounded endpoint tails")
    shape.add_argument("--from", dest="input", help="Complete estimate input JSON; see schema estimate")
    p.add_argument("--p", type=float, default=.8)
    p.add_argument("--shape", choices=["normal", "lognormal", "logitnormal"], help="Default follows quantity space: linear=normal, log=lognormal, logit=logitnormal")
    p.add_argument("--source", default="")
    p.add_argument("--reason", default="")
    p.add_argument("--method", default="judgment")
    p.add_argument("--assumes", default="")
    p.add_argument("--kind", choices=["epistemic", "aleatoric"], default="epistemic")
    p.add_argument("--note", default="")
    p.add_argument("--asof")
    p.add_argument("--ancestry", action="append", default=[])
    p.add_argument("--given", help="Condition this estimate on a named scenario")
    p.add_argument("--definition", dest="definition_id", help="Definition attached to this source/estimate")
    p = add("anchor", help="Record a sourced, dated point")
    p.add_argument("name")
    p.add_argument("--value", type=float, required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--asof", required=True)
    p.add_argument("--ancestry", action="append", default=[])
    p.add_argument("--note", default="")
    p.add_argument("--kind", choices=["point", "derived"], default="point")
    p.add_argument("--given")
    p.add_argument("--definition", dest="definition_id")
    p = add("scenario", help="Declare a mutually exclusive scenario partition")
    sub = p.add_subparsers(dest="action", required=True)
    p = sub.add_parser("group", parents=[shared])
    p.add_argument("name")
    p.add_argument("--def", dest="definition", required=True)
    p.add_argument("--independent-reason", default="")
    p = sub.add_parser("define", parents=[shared])
    p.add_argument("name")
    p.add_argument("--p", type=float, required=True)
    p.add_argument("--def", dest="definition", required=True)
    p.add_argument("--reason", default="")
    p.add_argument("--group", default="default")
    p = add("decision", help="Register controlled options and record a selection or open disposition")
    sub = p.add_subparsers(dest="action", required=True)
    p = sub.add_parser("define", parents=[shared])
    p.add_argument("name")
    p.add_argument("--options", required=True, help="Named numeric options, e.g. small=1,large=2")
    p.add_argument("--def", dest="definition", required=True)
    p.add_argument("--units", default="dimensionless")
    p.add_argument("--default")
    p = sub.add_parser("choose", parents=[shared])
    p.add_argument("name")
    choice = p.add_mutually_exclusive_group(required=True)
    choice.add_argument("--option")
    choice.add_argument("--open", dest="leave_open", action="store_true")
    p.add_argument("--reason", required=True)
    p = add("definition", help="Register a base measure and inclusion predicates")
    sub = p.add_subparsers(dest="action", required=True)
    p = sub.add_parser("define", parents=[shared])
    p.add_argument("name")
    p.add_argument("--target", required=True)
    p.add_argument("--measure", required=True)
    p.add_argument("--predicates", required=True, help="Named boolean predicates, e.g. commerce=false")
    p.add_argument("--owner", choices=["asker", "claimant", "reconstructed"], default="asker")
    p.add_argument("--role", choices=["primary", "branch"], default="branch")
    p.add_argument("--confidence", choices=["high", "medium", "low", "unknown"])
    p.add_argument("--source", default="")
    p = add("bridge", help="Record an uncertain multiplicative definition conversion")
    p.add_argument("from_definition")
    p.add_argument("to_definition")
    p.add_argument("--name", required=True)
    p.add_argument("--interval", nargs=2, type=float, required=True)
    p.add_argument("--p", type=float, default=.8)
    p.add_argument("--shape", choices=["normal", "lognormal", "logitnormal"], default="lognormal")
    p.add_argument("--source", required=True)
    p.add_argument("--reason", default="")
    p = add("relate")
    p.intermixed = True
    p.add_argument("target")
    p.add_argument("expression", nargs="*")
    p.add_argument("--fork", default="main")
    p.add_argument("--path", action="store_true", help="Relate the target to a named series")
    p.add_argument("--series")
    p.add_argument("--at", help="Path period label; default: last period")
    p = add("series", help="Define persistent paths and query-time periodic profiles")
    sub = p.add_subparsers(dest="action", required=True)
    p = sub.add_parser("define", parents=[shared])
    p.add_argument("name")
    p.add_argument("--base", required=True)
    p.add_argument("--growth", required=True, help="Primitive distribution quantity used as the per-step marginal prior")
    p.add_argument("--periods", required=True, help="Ordered, equally spaced labels, e.g. 2026,2027,2028")
    p.add_argument("--rho", type=float, required=True, help="AR(1) correlation of latent normal shocks")
    p.add_argument("--mode", choices=["multiplicative", "additive"], default="multiplicative")
    p.add_argument("--def", dest="definition", required=True)
    p.add_argument("--reason", required=True)
    p = sub.add_parser("anchor", parents=[shared])
    p.add_argument("name")
    p.add_argument("period")
    p.add_argument("--quantity", required=True)
    p.add_argument("--reason", required=True)
    p = sub.add_parser("periodic", parents=[shared])
    p.add_argument("name")
    p.add_argument("--over", choices=["hour_of_day", "day_of_week"], required=True)
    p.add_argument("--profile", required=True, help="JSON map from every index bucket to a quantity name")
    p.add_argument("--def", dest="definition", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--source", default="")
    p = sub.add_parser("show", parents=[shared])
    p.add_argument("name")
    p.add_argument("--run", dest="run_id")
    p = add("allocate", help="Partition a known total into Dirichlet-distributed shares")
    p.add_argument("total")
    p.add_argument("--name", dest="allocation")
    p.add_argument("--into", required=True, help="Comma-separated names for the generated part quantities")
    p.add_argument("--alpha", required=True, help="Positive Dirichlet concentrations in the same order as --into")
    p.add_argument("--reason", required=True)
    p.add_argument("--source", default="")
    p = add("allocation")
    sub = p.add_subparsers(dest="action", required=True)
    p = sub.add_parser("show", parents=[shared])
    p.add_argument("name")
    p.add_argument("--run", dest="run_id")
    p = add("fork")
    p.add_argument("target")
    p.add_argument("--as", dest="strategy", required=True)
    p.add_argument("--from", dest="source", default="main")
    p.add_argument("--reason", default="")
    p = add("strategy")
    sub = p.add_subparsers(dest="action", required=True)
    p = sub.add_parser("abandon", parents=[shared])
    p.add_argument("name")
    p.add_argument("--reason", required=True)
    p = add("note")
    p.add_argument("node")
    p.add_argument("text")
    p = add("bound")
    p.add_argument("target")
    p.add_argument("--lower", type=float)
    p.add_argument("--upper", type=float)
    p.add_argument("--reason", required=True)
    p.add_argument("--clip", action="store_true")
    p = add("merge")
    p.add_argument("target")
    p.add_argument("--from", dest="forks", required=True)
    p.add_argument("--weights", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--method", choices=["mixture"], default="mixture")
    p = add("sample")
    p.add_argument("target")
    p.add_argument("-n", type=int, default=20000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--fork")
    p.add_argument("--correlate", choices=["auto"], default="auto")
    p.add_argument("--definitions", help="Comma-separated definitions, or all (default: primary definition)")
    p.add_argument("--decision", action="append", default=[], help="Run-only selection, NAME=OPTION; repeat for multiple decisions")
    p.add_argument("--predicate-flips", action="store_true", help="Also evaluate every single-predicate flip with paired draws")
    for command in ("show", "compare"):
        p = add(command)
        p.add_argument("target")
        p.add_argument("--run", dest="run_id")
        p.add_argument("--quantiles", default="5,25,50,75,95")
        p.add_argument("--coverages", default=".8,.9", help="Central model interval coverages")
        p.add_argument("--by", choices=["fork", "definition", "decision"], default="fork")
        p.add_argument("--format", choices=["json", "text"], default="json")
    p = add("audit")
    p.add_argument("target")
    p.add_argument("--run", dest="run_id")
    p = add("check", help="Place a claim in a saved distribution and inspect saved predicate flips")
    p.add_argument("claim", type=float)
    p.add_argument("--against", required=True, help="TARGET or TARGET@DEFINITION")
    p.add_argument("--run", dest="run_id")
    p = add("resolve", help="Record outcome evidence against one saved forecast context")
    p.add_argument("target")
    p.add_argument("--event", required=True)
    p.add_argument("--run", dest="run_id", required=True)
    p.add_argument("--outcome", type=float, required=True)
    p.add_argument("--units", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--observed-at", required=True, help="When the outcome was observed; timezone-aware ISO timestamp")
    p.add_argument("--definition")
    p.add_argument("--decision", action="append", default=[])
    p.add_argument("--replaces", help="Current resolution ID when correcting evidence")
    p.add_argument("--reason", default="")
    p = add("resolution")
    sub = p.add_subparsers(dest="action", required=True)
    p = sub.add_parser("show", parents=[shared])
    p.add_argument("event")
    p.add_argument("--resolution", dest="resolution_id")
    p = add("score", help="Score the saved empirical forecast against a recorded outcome")
    p.add_argument("event")
    p.add_argument("--resolution", dest="resolution_id")
    p.add_argument("--run", dest="run_id", help="Alternative saved forecast of the same event and scope")
    p.add_argument("--units")
    p.add_argument("--coverages", default=".5,.8,.95")
    p = add("cohort", help="Register fixed event groups and evaluate train/test splits separately")
    sub = p.add_subparsers(dest="action", required=True)
    p = sub.add_parser("define", parents=[shared])
    p.add_argument("name")
    p.add_argument("--members", required=True, help="JSON array of event, run_id, group, split, and optional context selectors")
    p.add_argument("--units", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--coverages", default=".5,.8,.95")
    for action in ("show", "evaluate"):
        p = sub.add_parser(action, parents=[shared])
        p.add_argument("name")
        p.add_argument("--revision", type=int, help="Read outcomes and cohort membership at this project revision")
        if action == "evaluate":
            p.add_argument("--include-retrospective", action="store_true")
    p = add("calibration", help="Fit training-only spread adjustments and compare saved forecasts")
    sub = p.add_subparsers(dest="action", required=True)
    p = sub.add_parser("fit", parents=[shared])
    p.add_argument("name")
    p.add_argument("--cohort", required=True)
    p.add_argument("--method", required=True, help="strategy:<fork> or mixture")
    p.add_argument("--reason", required=True)
    p.add_argument("--scales", default=".25,.5,.75,1,1.25,1.5,2,3,4")
    p.add_argument("--include-retrospective", action="store_true")
    for action in ("show", "evaluate"):
        p = sub.add_parser(action, parents=[shared])
        p.add_argument("name")
        p.add_argument("--revision", type=int)
    p = sub.add_parser("apply", parents=[shared])
    p.add_argument("name")
    p.add_argument("--run", dest="run_id", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--definition")
    p.add_argument("--decision", action="append", default=[])
    p = add("research", help="Record run-bound research evidence and inspect review status")
    sub = p.add_subparsers(dest="action", required=True)
    p = sub.add_parser("template", parents=[shared])
    p.add_argument("target")
    p.add_argument("--run", dest="run_id")
    p.add_argument("--output", required=True)
    p = sub.add_parser("review", parents=[shared])
    p.add_argument("name")
    p.add_argument("--from", dest="input", required=True)
    p = sub.add_parser("check", parents=[shared])
    p.add_argument("--from", dest="input", required=True)
    p = sub.add_parser("show", parents=[shared])
    p.add_argument("name")
    p = sub.add_parser("status", parents=[shared])
    p.add_argument("target", nargs="?")
    p = add("report")
    sub = p.add_subparsers(dest="action", required=True)
    p = sub.add_parser("context", parents=[shared])
    p.add_argument("target")
    p.add_argument("--run", dest="run_id")
    p.add_argument("--output")
    p = sub.add_parser("issue", parents=[shared])
    p.add_argument("name")
    p.add_argument("--review", required=True)
    p.add_argument("--method", help="strategy:FORK or mixture; required if several methods exist")
    p.add_argument("--coverages", default=".8,.9")
    p.add_argument("--definition")
    p.add_argument("--decision", action="append", default=[])
    p = sub.add_parser("show", parents=[shared])
    p.add_argument("name")
    for command in ("save", "load"):
        p = add(command)
        p.add_argument("path")
    p = add("context")
    p.add_argument("action", choices=["now"])
    p.add_argument("--at", help="Explicit timezone-aware query time; omit to read frozen context")
    p = add("survey", help="Draft, compile, import, and review bound survey responses")
    sub = p.add_subparsers(dest="action", required=True)
    p = sub.add_parser("draft", parents=[shared])
    p.add_argument("name")
    p.add_argument("--phase", choices=["triage", "targeted"], default="targeted")
    p.add_argument("--budget", type=int, default=10, help="Maximum model slots, not EDSL question count")
    p.add_argument("--nodes", help="Explicit comma-separated quantities, including existing estimates")
    p.add_argument("--p", type=float, default=.8, help="Central interval coverage")
    p.add_argument("--reask", action="store_true", help="Revisit recorded unknowns in automatic selection")
    for action in ("show", "review", "template", "compile"):
        p = sub.add_parser(action, parents=[shared])
        p.add_argument("name")
        if action in {"template", "compile"}:
            p.add_argument("--output", required=True, help="New JSON file; existing files are never overwritten")
    p = sub.add_parser("ingest", parents=[shared])
    p.add_argument("name")
    p.add_argument("--from", dest="input_path", required=True)
    p.add_argument("--input-format", choices=["responses", "edsl"], default="responses")
    p.add_argument("--respondent-kind", choices=["asker", "human_panel", "llm_panel"])
    p.add_argument("--source", required=True)
    for action in ("apply", "reject"):
        p = sub.add_parser(action, parents=[shared])
        p.add_argument("name")
        p.add_argument("--proposals", required=True, help="Comma-separated proposal IDs, or all")
        p.add_argument("--reason", required=True)
    return root


def dispatch(args):
    command = args.command
    session = Session(getattr(args, "project", "."), expected_revision=getattr(args, "expect_revision", None))
    if command == "init":
        require(not hasattr(args, "project") or args.path == ".", "Choose either init PATH or --project PATH, not both.")
        return Session.create(getattr(args, "project", args.path), title=args.title, timezone=args.timezone, asof=args.asof).status()
    if command == "version":
        from . import __version__
        return {"version": __version__, "schema_version": 7, "readable_state_versions": [1, 2, 3, 4, 5, 6, 7]}
    if command == "guide":
        return {"guide": GUIDE, "research_workflow": research_workflow()}
    if command == "schema":
        return SCHEMAS[args.kind] if args.kind else SCHEMAS
    if command in {"status", "validate", "lint"}:
        return getattr(session, command)()
    if command == "next":
        return next_actions(session)
    if command == "resolve":
        return session.resolve(args.target, args.outcome, event=args.event, run_id=args.run_id, units=args.units,
                               source=args.source, observed_at=args.observed_at, definition=args.definition,
                               decisions=assignments(",".join(args.decision)), replaces=args.replaces, reason=args.reason)
    if command == "resolution":
        return session.resolution_show(args.event, resolution_id=args.resolution_id)
    if command == "score":
        return session.score(args.event, resolution_id=args.resolution_id, run_id=args.run_id, units=args.units,
                             coverages=csv(args.coverages, float))
    if command == "cohort":
        if args.action == "define":
            return session.cohort_define(args.name, read_json(args.members), units=args.units, reason=args.reason,
                                         coverages=csv(args.coverages, float))
        if args.action == "show":
            return session.cohort_show(args.name, revision=args.revision)
        return session.cohort_evaluate(args.name, revision=args.revision, include_retrospective=args.include_retrospective)
    if command == "calibration":
        if args.action == "fit":
            return session.calibration_fit(args.name, cohort=args.cohort, method=args.method, reason=args.reason,
                                           scales=csv(args.scales, float), include_retrospective=args.include_retrospective)
        if args.action == "apply":
            return session.calibration_apply(args.name, run_id=args.run_id, reason=args.reason,
                                             definition=args.definition, decisions=assignments(",".join(args.decision)))
        return getattr(session, "calibration_" + args.action)(args.name, revision=args.revision)
    if command == "survey":
        if args.action == "draft":
            return session.survey_draft(args.name, phase=args.phase, budget=args.budget, nodes=csv(args.nodes) if args.nodes else None,
                                        coverage=args.p, reask=args.reask)
        if args.action in {"show", "review"}:
            return getattr(session, "survey_" + args.action)(args.name)
        if args.action in {"template", "compile"}:
            data = session.survey_show(args.name)["response_template"] if args.action == "template" else session.survey_compile(args.name)
            with Path(args.output).open("x") as f:
                json.dump(data, f, indent=2, allow_nan=False)
                f.write("\n")
            return {"path": str(Path(args.output).resolve()), "survey": args.name, "artifact": args.action}
        if args.action == "ingest":
            return session.survey_ingest(args.name, read_json(args.input_path), source=args.source, format=args.input_format,
                                        respondent_kind=args.respondent_kind)
        return getattr(session, "survey_" + args.action)(args.name, "all" if args.proposals == "all" else csv(args.proposals), reason=args.reason)
    if command == "define":
        return session.define(args.name, units=args.units, definition=args.definition, space=args.space, status=args.status,
                              predicates=assignments(args.when, boolean) if args.when else None)
    if command == "assumption":
        return session.assumption(args.name, args.definition)
    if command == "estimate":
        if args.input:
            require(args.name is None and not any((args.source, args.reason, args.assumes, args.note, args.asof, args.ancestry, args.given, args.definition_id))
                    and args.method == "judgment" and args.kind == "epistemic" and args.p == .8 and args.shape is None,
                    "--from supplies the complete estimate; do not combine it with estimate fields.")
            payload = read_json(args.input)
            require(isinstance(payload, dict), "Estimate file must contain an object.")
            return session.estimate(**payload)
        require(args.name is not None, "Estimate requires a quantity name.")
        if args.interval:
            state, _ = session.store.read()
            require(args.name in state["quantities"], "Define the quantity first.", "not_found")
            shape = args.shape or {"linear": "normal", "log": "lognormal", "logit": "logitnormal"}[state["quantities"][args.name]["space"]]
            distribution = Distribution.from_interval(*args.interval, p=args.p, shape=shape)
        elif args.value is not None:
            distribution = Distribution.from_point(args.value)
        elif args.samples:
            distribution = Distribution.from_samples(read_json(args.samples))
        else:
            pairs = [pair.split(":") for pair in csv(args.quantiles)]
            require(all(len(pair) == 2 for pair in pairs), "Quantiles use percent:value pairs.")
            require(len({float(pair[0]) for pair in pairs}) == len(pairs), "Duplicate quantile probabilities.")
            distribution = Distribution.from_quantiles({float(p) / 100: float(v) for p, v in pairs})
        return session.estimate(args.name, distribution, source=args.source, reason=args.reason, method=args.method,
                                assumes=csv(args.assumes), kind=args.kind, note=args.note, asof=args.asof, ancestry=args.ancestry,
                                given=args.given, definition_id=args.definition_id)
    if command == "anchor":
        return session.anchor(args.name, args.value, source=args.source, asof=args.asof, ancestry=args.ancestry, note=args.note, kind=args.kind,
                              given=args.given, definition_id=args.definition_id)
    if command == "scenario":
        if args.action == "group":
            return session.scenario_group(args.name, definition=args.definition, independence_reason=args.independent_reason)
        return session.scenario(args.name, p=args.p, definition=args.definition, reason=args.reason, group=args.group)
    if command == "decision":
        if args.action == "define":
            return session.decision(args.name, options=assignments(args.options, float), definition=args.definition, units=args.units, default=args.default)
        return session.choose(args.name, option=args.option, leave_open=args.leave_open, reason=args.reason)
    if command == "definition":
        return session.definition(args.name, target=args.target, measure=args.measure, predicates=assignments(args.predicates, boolean),
                                  owner=args.owner, role=args.role, confidence=args.confidence, source=args.source)
    if command == "bridge":
        distribution = Distribution.from_interval(*args.interval, p=args.p, shape=args.shape)
        return session.bridge(args.name, args.from_definition, args.to_definition, distribution, source=args.source, reason=args.reason)
    if command == "relate":
        if args.path:
            require(args.series and not args.expression, "--path requires --series and no expression.")
            return session.relate_path(args.target, args.series, at=args.at, fork=args.fork)
        require(args.expression and not args.series and args.at is None, "Supply an expression, or --path --series NAME.")
        parts = args.expression[1:] if args.expression[0] == "=" else args.expression
        return session.relate(args.target, " ".join(parts), fork=args.fork)
    if command == "series":
        if args.action == "define":
            return session.series(args.name, base=args.base, growth=args.growth, periods=csv(args.periods), rho=args.rho,
                                  definition=args.definition, reason=args.reason, mode=args.mode)
        if args.action == "anchor":
            return session.series_anchor(args.name, args.period, args.quantity, reason=args.reason)
        if args.action == "periodic":
            return session.periodic(args.name, over=args.over, profile=read_json(args.profile),
                                    definition=args.definition, reason=args.reason, source=args.source)
        return session.series_show(args.name, run_id=args.run_id)
    if command == "allocate":
        parts, alphas = csv(args.into), csv(args.alpha, float)
        require(len(parts) == len(alphas) and len(set(parts)) == len(parts), "Provide distinct parts with one concentration each.")
        return session.allocate(args.total, dict(zip(parts, alphas)), allocation=args.allocation, reason=args.reason, source=args.source)
    if command == "allocation":
        return session.allocation_show(args.name, run_id=args.run_id)
    if command == "fork":
        return session.fork(args.target, args.strategy, source=args.source, reason=args.reason)
    if command == "strategy":
        return session.abandon(args.name, args.reason)
    if command == "note":
        return session.note(args.node, args.text)
    if command == "bound":
        return session.bound(args.target, lower=args.lower, upper=args.upper, reason=args.reason, clip=args.clip)
    if command == "merge":
        return session.merge(args.target, csv(args.forks), csv(args.weights, float), reason=args.reason)
    if command == "sample":
        definitions = "all" if args.definitions == "all" else csv(args.definitions) if args.definitions is not None else None
        run = session.sample(args.target, n=args.n, seed=args.seed, fork=args.fork, definitions=definitions,
                             decisions=assignments(",".join(args.decision)), predicate_flips=args.predicate_flips)
        return session.show(args.target, run_id=run["id"])
    if command in {"show", "compare"}:
        return session.show(args.target, run_id=args.run_id, quantiles=csv(args.quantiles, float), coverages=csv(args.coverages, float))
    if command == "audit":
        return session.audit(args.target, run_id=args.run_id)
    if command == "check":
        parts = args.against.split("@")
        require(1 <= len(parts) <= 2 and all(parts), "Use TARGET or TARGET@DEFINITION.")
        return session.check(args.claim, parts[0], definition=parts[1] if len(parts) == 2 else None, run_id=args.run_id)
    if command == "research":
        if args.action == "check":
            return session.research_check(read_json(args.input))
        if args.action == "review":
            return session.research_review(args.name, read_json(args.input))
        if args.action == "show":
            return session.research_show(args.name)
        if args.action == "status":
            return session.research_status(args.target)
        data = session.research_template(args.target, run_id=args.run_id)
        with Path(args.output).open("x") as f:
            json.dump(data, f, indent=2, allow_nan=False)
            f.write("\n")
        return {"path": str(Path(args.output).resolve()), "run_id": data["run_id"]}
    if command == "report":
        if args.action == "issue":
            return session.report_issue(args.name, review=args.review, method=args.method,
                                        coverages=csv(args.coverages, float), definition=args.definition,
                                        decisions=assignments(",".join(args.decision)) if args.decision else None)
        if args.action == "show":
            return session.research_show(args.name, issued=True)
        data = report_context(session, args.target, args.run_id)
        if args.output:
            with Path(args.output).open("x") as f:
                json.dump(data, f, indent=2, allow_nan=False)
                f.write("\n")
            return {"path": str(Path(args.output).resolve()), "run_id": data["summary"]["run_id"]}
        return data
    if command in {"save", "load"}:
        return getattr(session, command)(args.path)
    if command == "context":
        return session.context(at=args.at)
    raise StantonError("Unknown command.", "invalid_arguments")


def render_text(data):
    lines = [f"{data['target']} ({data['units']}) — run {data['run_id']}",
             f"Revision {data['revision']}; {data['n']} draws; seed {data['seed']}"]
    rows = list(data["forks"].items())
    if data["merged"]:
        rows.append(("mixture", data["merged"]))
    elif data.get("mixtures"):
        rows.extend(("mixture@" + key, value["summary"]) for key, value in data["mixtures"].items())
    for label, values in rows:
        quantiles = ", ".join(f"{q}={v:,.4g}" for q, v in values["quantiles"].items())
        lines.append(f"{label}: {quantiles}")
        for interval in values["intervals"]:
            lines.append(f"  {100 * interval['coverage']:g}% central model interval (p{interval['lower_percentile']:g}–p{interval['upper_percentile']:g}): {interval['lower']:,.4g}–{interval['upper']:,.4g}")
    if data.get("stale_run"):
        lines.append("Model or evidence changed; sample again before issuing a current conclusion.")
    for warning in data["warnings"]:
        lines.append(f"Warning [{warning['code']}]: {warning['message']}")
    return "\n".join(lines)


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        data = dispatch(args)
        if getattr(args, "format", None) == "text" and not getattr(args, "json", False):
            print(render_text(data))
        else:
            print(json.dumps({"schema_version": 1, "status": "ok", "command": args.command, "data": data,
                              "warnings": data.get("warnings", []), "errors": [], "next_actions": data.get("next_actions", [])},
                             indent=2, allow_nan=False))
        return 0
    except (StantonError, OSError, ValueError, KeyError, TypeError, ArithmeticError,
            sqlite3.Error, zlib.error, ZoneInfoNotFoundError) as exc:
        print(json.dumps({"schema_version": 1, "status": "error", "data": None,
                          "errors": [{"code": getattr(exc, "code", "invalid_input"), "message": str(exc)}],
                          "warnings": [], "next_actions": []}, allow_nan=False), file=sys.stderr)
        return 1
