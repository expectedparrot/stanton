"""Advisory agent guidance, separate from numerical machinery."""

from .common import StantonError
from .research import research_guide, research_workflow

GUIDE = research_guide() + """Stanton is a local numerical estimation workbench.
Start with init PATH. Every later command accepts --project PATH.
Define a scalar with units, a precise definition, and space log/linear/logit.
Mark the requested output with --status target. Use count for counts, not an
undefined unit such as businesses. Define rates with --space logit.
Estimate --interval selects normal/lognormal/logitnormal from linear/log/logit
space by default; --shape overrides this explicitly. Logitnormal endpoints
must lie strictly inside (0,1); use --value for exact zero/one.
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
Validate checks history integrity, stored samples, and immutable research/issuance
records. Lint offers corrective instructions; inspect and address its findings.
Research template TARGET --run RUN_ID --output review.json creates a bound form.
Fill its source population mappings, searches, reconciliation, alternate route,
dependence, uncertainty, sensitivity comparisons, and stopping rationale using
actual evidence. Run schema research_review for its field contract. Sensitivity
comparisons reference baseline_run and variation_run with changed numerical
inputs, not merely a different seed or strategy; restore the intended model and
save the final run after stress tests. For multi-context runs, save sensitivity
runs selecting the same single definition and decision context. Schema 2 requires
scope_details (population, geography, counting_unit, inclusions, exclusions,
interpretation, and reference_period with start/end ISO dates). Each source needs
observation_window (start/end or null), temporal_status (aligned, adjusted,
unresolved, unknown), and temporal_mapping; adjusted timing also needs evidence
in temporal_evidence. Unknown or unreconciled source timing requires provisional
issuance. Record discrepancies with status resolved/unresolved; resolved entries
need evidence, not just plausible explanations. Use numeric_checks to compare
source numerator/denominator with reported_ratio (a fraction, not a percentage).
Record input_dependencies when a judgment borrows another quantity's evidence.
Sensitivity status is performed, not_performed, or not_applicable; supply reason.
Not_performed is a gap and cannot be waived by a warning disposition. Not_applicable
is only allowed for deterministic models with justification. Do not invent tests.
Research check --from review.json previews computed findings without saving a
revision. Use its finding IDs for warning_dispositions; model-only template hints
cannot include source conflicts discovered after you fill the evidence fields.
Research review NAME --from review.json saves the review and computed comparisons.
Read research show NAME for detected shared leaves, sources, and ancestry; an
absence of detected overlap does not establish independence. A source outside
the target population cannot establish a bound without a defensible mapping.
Report issue NAME --review REVIEW --method strategy:FORK/mixture freezes the
headline from the selected run. --coverages .8,.9 labels p10–p90 and p5–p95.
Issuance status comes from review.json, not a --status flag on report issue.
Read the issued presentation: state its population, geography, reference period,
inclusions/exclusions, and limitations alongside its numbers. Shared evidence
remains a finding in issued reports even when acknowledged. Unresolved evidence,
ratio conflicts, or unperformed sensitivity cannot be waived for reviewed issuance.
Rates with support outside [0,1] block issuance, including provisional issuance.
Reviewed issuance requires dispositions for all remaining warnings and no material
research gaps. Record status provisional and disclose remaining_gaps when work
is incomplete. Other warnings can be justified individually using warning_id and
reason; an acknowledgment does not fix an invalid model or verify a source.
Report show NAME retrieves the immutable conclusion; research status TARGET
shows current/stale reviews and issued reports. Edit the model or evidence, then
sample and review again to change a headline. Appending review/issuance records
alone does not invalidate the run. Archives preserve these records and bindings.
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
Version 0.8 has no network, inference, or survey execution.
Scoring does not certify sources or coverage. Historical v0.1–v0.7 projects
remain readable. Historical research records retain their original validation
rules; create a fresh schema-2 review before issuing a new conclusion.

COMMON COMMAND FORMS (replace uppercase names and supplied evidence):
stanton anchor INPUT --value 100 --source 'SOURCE' --asof 2026-01-01
stanton relate TARGET --fork FORK = 'INPUT * RATE'
stanton note TARGET 'Substantive research findings, gaps, and stopping rationale'
stanton sample TARGET --seed 0
stanton research template TARGET --output review.json
stanton schema research_review
stanton research check --from review.json
stanton research review REVIEW_NAME --from review.json
stanton report issue REPORT_NAME --review REVIEW_NAME --method mixture --coverages .8,.9
stanton report show REPORT_NAME
stanton report context TARGET
Use --project PATH on these commands. Note text is positional; anchor --asof is
required. Report context takes a target quantity; report show takes a report name.
"""


