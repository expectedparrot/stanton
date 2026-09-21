<p align="center">
  <img src="docs/assets/stanton-artwork.png" width="760" alt="Stanton artwork: a green parrot estimating the number of jelly beans in a jar, with candidate counts above it, inside expectation brackets">
</p>

# Stanton

A local numerical estimation workbench for people and agents. Supply estimates
and their provenance, combine them with unit-aware arithmetic, and preserve the
resulting uncertainty and revision history.

Version 0.8 implements the first three delivery slices in [DESIGN.md](DESIGN.md):
scalar estimation, conditional models, persistent paths, periodic profiles,
and conserved allocations. The fourth slice now includes bound surveys,
optional EDSL compilation, reviewed response import, sourced outcomes, and
scoring of fixed evaluation cohorts, and training-only fitted spread adjustments.
Run-bound research reviews and issued conclusions now preserve source mappings,
sensitivity comparisons, warning dispositions, and explicitly labeled intervals.
Issued presentations include scope and dates; shared evidence and omitted
sensitivity tests remain visible, and unresolved evidence forces provisional status.
The broader product proposal is in [spec.md](spec.md).

## Install from GitHub

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git.

```bash
uv tool install --python 3.11 "stanton @ git+https://github.com/expectedparrot/stanton.git@main"
export PATH="$(uv tool dir --bin):$PATH"
stanton guide
```

`stanton guide` is the agent's golden-path entry point. It supplies the research
workflow and command guidance; `stanton next --project PATH` supplies subsequent
project-specific actions. Numerical operations run locally; installation and the
agent's external research require network access.

## Instructions for your agent

Copy and paste this block:

```text
Use Stanton to research my estimation question and produce a sourced estimate.
Install uv if needed: https://docs.astral.sh/uv/getting-started/installation/
Git is also required. Then install Stanton from GitHub:

uv tool install --python 3.11 "stanton @ git+https://github.com/expectedparrot/stanton.git@main"
export PATH="$(uv tool dir --bin):$PATH"

Run the golden-path guidance command:

stanton guide

Read its complete output and follow its instructions through completion.
```

## A complete example

Estimate an imaginary facility's annual operating cost three years from now.
**All inputs are synthetic demonstration data.** Two approaches disagree:
extrapolating a historical cost and constructing a fresh cost estimate.
Both use the same uncertain inflation factor.

Run these commands in an empty working directory. Every command returns JSON;
`show --format text` provides a compact human view. Each invocation opens the
saved project, so there is no Python session to keep alive.

<!-- walkthrough:start -->
```bash
stanton init facility --title "Synthetic facility cost estimate"

stanton define base --units USD --def "Synthetic baseline annual cost" --status known --project facility
stanton anchor base --value 100000 --source "Synthetic example fixture" --asof 2026-09 --project facility

stanton define growth --units dimensionless --def "Annual operating growth multiplier excluding inflation" --project facility
stanton estimate growth --interval 1.03 1.10 --p .8 --reason "Synthetic judgment for the example" --project facility

stanton define inflation --units dimensionless --def "Shared cumulative price-level multiplier over the projection" --project facility
stanton estimate inflation --interval .98 1.06 --reason "Synthetic common factor" --project facility

stanton define rebuilt --units USD --def "Synthetic future cost from an alternate costing exercise, before inflation" --project facility
stanton estimate rebuilt --interval 210000 240000 --source "Synthetic alternate costing inputs" --project facility

stanton define cost --units USD --def "Nominal annual operating cost three years after the baseline" --status target --project facility
stanton relate cost = 'base * growth**3 * inflation' --project facility
stanton fork cost --as extrapolation --project facility
stanton fork cost --as costing --project facility
stanton relate cost = 'rebuilt * inflation' --fork costing --project facility

stanton fork cost --as reference_class --project facility
stanton strategy abandon reference_class --reason "No comparable facilities in this synthetic fixture" --project facility
stanton note cost "The disagreement needs investigation; neither synthetic method is established as correct." --project facility
stanton bound cost --upper 200000 --reason "Provisional planning ceiling; inspect exceedances" --project facility
stanton merge cost --from extrapolation,costing --weights .5,.5 --reason "Equal illustrative weights for the two methods" --project facility

stanton sample cost -n 20000 --seed 42 --project facility
stanton show cost --format text --project facility
stanton compare cost --by fork --project facility
stanton audit cost --project facility
stanton report context cost --output report-context.json --project facility
stanton validate --project facility

stanton save facility.stanton.gz --project facility
stanton load facility.stanton.gz --project restored-facility
stanton show cost --project restored-facility
```
<!-- walkthrough:end -->

