# Outcome evidence and forecast scoring

Stanton 0.5 records sourced outcomes against saved forecasts and evaluates fixed
cohorts. It preserves the forecast's original target, definition, decisions,
query context, and sample arrays. Scoring does not alter the numerical model or
fit a calibration adjustment.

## An offline walkthrough

All forecasts and outcomes here are synthetic fixtures. Run in an empty
directory with Stanton installed; the optional EDSL dependency is not needed.

<!-- walkthrough:start -->
```bash
stanton init evaluation --title "Synthetic cost forecast evaluation"
stanton define cost --units USD --def "Synthetic cost of an independent roof case" --status target --project evaluation
stanton estimate cost --interval 80 120 --reason "Synthetic forecast for roof A" --project evaluation
stanton sample cost -n 2000 --seed 42 --project evaluation > roof-a.json
stanton estimate cost --interval 160 240 --reason "Synthetic forecast for roof B" --project evaluation
stanton sample cost -n 2000 --seed 42 --project evaluation > roof-b.json
stanton estimate cost --interval 320 480 --reason "Synthetic forecast for roof C" --project evaluation
stanton sample cost -n 2000 --seed 42 --project evaluation > roof-c.json

python3 - <<'PY'
import json
from pathlib import Path
members = []
for letter, split in (("a", "train"), ("b", "test"), ("c", "test")):
    run_id = json.loads(Path(f"roof-{letter}.json").read_text())["data"]["run_id"]
    members.append({"event": f"roof_{letter}", "run_id": run_id,
                    "group": f"building_{letter}", "split": split})
Path("members.json").write_text(json.dumps(members, indent=2) + "\n")
PY
stanton cohort define roofs --members members.json --units USD --reason "Fixed synthetic cases with separate buildings in train and test" --project evaluation
stanton cohort evaluate roofs --project evaluation > unresolved.json

forecast_a=$(python3 -c 'import json; print(json.load(open("roof-a.json"))["data"]["run_id"])')
forecast_b=$(python3 -c 'import json; print(json.load(open("roof-b.json"))["data"]["run_id"])')
observed_at=$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')
stanton resolve cost --event roof_a --run "$forecast_a" --outcome 110 --units USD --source "Synthetic observed cost for roof A" --observed-at "$observed_at" --project evaluation
stanton resolve cost --event roof_b --run "$forecast_b" --outcome 260 --units USD --source "Synthetic observed cost for roof B" --observed-at "$observed_at" --project evaluation
stanton score roof_a --coverages .5,.8,.95 --project evaluation
stanton resolution show roof_b --project evaluation
stanton cohort evaluate roofs --project evaluation > evaluation-report.json
stanton cohort show roofs --project evaluation
stanton validate --project evaluation
stanton save evaluation.stanton.gz --project evaluation
stanton load evaluation.stanton.gz --project restored-evaluation
stanton cohort evaluate roofs --project restored-evaluation
```
<!-- walkthrough:end -->

The report has one scored training event and one scored test event. Roof C is
still unresolved, so the test report shows two registered events but a scoring
denominator of one. No zero score or invented outcome is supplied for roof C.
Roof A's outcome falls inside its central 80% interval; roof B's falls above it.
These tiny synthetic cohorts demonstrate mechanics, not calibration performance.

The Python equivalent is [outcome_scoring.py](../examples/outcome_scoring.py).
It saves individual scores, the cohort definition, and the evaluation report:

```bash
python examples/outcome_scoring.py evaluation-example
stanton cohort evaluate roofs --project evaluation-example
```

## Frozen outcomes and context

`resolve TARGET` requires an explicit `--run`, stable `--event` name, finite
`--outcome`, `--units`, nonblank `--source`, and timezone-aware `--observed-at`
timestamp. The timestamp describes when the outcome was observed or became
known, not when the CLI command ran. Compatible units are converted to the
forecast units while the supplied value and units remain in the evidence.

If a saved run contains multiple definitions or decision combinations, select
one with `--definition NAME` and repeated `--decision NAME=OPTION` arguments.
An outcome scores all saved strategies and any mixture within that context.
Other choices and predicate-flip diagnostics are excluded. Scenario uncertainty
remains part of the issued forecast; scoring does not condition draws on the
eventual realized scenario.

