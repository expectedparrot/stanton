# Fitting and applying a spread adjustment

Stanton 0.6 fits an immutable calibration artifact from a cohort's declared
training split. It applies that artifact explicitly to a saved forecast and
compares raw and adjusted forecasts on the same events. All operations are
local and available through both `Session` and the CLI.

## Offline walkthrough

These are synthetic cases demonstrating the mechanics, not evidence of
calibration quality. Run in an empty directory with Stanton installed.

<!-- walkthrough:start -->
```bash
stanton init calibration --title "Synthetic spread calibration"
stanton define cost --units USD --def "Synthetic cost per independent building" --status target --project calibration
stanton estimate cost --interval 80 120 --reason "Synthetic training forecast" --project calibration
stanton sample cost -n 500 --seed 42 --project calibration > train.json
stanton estimate cost --interval 160 240 --reason "Synthetic test forecast" --project calibration
stanton sample cost -n 500 --seed 43 --project calibration > test.json

python3 - <<'PY'
import json
from pathlib import Path
members = []
for split in ("train", "test"):
    run_id = json.loads(Path(f"{split}.json").read_text())["data"]["run_id"]
    members.append({"event": split, "run_id": run_id, "group": split, "split": split})
Path("members.json").write_text(json.dumps(members))
PY
stanton cohort define buildings --members members.json --units USD --reason "Fixed synthetic cases with separate buildings in each split" --project calibration
train_run=$(python3 -c 'import json; print(json.load(open("train.json"))["data"]["run_id"])')
test_run=$(python3 -c 'import json; print(json.load(open("test.json"))["data"]["run_id"])')
observed_at=$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')
stanton resolve cost --event train --run "$train_run" --outcome 140 --units USD --source "Synthetic training outcome" --observed-at "$observed_at" --project calibration
stanton calibration fit spread_v1 --cohort buildings --method strategy:main --scales .5,1,2,4 --reason "Assess direct-cost forecast spread on fixed training cases" --project calibration
stanton calibration show spread_v1 --project calibration > fitted.json
stanton calibration apply spread_v1 --run "$test_run" --reason "Synthetic transfer to the second building" --project calibration > adjusted.json
stanton calibration evaluate spread_v1 --project calibration > unresolved.json

observed_at=$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')
stanton resolve cost --event test --run "$test_run" --outcome 260 --units USD --source "Synthetic test outcome recorded after fitting" --observed-at "$observed_at" --project calibration
stanton calibration evaluate spread_v1 --project calibration > comparison.json
stanton validate --project calibration
stanton save calibration.stanton.gz --project calibration
stanton load calibration.stanton.gz --project restored-calibration
stanton calibration evaluate spread_v1 --project restored-calibration
```
<!-- walkthrough:end -->

The [Python example](../examples/calibration.py) creates a comparable project:

```bash
python examples/calibration.py calibration-example
stanton calibration evaluate spread_v1 --project calibration-example
```

## Fitting contract

Select exactly one method: `strategy:main`, another `strategy:FORK`, or `mixture`.
Every eligible training case must contain it. This avoids silently fitting on
a different subset for each method. Cohort authors supply the meaning of the
method and the rationale for grouping cases. No domain or question-shape
classifier is inferred from strategy names.

For each empirical forecast, the transformation is
`adjusted = median + scale * (raw - median)`. The center is the inverse empirical
CDF median, with quantile method `inverted_cdf`. Scaling is in **linear quantity
space**, regardless of the quantity's original distribution or `space` tag.
There is no fitted location shift. The variance multiplier is `scale**2`.

The deterministic search minimizes equal-event mean CRPS over a supplied grid
of 1–100 distinct positive scales. The grid must include 1, the unchanged
forecast. Defaults are `.25,.5,.75,1,1.25,1.5,2,3,4`. Exact ties prefer the scale
closest to 1, then the smaller scale. The artifact records every candidate's
training score and whether the winner lies at a grid endpoint; this is an
optimum over the supplied grid, not a continuous optimizer. A grid containing
only 1 is a valid baseline. An all-point training set cannot identify a spread
adjustment and is rejected.

Training reads only training forecasts and their outcomes. Unresolved cases
and excluded evidence remain in the artifact's training roster. Retrospective
forecasts are excluded unless `--include-retrospective` is supplied; future
observation timestamps are always excluded. There must be at least one eligible
resolved event. Event and related-group counts expose how little or how much
evidence supported the fit; one case does not establish generalization.

The immutable artifact pins the project revision, cohort ID, units, selected
method, grid, engine version, scale, and training resolution IDs and hashes.
Fitting under an existing name fails. Register a new name to refit after a
correction. Archive validation recomputes the fit from its original evidence.

## Applying and evaluating

`calibration apply` returns an overlay containing the full fitted artifact,
its hash, the frozen forecast binding, original and adjusted draws, summaries,
an application reason, and an output digest. Redirect the JSON to preserve it.
Application is read-only: the saved run and working model retain their original
values. Run IDs remain model-run IDs, so ordinary `score`, `show`, and `audit`
continue to describe the original forecast. Use `calibration evaluate` for the
raw/adjusted comparison. There is no `sample --calibration` integration yet.

Select `--definition` and `--decision NAME=OPTION` when the saved run has more
than one context. The selected method must exist, and its units must be
compatible with the fitting cohort. Applying to a new case is an explicit
modeling judgment recorded in `--reason`; unit compatibility alone does not
establish that the learned adjustment transfers.

This is a scalar output transformation. It does not re-run the model, adjust
leaf estimates, enforce joint conservation, or preserve bounded support. The
overlay counts adjusted draws outside saved target bounds and reports a warning,
including when the original sampler used clipping. No new clipping is applied.
Linear expansion can introduce negative values into a positive forecast; review
the resulting support before using it. Log/logit transformations and coherent
joint calibration remain future work.

Evaluation uses the artifact's original cohort and interval contract. Training
scores retain the exact evidence used for fitting, including cases unresolved
at that time. Test scores use the active outcome records at the requested
`--revision`, or the current revision by default. Raw and adjusted aggregates
always use identical events. Missing selected methods fail explicitly; outcomes
are never invented for unresolved cases.

Reports count test observations and events with evidence recorded before fitting,
including evidence later corrected, and flag
cohort registration after observation. Those cases are post-hoc diagnostics.
The fitter excludes all test cases, but inspecting test results and selecting
another artifact can still compromise a holdout comparison. Source timestamps,
group relationships, cohort selection, and source truth remain supplied
evidence. Improved training CRPS does not guarantee improved test performance
or calibrated interval coverage.

New projects use state schema 6. State schemas 1–5 and existing numerical runs
remain readable. Calibration bookkeeping does not stale survey instruments.
