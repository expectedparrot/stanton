# Scenarios, decisions, and definitions

Stanton 0.2 separates uncertain regimes from choices and accounting scope.
Regimes are sampled. Decisions and definitions are reported as separate branches
with paired draws; the package does not assign them probabilities.

## An offline walkthrough

Estimate an imaginary renovation. **All numbers and probabilities below are
synthetic fixtures, not quotes or real market evidence.** Labor and materials
share a demand regime, finish is the asker's choice, and the quote's definition
excludes disposal. The alternative definition includes it.

Run the following in an empty working directory with Stanton installed.

<!-- walkthrough:start -->
```bash
stanton init renovation --title "Synthetic renovation scope comparison"
stanton define labor --units USD --def "Synthetic labor cost before finish choice" --project renovation
stanton define materials --units USD --def "Synthetic material cost before finish choice" --project renovation
stanton define disposal --units USD --def "Synthetic disposal cost" --when disposal=true --project renovation
stanton define cost --units USD --def "Synthetic renovation cost under the selected scope" --status target --project renovation

stanton scenario define quiet --group demand --p .4 --def "Quiet demand regime" --reason "Synthetic fixture" --project renovation
stanton scenario define busy --group demand --p .6 --def "Busy demand regime" --reason "Synthetic fixture" --project renovation
stanton estimate labor --value 10000 --given quiet --reason "Synthetic fixture" --project renovation
stanton estimate labor --value 20000 --given busy --reason "Synthetic fixture" --project renovation
stanton estimate materials --value 3000 --given quiet --reason "Synthetic fixture" --project renovation
stanton estimate materials --value 6000 --given busy --reason "Synthetic fixture" --project renovation
stanton estimate disposal --interval 4000 6000 --reason "Synthetic disposal uncertainty" --project renovation

stanton decision define finish --options standard=1,premium=1.5 --default standard --def "Asker-controlled finish choice" --project renovation
stanton decision choose finish --open --reason "Compare both options before choosing" --project renovation
stanton relate cost = '(labor + materials) * finish + disposal' --project renovation

stanton definition define quoted --target cost --measure "quoted renovation spend" --predicates disposal=false --owner claimant --role primary --project renovation
stanton definition define full --target cost --measure "total renovation spend" --predicates disposal=true --owner asker --project renovation
stanton sample cost -n 5000 --seed 42 --definitions all --predicate-flips --project renovation
stanton show cost --format text --project renovation
stanton check 30000 --against cost@quoted --project renovation
stanton audit cost --project renovation
stanton report context cost --output renovation-context.json --project renovation
stanton validate --project renovation
stanton save renovation.stanton.gz --project renovation
stanton load renovation.stanton.gz --project restored-renovation
stanton check 30000 --against cost@quoted --project restored-renovation
```
<!-- walkthrough:end -->

Under standard finishes, the quoted-scope distribution takes values $13,000 and
$26,000. Its $30,000 claim lies above p95. Adding disposal moves the busy-regime
cost to roughly $30,000–$32,000; the claim falls inside the central 90% interval.
The predicate-flip result reports this change using the same labor, materials,
and disposal draws. Premium finishes remain a separate result.

This is placement in a supplied model, not a finding that a real quote is fair,
accurate, or empirically calibrated. A claim inside a central interval can still
fall in a gap between scenario modes; inspect the scenario structure as well.

The Python equivalent is [conditional_models.py](../examples/conditional_models.py):

```bash
python examples/conditional_models.py conditional-example
stanton show cost --project conditional-example --format text
```

## Scenario contract

`scenario define` assigns each regime to one mutually exclusive, exhaustive
group. Draft groups may be incomplete; lint warns, and sampling an affected leaf
requires group probabilities to sum to one. Probabilities are never normalized
silently. Missing probability reasons remain visible as lint warnings.

`estimate --given SCENARIO` creates a versioned conditional estimate. A leaf can
condition on one group. Every positive-probability scenario in that group needs
a conditional estimate, or the leaf needs an explicit unconditional estimate
that serves as its fallback. The fallback is not a second independent estimate
to mix into the conditional value.