The extrapolation median is roughly **$123,000**, while the alternate costing
median is roughly **$229,000**. The mixture retains both components, with
`divergent-strategies` and `bound-violation` warnings. The ceiling does not alter
the draws. A central interval across the mixture is not evidence that the two
methods agree.

Revising a leaf creates a new estimate record shared by future runs of both
forks. Previous runs remain intact:

```bash
stanton estimate inflation --interval 1.05 1.15 --reason "Revised synthetic price assumption" --project facility
stanton show cost --project facility
stanton sample cost --seed 42 --project facility
```

The first `show` flags that working inputs are newer than its saved result.
Use `show cost --run RUN_ID` or `audit cost --run RUN_ID` to inspect an earlier
run and its original provenance.

The equivalent Python walkthrough is [examples/quickstart.py](examples/quickstart.py).

For joint scenarios, controlled choices, and definition-dependent claim checks,
see the [conditional-model walkthrough](docs/conditional-models.md). It includes
a complete synthetic renovation example where disposal scope changes a claim's
placement in the distribution.

## Python API

```python
from stanton import Distribution, Session

session = Session.create("python-example")
session.define("revenue", units="USD", definition="Synthetic annual net revenue", space="log")
session.estimate(
    "revenue",
    Distribution.from_interval(80_000, 140_000, p=0.8, shape="lognormal"),
    reason="Illustrative judgment; not empirical evidence",
)
run = session.sample("revenue", seed=7)
print(session.show("revenue", run_id=run["id"]))
```

`Distribution.from_point`, `from_samples`, and `from_quantiles` are also
available. Quantile probabilities in Python use `[0, 1]`; the CLI uses percentages.
For complete estimate records, `estimate --from FILE` accepts the input described
by `stanton schema estimate`. Published schema descriptions are discoverable with
`stanton schema`.

## Numerical and history semantics

- Intervals are equal-tailed central intervals. Shapes are `normal`, `lognormal`,
  and `logitnormal`. Space tags describe the quantity, while the distribution
  constructor controls its support. Use `linear` for quantities that can cross
  zero; rates can use `logit` with a logit-normal estimate or endpoint point masses.
- Empirical samples are resampled with replacement. Entered quantiles use a
  piecewise-linear inverse CDF with constant endpoint tails; this deliberately
  introduces bounded tails and, for interior endpoints, endpoint masses.
- The expression language supports arithmetic and `abs`, `sqrt`, `log`, `exp`,
  `minimum`, and `maximum`. Powers require constant exponents. Relations take
  precedence over direct estimates in that fork. Cycles and unknown references
  are rejected; nonfinite draws fail the run rather than disappearing.
- Compatible unit scales convert through Pint. `USD`, `person`, `count`, and
  `dozen` are available alongside its standard units. Unknown units are rejected.
  Count is dimensionless, so definitions must distinguish the things counted.
  Unit checks do not infer nominal/real currency, geography, or fiscal/calendar scope.
- Factors are ordinary quantities referenced by multiple relations. Each leaf
  is sampled once per draw and reused across the entire comparison. Textual
  `assumption` records and `--assumes` citations preserve reasoning, but do not
  supply numerical correlation. Shared citations receive a warning.
- `sample` uses a target's merge members, otherwise its non-abandoned named
  forks, otherwise `main`. `--fork NAME` selects one explicitly. A fork copies
  relations; subsequent relation edits are local to that fork. Leaves remain global.
- Mixture weights must sum to one. Declared ancestry is audited for shared
  origins; it does not silently change weights. Divergence means medians differ
  by more than the larger central-80% half-width, in log space for positive
  log-tagged targets and linear space otherwise. It is a diagnostic, not a test
  with a calibrated significance level.
- A bound warns by default. `bound ... --clip` means joint conditioning, not
  clamping: complete draws satisfying **all** clipped bounds in the selected
  forks are retained, including their shared leaves. Runs preserve unconditioned
  summaries and violation mass. More than 20 times the requested number of
  attempted draws produces a low-acceptance error instead of a partial result.