def next_actions(session):
    state, revision = session.store.read()
    root = ["stanton", "--project", str(session.store.root)]
    tasks = []
    if not state["quantities"]:
        tasks.append({"kind": "define_target", "description": "Define the scalar, units, and scope to estimate.",
                      "required_inputs": ["name", "units", "definition"], "schema": "quantity", "mutates": True, "network": False})
    targets = [node for node, quantity in state["quantities"].items() if quantity["status"] == "target"]
    if not targets:
        from .expressions import parse
        graph = state["graphs"]["main"]
        used = {node for relation in graph.values() for node in parse(relation["expression"])[1]}
        targets = sorted(set(graph) - used)
    for node, quantity in state["quantities"].items():
        if not targets and not quantity.get("process") and node not in state["estimates"] and node not in state.get("conditional_estimates", {}) and node not in state.get("decisions", {}) and not any(node in graph for graph in state["graphs"].values()):
            tasks.append({"kind": "supply_model_input", "node": node, "description": "Supply an estimate or a relation for this quantity.",
                          "required_inputs": ["distribution and provenance, or expression"], "mutates": True, "network": False})
    if not tasks:
        from .branches import layout, leaf_plan
        from .sampling import select_forks
        tasks.append({"kind": "inspect", "argv": root + ["lint"], "mutates": False, "network": False})
        for node, quantity in state["quantities"].items():
            if node in targets:
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
                if run and not session.show(node, run_id=run["id"])["stale_run"]:
                    tasks.append({"kind": "inspect_result", "argv": root + ["show", node, "--run", run["id"]],
                                  "mutates": False, "network": False})
                    reviews = {k: r for k, r in state.get("research_reviews", {}).items() if r["run_id"] == run["id"]}
                    if not reviews:
                        tasks.append({"kind": "record_research_review", "target": node, "run_id": run["id"],
                                      "description": "Create research template, fill it from actual evidence, and save research review before report issue.",
                                      "schema": "research_review", "argv": root + ["schema", "research_review"],
                                      "required_inputs": ["new template output path", "source mappings and research findings", "saved sensitivity runs or explicit omission status/reason", "review name"],
                                      "mutates": False, "network": False})
                    elif not any(r["run_id"] == run["id"] for r in state.get("issued_reports", {}).values()):
                        tasks.append({"kind": "issue_report", "target": node, "run_id": run["id"], "reviews": sorted(reviews),
                                      "description": "Address review findings, then report issue with a new name, chosen review, method, and context. Inspect report context first.",
                                      "argv": root + ["report", "context", node, "--run", run["id"]],
                                      "required_inputs": ["issued report name", "review", "method/context if ambiguous"],
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
    research_status = session.research_status()
    current_reviews = {k: r for k, r in research_status["reviews"].items() if r["current_basis"]}
    if current_reviews:
        tasks[0].update(description="Inspect recorded research reviews, unresolved findings, and issuance status. Records do not certify research quality.",
                        argv=root + ["research", "status"], completion_status="recorded")
        for review_name, record in current_reviews.items():
            tasks.append({"kind": "inspect_research_review", "target": record["target"],
                          "argv": root + ["research", "show", review_name], "mutates": False, "network": False})
    for survey, record in state.get("surveys", {}).items():
        if any(p["status"] == "pending" for p in record["proposals"].values()):
            tasks.append({"kind": "review_responses", "argv": root + ["survey", "review", survey],
                          "mutates": False, "network": False})
    return {"revision": revision, "advisory": True, "research_workflow": research_workflow(), "research_status": research_status, "next_actions": tasks}
