# Stanton implementation design

Review of `spec.md` v0.4 and neighboring packages, 2026-09-19.
This is the implementation contract and delivery plan. Version 0.6 implements
the first three slices; see `README.md`, `docs/conditional-models.md`, and
`docs/paths-and-allocations.md` for shipped behavior and limits.
It also implements elicitation, outcome evaluation, and scalar spread calibration
from slice four, documented in `docs/elicitation.md`, `docs/outcome-scoring.md`,
and `docs/calibration.md`.
The product specification remains in `spec.md`. Later slices below are proposals.

## Fit with the surrounding packages

Build Stanton as an independent, locally usable Python package with a public
Python API and a CLI over the same operations. The agent researches, chooses
methods, and supplies judgments; Stanton computes and preserves the record.

`vorhersage` is the closest architectural reference. Its current implementation
offers useful patterns, but its timeline engine computes declared schedules
and finite weighted scenarios, not general Monte Carlo scalar distributions.
Stanton needs its own numerical engine.

| Local implementation inspected | Pattern to adopt |
| --- | --- |
| `../vorhersage/pyproject.toml`, `src/vorhersage/cli.py` | Python 3.11+, `src/` layout, console entry point, `python -m` entry point, thin command dispatch |
| `../vorhersage/src/vorhersage/store.py` | Project-local SQLite, transactions, immutable artifacts, content hashes, append-only events, optimistic revision checks |
| `../vorhersage/src/vorhersage/schemas.py`, `common.py` | Published schemas, structured errors, strict JSON serialization, explicit timestamps |
| `../vorhersage/src/vorhersage/cli.py` | Discoverable `guide`, `schema`, `next`, and `report context`; structured next actions with argument arrays |
| `../vorhersage/tests/test_cli.py` | Execute documented walkthroughs in fresh processes and verify persisted outputs |
| `../flyvbjerg/README.md`, `src/flyvbjerg/edsl_bridge.py` | Frozen reference-class evidence and portable native EDSL artifacts |
| `../helmer/README.md`, `pyproject.toml` | Local numerical workflow, optional EDSL fielding, retained respondent provenance and disagreement |

Borrow the interfaces and persistence principles. Keep Stanton's agent guidance
advisory: importing Vorhersage's prescribed research workflow would conflict
with the spec's strategy-neutral design. No runtime dependency on Vorhersage
is needed for the initial implementation. Reference-class interchange can use
a versioned export contract with Flyvbjerg later.

## Package and command contract

Proposed layout:

```text
pyproject.toml
src/stanton/
    __init__.py          # supported public types and version
    __main__.py
    cli.py               # argument parsing and output only
    schemas.py           # persisted and public input schemas
    store.py             # transactional project state and immutable history
    distributions.py     # constructors, quantiles, distribution validation
    expressions.py       # restricted expression parser and unit propagation
    sampling.py          # shared draws, graph evaluation, run artifacts
    branches.py          # deterministic branch layout and scenario coverage
    branch_sampling.py   # paired branch engine and validation
    checks.py            # empirical claim placement and predicate flips
    session.py           # public editing and query operations
    lint.py
    reports.py           # summaries, provenance, report context
    guidance.py          # guide and advisory next actions
tests/
examples/
docs/
```

Add calibration and outcome-evaluation modules as
their delivery slices are implemented. Proposed dependencies are NumPy for
arrays and random generation, SciPy for distribution operations, and Pint for
unit algebra; use an optional `fielding` extra for EDSL. Confirm compatible
versions during implementation. Standard-library argparse and SQLite match
Vorhersage without adding an application framework.

Every stateful command accepts `--project PATH`. `stanton init PATH` creates
`.stanton/state.sqlite` and an artifacts directory. Mutations commit
automatically; `save` and `load` mean portable export and import, not an
in-memory session that disappears between CLI invocations.

Keep the spec's analyst verbs. Add the package conventions `guide`, `schema`,
`status`, `next`, `validate`, and `report context`. `next` lists concrete gaps
and useful actions without requiring a fixed sequence of estimation strategies.
The agent guide requires high-effort empirical research by default, including
source independence, anomaly investigation, alternative methods, stress tests,
and an evidence-backed synthesis review. `guide`, `next`, and `report context`
share the contract in `research.py`. Repository agent instructions require its
use; external agents must be instructed to read the guide. Research status stays
`not_assessed` in tool outputs: numerical validity does not certify that research
was performed. Study records and frozen target notes preserve the agent's review.
Expose complex records through `--from FILE` as well as convenient flags.
Add explicit commands for assumptions, decisions, and definitions, which appear
in the ontology but lack a complete CLI contract in the spec.