- Runs record the exact project revision, inputs, draws, engine/dependency
  versions, seed, and generator. A revision creates new history; old runs are
  never recomputed automatically. Pass `--expect-revision N` on a mutation to
  reject a stale edit. A saved run may finish after the working project changes;
  it remains attached to the revision it sampled.

## Agent interface

`guide`, `schema`, `status`, `next`, `lint`, `validate`, and `report context`
make the tool discoverable and resumable. `next` gives advisory actions rather
than prescribing a numerical estimation strategy. When inputs are missing, it
states what the agent needs to supply.

**Agents should read and follow `stanton guide` before empirical estimation.**
High-effort research is the default: investigate independent evidence and
contradictions, attempt alternative models, test consequential assumptions, and
record a synthesis review before presenting a completed estimate. `next` and
`report context` repeat this contract; computational readiness does not establish
research completeness. See [the agent research workflow](docs/agent-research.md)
for the study record template and instructions for external agents.
Use `research template`, `research review`, and `report issue` to bind a conclusion
to saved evidence and numerical results. See the [runnable research review
walkthrough](docs/research-review.md). Issuance checks stale inputs and unresolved
model findings; it does not certify research quality.

See [Instructions for your agent](#instructions-for-your-agent) for the
copy-and-paste installation and startup instructions.

Success produces one versioned JSON envelope on stdout. Failure produces a
structured error on stderr with a nonzero exit code. JSON includes warnings and
available next actions. `--json` is accepted explicitly; `--help` is ordinary
command-line help. Existing export/report files are not overwritten.

`audit` defaults to the working model; `audit --run` and `report context` pin
their provenance to a saved run. Audit includes notes, assumption citations,
source dates and ancestry, and abandoned strategies. Missing source/reason
fields warn; mathematical impossibilities such as cycles fail. Anchor commands
require a source and date. Fuzzy source dates are retained without inventing a
trend-widening rule. `init --asof YYYY-MM-DD` enables mechanical source-cutoff lint.

## Current scope

This version supports scalar distributions, point/derived anchors,
global leaves, relation forks, shared factors, mixture merges, bounds, provenance,
basic lint, frozen results, and portable history. It also supports exhaustive
scenario groups with conditional estimates, numeric decision options, definition
masks, explicit uncertain bridge factors, and empirical claim checks with saved
predicate-flip comparisons. Paths add correlated per-period growth and explicit
anchors; periodic profiles select quantities using frozen query context;
Dirichlet allocations conserve known totals. See the
[paths and allocations walkthrough](docs/paths-and-allocations.md).
The [elicitation walkthrough](docs/elicitation.md) covers drafting questions,
importing typed responses, reviewing conflicts, and applying proposed estimates
or decisions with respondent provenance. EDSL compilation uses the optional
`fielding` extra; execution stays external. The
[outcome-scoring walkthrough](docs/outcome-scoring.md) records observed values,
scores saved forecasts, and compares methods on fixed train/test cohorts.
The [calibration walkthrough](docs/calibration.md) fits immutable spread artifacts,
applies them as explicit overlays, and compares raw/adjusted test scores.
Existing v0.1–v0.5 projects and runs remain readable.

It does not implement the whole v0.4 spec. Cross-classified allocations, reference-class
adapters, external survey delivery, sensitivity/VoI, joint calibration, consensus
anchors, logarithmic pooling, automatic reconstruction-uncertainty propagation,
and semantic definition matching remain planned in [DESIGN.md](DESIGN.md).

These outputs express the supplied model's uncertainty. Source correctness and
empirical calibration are not established by the tool.

## Development

From a clone of this repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check src tests examples
python -m build
```

Tests check analytic distribution behavior, shared-variable identities, unit
conversions, fork dependence, truncation, immutable history, imports, path
covariance, allocation conservation, periodic context, and a fresh-process
execution of every command in all five documented walkthroughs. Elicitation
tests cover stale bindings, atomic review, raw-response retention, unit checks,
and native EDSL Survey/Results round-trips with network connections blocked.
Evaluation tests check CRPS against analytic and pairwise references, correction
history, frozen outcome scope, matched event denominators, and split leakage.
Install `.[dev,fielding]` to include the optional EDSL tests.