Each draw chooses one regime for the group, shared across every affected leaf,
fork, definition, and decision branch. Different leaves still have independent
residual uncertainty within that regime unless their relations share a factor.
Runs preserve the chosen regimes, conditional estimate IDs, and empirical
regime frequencies before and after any bound conditioning.

For multiple active groups, record their independence assumptions:

```bash
stanton scenario group demand --def "Demand regimes" --independent-reason "Declared modeling assumption: independent of the price regime" --project renovation
```

Every active group needs such a reason. If independence is inappropriate, encode
the joint cases in one group and supply their joint probabilities. Multiple
groups conditioning the same leaf are not supported.

## Decision contract

Decision options are named numeric values with common declared units, so they
can enter ordinary expressions. They cannot receive stochastic estimates or be
computed by a relation. Each relevant decision is one of:

- `unasked`: no disposition recorded; evaluate every option separately.
- `open`: the asker deliberately wants all options retained.
- `selected`: one option chosen with a recorded reason.

The default is recommendation metadata. It does not silently stand in for the
asker's selection. `sample --decision finish=standard` selects an option for one
run without changing the decision's recorded disposition. Multiple decisions
produce a Cartesian product; runs are limited to 64 branches and two million
branch draws. Choose options or definitions explicitly to reduce the product.

## Definition and bridge contract

Definitions record a base-measure description, owner, role, and boolean inclusion
predicates. A quantity's `--when` conditions are conjunctive. If they do not
match, its contribution is zero in its declared units and its entire subgraph
is skipped. A missing predicate is an error, not an implicit exclusion.

One definition per target can be primary. Sampling uses it by default; otherwise
select `--definitions NAME`, a comma-separated list, or `all`. Definition masks
apply across relation forks and reuse the global leaves. The measure label is
provenance, not an automatic dimensional or accounting conversion.

`--predicate-flips` saves one-at-a-time flips of every predicate in each selected
definition. `check VALUE --against TARGET@DEFINITION` reports each baseline's
claim placement and its available paired flips, keeping strategies and decisions
separate. Without saved flips, it reports `not_evaluated` and explains how to
compute them. `--run RUN_ID` pins the check to historical inputs.

Percentile is the empirical midrank: mass strictly below the claim plus half
the mass equal to it. The result also reports the full percentile interval
spanned by ties. `above_p95`, `below_p5`, and `within_p5_p95` describe central
interval placement, not truth or a formal significance test.

Anchors and estimates can carry `--definition NAME`. Reconstructed definitions
require a source and a confidence tag. Those tags remain provenance; no numeric
widening constant is invented. Model the uncertainty with alternate definitions
or an explicit bridge:

```bash
stanton bridge quoted full --name scope_factor --interval 1.1 1.5 --source "Synthetic conversion judgment" --project renovation
```

This creates an ordinary dimensionless uncertain estimate. Use it explicitly in
the appropriate relation. The bridge retains endpoint definition revisions, and
lint reports stale endpoints after a definition changes. Cross-definition source
use remains visible as `def-drift` so the declared conversion can be inspected;
the package does not prove that an arbitrary expression reconciles definitions.

## Mixtures, bounds, and history

A strategy mixture is computed separately inside each definition and decision
context. There is no blended result across contexts. Method selections are
paired across contexts so comparisons do not acquire extra mixture noise.

`--clip` retains complete joint rows satisfying every clipped bound in all
selected branches. Adding branches can therefore change the conditional
distribution when output bounds are clipped. Mutually incompatible constraints
can fail with low acceptance; inspect branches separately or revise the model.
Bounds on excluded quantities do not apply. Unconditioned summaries and regime
frequencies remain available.

Runs and archives retain all branches, conditional provenance, choices, and
definition revisions. Reading a v0.1 project does not rewrite its history;
new features append v0.2-compatible revisions. Survey elicitation, automatic
definition reconstruction, and learned calibration remain later work.