Use a versioned JSON envelope with `status`, `command`, `data`, `warnings`,
`errors`, and `next_actions`. Match Vorhersage's machine mode: success on stdout,
structured failure on stderr with a nonzero exit code. Offer explicit text
rendering for humans. Actions include argument arrays, project identity,
required inputs, and mutation/network metadata; missing inputs must not be
presented as executable placeholder commands.

## Persistence and reproducibility

Separate stable quantity IDs, immutable estimate revisions, mutable working
heads, relation-graph revisions, and immutable sample runs. An estimate revision
records its predecessor, provenance, uncertainty kind, method, assumptions,
source availability dates, and recording timestamp. Notes and abandonments
append history rather than rewriting old estimates.

Leaves belong to the session. Forks select relation graphs, not private copies
of leaves. Editing a global leaf affects subsequent runs of every applicable
fork. Historical sample runs pin the exact leaf revisions and graph revisions
they used and remain unchanged. A direct estimate used as one strategy can be
a separate global quantity referenced by that strategy's target relation.

A sample run freezes the model snapshot, target, fork IDs, definition and
decision branches, query context, seed, generator and engine versions, sample
count, bounds policy, and calibration artifact ID. Save sample arrays and their
hashes alongside the run. A seed alone is insufficient to reconstruct a result
after inputs or engine behavior change.

Sample each stochastic leaf once per draw and reuse it throughout the DAG and
all compared forks. Use stable random streams keyed by stochastic node identity
so adding an unrelated node does not change existing draws. `show` identifies
the run and reports whether newer working revisions exist.

Use transactional writes with expected-revision checks to reject stale edits.
Exports include versioned records and referenced artifacts; imports validate
integrity and references before committing.

## Numerical choices to settle before implementation

### Shared assumptions and correlation

A shared citation does not specify a joint distribution, correlation sign, or
effect size. Separate an **assumption citation** from a **sampled factor**.
The proposed first implementation samples explicit factor quantities once and
references them in relations. For example, two revenue estimates can depend on
the same sampled inflation factor through different formulas. Shared scenarios
also induce dependence by selecting one joint regime for the relevant leaves.

`--correlate auto` reuses these explicit dependencies. Shared textual assumptions
without a numerical relationship produce an unresolved-dependence warning;
they must not silently imply perfect positive correlation. Factor loadings or a
copula interface can come later if dry-runs justify them. This is a proposed
clarification to the current spec, not a behavior it already defines.

### Distribution semantics and spaces

Define `from_interval(low, high, p, shape)` as an equal-tailed central interval.
Keep distribution family distinct from space: lognormal is a positive-valued
family; log is a transform used for appropriate comparisons or error models.
Specify a logit-normal constructor for rates. Exact zero and one require point
masses or another explicitly supported family.

Reject nonfinite values, unordered intervals, invalid probabilities, and
impossible constructor supports. Choose explicit defaults for empirical
quantile interpolation and tail behavior; do not infer tails from three points
without recording a policy. Mixtures must handle point masses as well as
continuous components.

Scenarios need a named mutually exclusive, exhaustive group with probabilities
summing to one, or an explicit remainder regime. Missing conditional values
need a declared fallback or an incomplete-model error. Different scenario
groups must declare whether independence is assumed or provide a joint model.

### Expressions and units

Parse a restricted expression AST. Support named quantities, numeric constants,
arithmetic, and a documented function whitelist; never evaluate arbitrary
Python. Detect cycles, unknown references, domain errors, and nonfinite output.
Do not silently discard invalid draws.

Carry units through the graph and convert compatible scales explicitly. Retain
semantic tags that dimensional algebra cannot resolve: nominal versus real
currency, currency year, geography, manufactured versus sold, and fiscal versus
calendar periods. Unknown custom units remain explicit unresolved metadata.

