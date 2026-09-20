# Paths, periodic profiles, and conserved allocations

Stanton 0.3 adds processes that ordinary relations can use. Their inputs,
realizations, and query context are frozen with each run.

## An offline walkthrough

All values below are synthetic modeling fixtures. Start in an empty directory
with Stanton installed. Project commands continue to use separate processes.

<!-- walkthrough:start -->
```bash
stanton init planning --title "Synthetic planning processes" --timezone America/New_York
stanton define base --units USD --def "Synthetic annual revenue at the initial period" --project planning
stanton anchor base --value 100000 --source "Synthetic fixture" --asof 2026-01 --project planning
stanton define growth --units dimensionless --def "Annual revenue multiplier prior" --project planning
stanton estimate growth --interval 1.01 1.10 --reason "Synthetic central 80 percent interval" --project planning
stanton series define revenue --base base --growth growth --periods 2026,2027,2028,2029 --rho .7 --def "Annual revenue path" --reason "Synthetic persistence assumption" --project planning
stanton define future --units USD --def "Revenue in 2029" --status target --project planning
stanton relate future --path --series revenue --at 2029 --project planning
stanton sample future -n 2000 --seed 42 --project planning
stanton show future --format text --project planning
stanton series show revenue --project planning

stanton define budget --units USD --def "Known total budget" --project planning
stanton anchor budget --value 100000 --source "Synthetic fixture" --asof 2026-01-01 --project planning
stanton allocate budget --name spending --into staff,equipment,reserve --alpha 5,3,2 --reason "Synthetic expected shares and concentration" --project planning
stanton define allocated --units USD --def "Sum of all budget parts" --status target --project planning
stanton relate allocated = 'staff + equipment + reserve' --project planning
stanton sample allocated -n 2000 --seed 42 --project planning
stanton allocation show spending --project planning

stanton define weekday --units person --def "Synthetic weekday occupancy" --project planning
stanton estimate weekday --value 100 --reason "Synthetic fixture" --project planning
stanton define weekend --units person --def "Synthetic weekend occupancy" --project planning
stanton estimate weekend --value 20 --reason "Synthetic fixture" --project planning
cat > weekly-profile.json <<'JSON'
{"0":"weekday","1":"weekday","2":"weekday","3":"weekday","4":"weekday","5":"weekend","6":"weekend"}
JSON
stanton series periodic occupancy --over day_of_week --profile weekly-profile.json --def "Occupancy at query time" --reason "Synthetic weekly pattern" --project planning
stanton context now --at 2026-09-19T16:00:00+00:00 --project planning
stanton sample occupancy -n 100 --seed 42 --project planning
stanton show occupancy --format text --project planning
stanton validate --project planning
stanton save planning.stanton.gz --project planning
stanton load planning.stanton.gz --project restored-planning
```
<!-- walkthrough:end -->

The allocation sum is $100,000 in every draw within floating-point precision.
Occupancy is 20 because the frozen query time falls on Saturday in New York.
The revenue endpoint is uncertain; higher persistence makes successive growth
shocks move together.

Pass the `run_id` returned by `sample` to `series show NAME --run ID` or
`allocation show NAME --run ID` to inspect saved period or part distributions.
Without `--run`, these commands describe the current model. The Python example
[paths_and_allocations.py](../examples/paths_and_allocations.py) creates all three
models and writes their saved-run reports:

```bash
python examples/paths_and_allocations.py process-example
stanton show future --project process-example --format text
```

## Path contract

The ordered labels describe equally spaced steps; they do not infer elapsed
time from dates. Generated quantities are named `SERIES__PERIOD` and work in
ordinary expressions. `relate --path` selects the final period by default.

The growth quantity supplies a **marginal distribution template**, independently
of any scalar use of that quantity. For each path realization, standard normal
shocks follow `z[t] = rho*z[t-1] + sqrt(1-rho**2)*epsilon[t]`, with a stationary
standard normal first shock. The normal CDF and the growth prior's inverse CDF
convert shocks to per-step growth values. `rho` is latent-normal correlation;
it need not equal correlation of transformed growth values. It must be in
[-1, 1]. Named paths have independent residual shocks; reuse the same path to
share shocks across relations and forks. Scenario-conditioned growth uses one
shared regime for the entire realization, paired with other affected quantities.

Multiplicative paths apply positive, dimensionless multipliers, such as 1.05
for five percent growth. Compatible units such as percent are converted before
application. Choose a positive-support prior; a sampled nonpositive multiplier
fails the run. Additive paths apply increments in units compatible with the
level. Growth priors must be primitive distribution quantities, not decisions,
derived expressions, or other process outputs.

`series anchor NAME PERIOD --quantity Q --reason TEXT` replaces the level at
that period and propagates it forward. It does not condition or smooth earlier
levels or reset the latent shock process. Anchors can be uncertain quantities.
Only period values needed for the sampled target are evaluated, so an anchor
can prune earlier levels from the saved period report. Fuzzy anchor dates are
retained and flagged by lint; they do not move period labels or automatically
widen forecasts. Old runs retain their original anchors and draws.

## Periodic contract

Profiles map every bucket to a compatible quantity: hours 0–23 or weekdays
0–6 (Monday first). The run selects one bucket using the project's frozen
timezone-aware query time, converted to the project timezone. `context now --at`
changes that time for future runs. A profile can reuse quantities across buckets;
it is a lookup model, without interpolation or an inferred seasonal process.

## Allocation contract

Allocations partition an unconditional, unmasked, nonnegative point total into
2–256 named quantities. All Dirichlet concentrations must be positive and have
a recorded modeling reason. Expected shares are `alpha[i] / sum(alpha)`;
increasing every concentration proportionally narrows uncertainty around those
shares. Different allocations use independent share draws.

Every run using any part saves the complete share vector. Reusing parts in
multiple relations or forks reuses those draws. Clipped bounds retain complete
joint rows, preserving conservation, although conditioning changes the share
distribution. Bounds are applied to quantities in the sampled branches'
dependency graphs; a bound on an unused sibling is not an implicit constraint.
Definition masks may exclude a part from a reported subtotal, while
`allocation show --run` reports the full underlying partition.

Sampling records use schema 3. Validation checks frozen process plans, prior
references, finite growth draws, share conservation, and recomputed outputs.
Historical schema 1 and 2 projects remain readable. Cross-classified margins,
uncertain totals, automatic date propagation, and inferred persistence are not
implemented in this release.
