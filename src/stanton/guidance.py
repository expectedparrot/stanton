"""Advisory agent guidance, separate from numerical machinery."""

from .common import StantonError
from .research import research_guide, research_workflow

GUIDE = research_guide() + """Stanton is a local numerical estimation workbench.
Start with init PATH. Every later command accepts --project PATH.
Define a scalar with units, a precise definition, and space log/linear/logit.
Use anchor for a dated sourced point; estimate for an uncertain distribution.
An interval is an equal-tailed central interval with coverage --p (default .8).
Use --reason to label judgment; source verification remains your responsibility.
Revise a leaf by estimating it again. Old runs keep the original estimate.
Use relate TARGET = 'EXPRESSION' to compose named quantities; a relation takes
precedence over a direct estimate for that node in its fork. To compare a direct
estimate with a decomposition, put the direct estimate in a separate leaf.
Arithmetic supports + - * / ** and abs, sqrt, log, exp, minimum, maximum.
Powers use constant exponents. Unit-compatible scales convert automatically.
For dependence, define and estimate a shared factor and use it in relations.
Assumption citations are provenance, not numerical correlation coefficients.
Fork TARGET --as NAME copies relations; leaves stay global. Use --fork NAME on
relate to edit that graph. Abandon unused strategies with a recorded reason.
Merge TARGET --from a,b --weights .5,.5 --reason TEXT stores mixture weights.
Sample TARGET --seed 0 freezes inputs and draws. Without --fork it uses the
merge members, or all non-abandoned forks registered for TARGET, or main.
Show and compare retain every fork. Audit --run ID inspects historical inputs.
Bounds warn by default. --clip on bound conditions complete joint draws on ALL
clipped bounds in the selected forks and branches, with at most 20*n attempted draws.
Scenario define NAME --group GROUP --p P --def TEXT --reason TEXT records a regime.
Estimate --given NAME sets a conditional marginal. One group draw is shared by
all dependent leaves. Group probabilities must sum to one. Every positive regime
needs a conditional estimate or an explicit unconditional fallback. Multiple
groups require recorded independence reasons; otherwise define joint regimes.
Decision define NAME --options small=1,large=2 --def TEXT declares a controlled
quantity. Choices are never sampled. Unasked and deliberately open decisions
report all options separately. A default is a recommendation, not a selection.
Decision choose NAME --option small --reason TEXT records a selection; --open
records deliberate nonselection. Sample --decision NAME=OPTION overrides one run.
Definition define NAME --target TARGET --measure TEXT --predicates key=true
registers a scope. Define quantity --when key=true gates it in every relation.
Set --role primary for the default definition, or sample --definitions a,b/all.
Sample --predicate-flips also saves paired one-predicate-at-a-time comparisons.
Anchor/estimate --definition NAME tags a source's scope. Bridge FROM TO --name
FACTOR --interval LO HI --source TEXT creates an ordinary uncertain multiplier;
apply it explicitly in a relation. Confidence tags do not invent numeric width.
Check VALUE --against TARGET@DEFINITION uses a saved run, including its recorded
predicate flips. It reports strict-below and tie mass; percentile is midrank.
Decision and definition branches have no probability weights and are never merged.
Sample again after editing; show reports newer working revisions explicitly.
Save FILE exports history; load FILE requires a new destination project.
Validate checks history integrity and stored samples. Lint is advisory.
Next suggests model operations and reminds the agent to review the research
contract. Computational readiness does not establish research completeness.
Report context exports factual material for the calling agent's explanation.
Series define NAME --base Q --growth Q --periods a,b,c --rho R --def TEXT
--reason TEXT creates a path. Growth is a per-step marginal prior with AR(1)
latent normal shocks, not a fixed scalar shared over all steps. Multiplicative
paths need positive dimensionless multipliers; additive paths need level units.
Series anchor NAME PERIOD --quantity Q --reason TEXT resets the level forward.
Relate TARGET --path --series NAME --at PERIOD uses a generated path output.
Series periodic NAME --over hour_of_day/day_of_week --profile FILE selects a
quantity using frozen context time and timezone. Profiles must cover all buckets.
Allocate TOTAL --into a,b,c --alpha 2,3,5 --reason TEXT partitions a known point
total with Dirichlet shares. Full partitions conserve totals within floating-point
precision, including after bound conditioning. Concentrations are modeling inputs.
Series show NAME --run ID and allocation show NAME --run ID inspect saved draws.
Fuzzy dates remain provenance; no time uncertainty is silently propagated.
Survey draft NAME --phase triage/targeted --budget N freezes missing estimate
slots and, in triage, unasked decisions. --nodes explicitly revisits quantities.
Selection is deterministic, not a sensitivity or value-of-information ranking.
Survey template NAME --output FILE exports a bound response form. Survey compile
NAME --output FILE creates native EDSL Survey and Scenario JSON; install the
fielding extra. Compilation never executes models or contacts respondents.
Survey ingest NAME --from FILE --source TEXT preserves answers as proposals.
For Results.to_dict JSON use --input-format edsl --respondent-kind KIND.
Survey review NAME exposes responses and conflicts. Survey apply NAME
--proposals ID1,ID2/all --reason TEXT applies one proposal per slot atomically.
Apply all selected slots together: changing the model invalidates remaining
proposals. Survey reject records a reason without editing numerical inputs.
Unknown needs a reason and suppresses automatic re-asking until --reask;
unanswered leaves the slot open. Respondents and model iterations remain separate.
There is no automatic pooling, uncertainty widening, or calibration at import.
Resolve TARGET --event NAME --run ID --outcome X --units UNIT --source TEXT
--observed-at TIMESTAMP records outcome evidence. Choose --definition and
--decision NAME=OPTION if the run contains several contexts; hypothetical
choices and predicate flips are never treated as additional realized events.
Correct an outcome with --replaces CURRENT_RESOLUTION_ID --reason TEXT;
original evidence and forecasts remain available. Resolution show NAME inspects
the chain. Score NAME reports CRPS, PIT bounds, and central interval scores.
--resolution ID scores historical evidence; --run ID selects another compatible
saved forecast. Scores use the empirical CDF, with lower scores better.
Cohort define NAME --members FILE --units UNIT --reason TEXT freezes event/run
membership, coverages, related-event groups, and train/test splits. Each event
appears once; related groups cannot cross splits. Cohort evaluate NAME reports
the splits separately, including unresolved counts and matched-method scores.
Forecasts saved at or after the outcome observation are retrospective and
excluded by default; --include-retrospective includes them explicitly. Future
observation timestamps remain excluded. --revision N reproduces an earlier
cohort evaluation after evidence corrections. Registration after observed or
recorded outcomes is disclosed, not described as a held-out experiment.
Calibration fit NAME --cohort NAME --method strategy:FORK/mixture --reason TEXT
fits a positive linear spread scale around each forecast's empirical median.
Only eligible training events influence the CRPS grid search. Scale 1 is always
an option. Artifacts pin the cohort, grid, revision, and exact training evidence.
Calibration apply NAME --run ID --reason TEXT returns raw and adjusted draws
with a digest; redirect JSON to save the overlay. It does not change the run or
enforce joint constraints. Target bound violations are reported without clipping.
Calibration evaluate NAME compares raw/adjusted scores on identical events,
with separate training and test results. Training evidence stays pinned;
test evidence uses the chosen --revision. Observations before fitting are
flagged. Repeated selection on test results compromises a holdout interpretation.
Version 0.6 has no network, inference, or survey execution.
Scoring does not certify sources or coverage. Historical v0.1–v0.5 projects
remain readable.
"""