Unit mismatch can remain a lint warning as specified, but no resulting output
should be labeled unit-validated. Structural impossibilities such as a cycle
or invalid probability are hard errors. This separates overridable analytical
judgment from records the engine cannot calculate.

### Bounds and merges

Report bound violation mass against the original run. The spec's `--clip` means
conditioning/truncation, not replacing out-of-range values with boundary values.
Retain and renormalize complete joint rows so dependence survives; replenish
draws under a recorded policy when needed, and fail clearly when acceptance is
zero or too low. Preserve the unconditioned result for comparison.

Start with mixtures using explicit nonnegative weights summing to one and a
recorded reason. Preserve component results and declared/effective weights.
Define the divergence statistic, interval width, comparison space, and
zero-width behavior before implementing the warning.

Record shared ancestry and warn immediately. Automatic down-weighting needs a
specified policy: for example, explicit evidence-family weight budgets with
declared within-family shares. Free-text ancestry alone must not silently alter
weights. Defer logarithmic pooling until density and discrete-mass semantics
are specified.

### Sensitivity, calibration, and elicitation

Start with clearly labeled sensitivity diagnostics. A variance-times-
resolvability ranking is a research-priority heuristic; formal value of
information additionally needs an observation model, decision, and utility.
Correlated inputs also need an explicit attribution convention before a
variance decomposition can be interpreted as additive contributions.

Record resolutions against frozen issued runs and original target definitions.
Begin evaluation with interval coverage, interval scores, and an empirical
distribution score such as CRPS, retaining cohort sizes and units. Keep training
and evaluation questions separate and group related questions. Apply only
versioned, explicitly selected calibration artifacts; no universal widening
constant or consensus bias adjustment should be invented at ingestion.
Calibration measures outcomes and does not verify source truthfulness.

EDSL question names bind to stable slot IDs, but ingest must also pin the model
revision and instrument version, preserve raw responses, validate units and
types, reject stale or duplicate writes, and create new estimate revisions.
Unknown, unanswered, and deliberately open are separate states. Synthetic-panel
response variation must be labeled as such rather than automatically treated
as calibrated uncertainty about the target.

## Delivery slices and acceptance criteria

### 1. A complete local estimation workflow

Implement packaging, project storage, distribution constructors, quantities,
immutable estimates and anchors, notes, explicit shared factors, DAG relations,
units, fork/abandonment records, sampling, bounds, mixtures, comparison, audit,
basic lint, and portable save/load. Include the discovery and report-context
commands. Run the same operations through the Python API and CLI.

Use a labeled synthetic worked example with a known anchor, uncertain growth,
an alternate decomposition, a shared factor, two disagreeing forks, a bound,
and a revision. Every README command must run offline in a new process. This
slice is complete only when an agent can build, save, reopen, inspect, compare,
revise, and export a sourced estimate with reproducible samples.

### 2. Conditional models and interpretation (implemented in 0.2)

Add exhaustive scenario groups, conditional estimates, per-decision results,
definition predicates, definition-tagged anchors, explicit bridge estimates,
claim percentiles, and predicate-flip comparisons. Keep branches paired through
the same leaf draws. Use the creator-economy example as a modeling fixture with
clearly labeled supplied inputs, not as a verified factual conclusion.

Implemented contract: one scenario group per conditioned leaf; multiple active
groups require explicit independence reasons. Missing conditional values require
an explicit unconditional fallback. Decisions are numeric options; defaults are
recommendations, while unasked/open decisions report every option. Definitions
are target-scoped, conjunctive boolean masks. Sampling can save one-at-a-time
predicate flips; claim checks use those saved draws and report ties explicitly.
Mixtures stay within each decision/definition context. Definition tags, confidence,
and bridge endpoint revisions are retained; confidence alone never invents numeric
uncertainty. Caller-supplied bridge distributions express numerical conversion
uncertainty. Automatic reconstruction and purpose elicitation remain future work.

### 3. Paths and conservation (implemented in 0.3)

Persistent paths use equal-step labels and a Gaussian AR(1) copula for marginal
growth priors, with additive and multiplicative modes. Explicit anchors reset
levels forward; shared regimes persist across periods. Complete periodic
profiles evaluate the frozen query time in the project timezone. Dirichlet
allocations partition known point totals and retain complete share vectors
through joint-row truncation. Conservation is tested within floating-point
precision. Reports inspect saved draws, and schema 1 and 2 archives remain readable.