An event denotes one observable under one definition and decision context. Use
a different event name for a different scope. Repeated forecasts for that event
can be inspected with `score EVENT --run OTHER_ID` only when their frozen target,
definition revision, decision values, and query-time scope match. Current model
edits cannot change an old forecast or its resolution.

## Correcting evidence

An already resolved event rejects duplicate writes. To correct an observation,
repeat `resolve` with the original run and context selectors, add
`--replaces CURRENT_RESOLUTION_ID`, and supply a nonblank `--reason`. The new
record supersedes the current evidence without modifying the old record.
`resolution show EVENT` returns the full chain.

`score EVENT` uses the current resolution. `--resolution ID` reproduces a score
against older evidence. Cohort reports include a project revision; use
`cohort evaluate NAME --revision N` to reproduce the entire evaluation before a
correction or later resolution. Register a new cohort name to change membership
or interval coverages.

## Score definitions

The scorer treats the saved draws as an equally weighted empirical distribution.
Its quantiles use the inverse empirical CDF (`inverted_cdf`), whereas the general
`show` command uses interpolated percentiles. Small Monte Carlo samples can
therefore produce slightly different interval endpoints in those two views.

CRPS is the integral of the squared difference between the forecast CDF and the
observed step function. For saved draws it equals
`mean(abs(X - y)) - mean(abs(X - X')) / 2`, with independent draws from that
empirical distribution. The implementation integrates between sorted values,
avoiding a quadratic pairwise matrix. This scores the saved empirical forecast;
it does not apply a finite-ensemble bias correction.

For a central interval with coverage `p`, let `alpha = 1 - p`. Its score is
`upper - lower + 2/alpha * max(lower - outcome, outcome - upper, 0)`.
Lower scores are better. CRPS and interval scores retain the outcome's units.
See [Gneiting and Raftery (2007), sections 4.2 and 6.2](https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf).
Stanton uses CRPS as a nonnegative loss, reversing the sign of that paper's
equation (20).

Reports also include the absolute error of the empirical median and PIT bounds
`[P(X < y), P(X <= y)]`, plus their midpoint. This preserves tie mass; a midpoint
PIT is not claimed to be uniform for discrete distributions. Interval coverage
includes either endpoint. Default central coverages are 50%, 80%, and 95%; use
`--coverages` to supply distinct values strictly between zero and one.

## Cohort contract

Each member supplies `event`, `run_id`, `group`, and `split` (`train` or `test`),
plus context selectors when needed. A cohort contains at most one forecast per
event, preventing repeated forecast revisions from increasing its weight.
Related events must use the same declared group, and a group cannot cross
train/test splits. The tool cannot infer undeclared relationships.

All forecasts must have units compatible with the explicitly chosen cohort
units. Scores are converted before aggregation. Methods are identified by
strategy name, with the mixture reported separately. Their meaning across
cases remains the cohort author's responsibility.

Train and test reports stay separate. Each scored event has equal weight; the
report also exposes the number of related groups. Only methods present for
every scored event in a split receive aggregate scores. `method_availability`
and the individual cases retain the others, so comparisons never silently use
different event denominators. An empty scored set produces no aggregate scores.
Coverage fractions are descriptive; no independent-case confidence interval
or calibrated-coverage certificate is inferred.

A forecast saved at or after the supplied observation time is retrospective.
It is excluded from cohort aggregates unless `--include-retrospective` is
explicitly selected. Standalone scores still report it with a warning. A
future observation time relative to evidence recording is flagged and excluded
from cohort aggregates even when retrospective scoring is enabled.

The report discloses both outcomes already recorded when the cohort was
registered and observations whose supplied timestamps predate registration.
Post-outcome registration is useful for diagnostics but is not described as a
held-out experiment. Unresolved and excluded cases remain visible. Source and
timestamp accuracy are supplied evidence, not verified facts.

Project archives preserve outcome corrections and fixed cohort membership.
Validation checks bindings against the actual saved runs before loading an
archive. Current releases use schema 6; schema 1–5 projects and historical sampler
records remain readable. Outcome bookkeeping does not stale an otherwise
unchanged survey instrument. See [calibration](calibration.md) for explicit
training-only spread fitting and raw/adjusted evaluation. Automatic widening,
censored or disputed outcomes, and cross-project banks remain future work.