def next_actions(session):
    state, revision = session.store.read()
    root = ["stanton", "--project", str(session.store.root)]
    tasks = []
    if not state["quantities"]:
        tasks.append({"kind": "define_target", "description": "Define the scalar, units, and scope to estimate.",
                      "required_inputs": ["name", "units", "definition"], "schema": "quantity", "mutates": True, "network": False})
    targets = [node for node, quantity in state["quantities"].items() if quantity["status"] == "target"]
    for node, quantity in state["quantities"].items():
        if not targets and not quantity.get("process") and node not in state["estimates"] and node not in state.get("conditional_estimates", {}) and node not in state.get("decisions", {}) and not any(node in graph for graph in state["graphs"].values()):
            tasks.append({"kind": "supply_model_input", "node": node, "description": "Supply an estimate or a relation for this quantity.",
                          "required_inputs": ["distribution and provenance, or expression"], "mutates": True, "network": False})
    if not tasks:
        from .branches import layout, leaf_plan
        from .sampling import select_forks
        tasks.append({"kind": "inspect", "argv": root + ["lint"], "mutates": False, "network": False})
        for node, quantity in state["quantities"].items():
            if quantity["status"] == "target":
                try:
                    branches = layout(state, node, select_forks(state, node))
                    leaf_plan(state, branches)
                except StantonError as exc:
                    tasks.append({"kind": "complete_model", "target": node, "code": exc.code,
                                  "description": str(exc), "required_inputs": ["Resolve the reported model gap"],
                                  "mutates": True, "network": False})
                    continue
                try:
                    run = session.store.run(target=node)
                except StantonError as exc:
                    if exc.code != "not_found":
                        raise
                    run = None
                if run and run["revision"] == revision:
                    tasks.append({"kind": "inspect_result", "argv": root + ["show", node, "--run", run["id"]],
                                  "mutates": False, "network": False})
                else:
                    tasks.append({"kind": "sample", "argv": root + ["sample", node], "mutates": True, "network": False})
    # Add agent work after determining executable model actions: a reminder must
    # not suppress missing-input diagnostics or the existing sampling workflow.
    tasks.insert(0, {"kind": "research_review", "targets": targets,
                     "description": "Read stanton guide and complete its high-effort research contract before final synthesis. Review the study's RESEARCH.md and evidence; a runnable or sampled model does not establish research completeness.",
                     "argv": root + ["guide"], "mutates": False, "network": False,
                     "execution": "Reading the guide is local; the research itself is agent work and may require external tools.",
                     "completion_status": "not_assessed"})
    for survey, record in state.get("surveys", {}).items():
        if any(p["status"] == "pending" for p in record["proposals"].values()):
            tasks.append({"kind": "review_responses", "argv": root + ["survey", "review", survey],
                          "mutates": False, "network": False})
    return {"revision": revision, "advisory": True, "research_workflow": research_workflow(), "next_actions": tasks}