Fuzzy dates remain provenance with a lint finding; numeric time uncertainty
requires a future explicit time model. Cross-classified allocations remain
unimplemented until the intended distribution over feasible tables and its
sampler are specified; matching margins alone is insufficient.

### 4. Elicitation and learning (0.4–0.6)

Implemented: immutable instruments bind primitive numeric and decision slots
to the model revision, units, context, definitions, and interval contract.
Triage prioritizes unasked decisions; targeted drafts select missing estimates
deterministically, with explicit selection for revisiting existing inputs.
Native EDSL compilation supplies status questions, skip rules, and a frozen
Scenario. Portable responses and Results JSON import preserve respondent,
iteration, raw-answer, and model provenance. Imports create typed proposals;
review applies one proposal per slot in an atomic batch. Model changes reject
stale imports and applications. Unknowns, unanswered responses, deliberately
open choices, conflicts, and duplicate imports remain distinct.

Outcome evidence now pins an immutable saved run and one definition/decision
context. Corrections append linked records. Empirical-CDF CRPS, interval scores,
coverage, median error, and tie-aware PIT diagnostics use saved samples. Fixed
cohorts pin event membership, units, interval contracts, related-event groups,
and train/test splits. Duplicate events and groups spanning splits are rejected;
retrospective forecasts are excluded by default. Unresolved cases and
post-outcome registration remain visible. Comparisons aggregate only methods
present for every scored event in a split. Project-revision selection reproduces
evaluations before evidence corrections, and archive validation verifies run bindings.

Calibration artifacts now fit a linear spread multiplier around the empirical
median for an explicitly selected strategy or mixture. Deterministic grid search
minimizes training mean CRPS; the grid includes the unchanged forecast. Artifacts
pin the cohort, revision, candidate scores, and exact training evidence. Read-only
application returns original and adjusted draws with hashes and support diagnostics.
Evaluation keeps training evidence pinned and compares raw/adjusted forecasts on
the same test events, with pre-fit outcome timing disclosed. Archive validation
reproduces fits. The adjustment acts on scalar outputs and does not enforce joint
constraints or provide a calibration guarantee.

External execution and delivery remain distinct from compilation. There is no
automatic respondent pooling or interval widening. Definition-probe generation,
conditional-slot elicitation, sensitivity-based selection, cross-project
evaluation banks, log/logit spread fitting, joint calibration, and sample-command
integration remain future work.
Add Flyvbjerg interchange when a concrete reference-class example needs it.

## Verification priorities

- Analytic checks for normal sums and shared-variable identities: `x - x = 0`
  in every draw, including across forks.
- Repeated-process CLI walkthroughs, immutable old runs after leaf revisions,
  stale-write rejection, and export/import equivalence.
- Distribution interval recovery within Monte Carlo tolerance, signed and
  bounded-support cases, and explicit empirical-tail behavior.
- Unit conversions, cycle detection, invalid expression rejection, missing
  scenario coverage, and nonfinite arithmetic diagnostics.
- Mixture component weights, retained disagreement, complete provenance,
  original bound violation mass, and truncation preserving joint rows.
- Conservation, persistent series shocks, frozen periodic context, definition
  masks, and decisions never sampled.
- Stale survey ingestion/application, duplicate responses, raw provenance,
  atomic review, and native EDSL question/Scenario bindings.
- Analytic and pairwise score references, immutable corrections, outcome scope,
  unresolved counts, matched event denominators, and related-group split checks.
- Training-only fit invariance to test outcomes, pinned correction history,
  raw/adjusted matched denominators, explicit support diagnostics, and archive
  replay of fitted artifacts.

## Small specification edits to make alongside implementation

Replace the two remaining `q` command references with `stanton`. Define the
meaning of `--clip`, assumption citations versus numerical dependence, immutable
runs versus global working leaves, and source dates versus recording dates.
Specify how forks are selected for `relate`, `sample`, and `show`. Document
advisory provenance warnings versus invalid-state errors, including whether
missing reasons are accepted as draft records. Mark the survey/definition
drafts, unsupported calibration options, and unresolved sampling schemes by
delivery status so proposed commands are not mistaken for shipped behavior.
