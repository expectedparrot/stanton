# Collecting and reviewing model inputs

Stanton 0.4 adds a local survey workflow: freeze model slots, collect typed
responses, inspect proposals, and apply selected inputs in one transaction.
Compilation produces native EDSL Survey and Scenario JSON. It does not send a
survey, execute a model, or contact respondents.

## An offline walkthrough

All values below are synthetic fixtures. This walkthrough needs only the base
Stanton installation. Start in an empty directory.

<!-- walkthrough:start -->
```bash
stanton init roof --title "Synthetic roof elicitation"
stanton define area --units 'meter**2' --space linear --def "Roof surface area" --project roof
stanton define rate --units 'USD/meter**2' --def "Installed price per unit area" --project roof
stanton define cost --units USD --def "Total roof cost" --status target --project roof
stanton decision define finish --options standard=1,premium=2 --def "Chosen finish" --project roof
stanton relate cost = 'area * rate * finish' --project roof

stanton survey draft owner_input --phase triage --budget 3 --project roof
stanton survey template owner_input --output responses.json --project roof
```

The template contains the instrument and model revision identifiers. Keep those
bindings intact. Replace the example respondent identifier and fill the answers:

```bash
python3 - <<'PY'
import json
from pathlib import Path
path = Path("responses.json")
payload = json.loads(path.read_text())
payload["responses"][0] = {
    "respondent": {"id": "synthetic_owner", "kind": "asker"},
    "iteration": 0,
    "answers": {
        "leaf__area": {"status": "point", "value": 100, "units": "meter**2", "reason": "Synthetic measurement"},
        "leaf__rate": {"status": "interval", "low": 80, "high": 120, "units": "USD/meter**2", "reason": "Synthetic central 80 percent range"},
        "decision__finish": {"status": "open", "reason": "Compare both finishes before choosing"}
    }
}
path.write_text(json.dumps(payload, indent=2) + "\n")
PY
stanton survey ingest owner_input --from responses.json --source "Synthetic owner interview" --project roof
stanton survey review owner_input --project roof
stanton survey apply owner_input --proposals all --reason "Use these synthetic inputs and compare finishes" --project roof
stanton sample cost -n 2000 --seed 42 --project roof
stanton show cost --format text --project roof
stanton audit cost --project roof
stanton validate --project roof
stanton save roof.stanton.gz --project roof
stanton load roof.stanton.gz --project restored-roof
stanton survey review owner_input --project restored-roof
```
<!-- walkthrough:end -->

Standard-finish costs have a central 80% interval near $8,000–$12,000. Premium
costs are twice the corresponding standard-finish draw. The decision remains
deliberately open, with both branches visible.

The Python equivalent is [elicitation.py](../examples/elicitation.py). It writes
the response template, completed synthetic responses, proposal review, and
audit report into the example project. `--edsl` also writes the compiled native
instrument before importing the portable responses.

```bash
python examples/elicitation.py elicitation-example
stanton show cost --project elicitation-example --format text
```

## Drafting and selection

`survey draft NAME` creates a new immutable instrument. Names are never reused.
Automatic targeted drafts select missing primitive estimates in name order;
triage adds unasked decisions first. `--budget N` limits model slots, not the
number of EDSL questions. A numerical slot produces five questions and a
decision produces two. Selection is a deterministic starting point, without
sensitivity or value-of-information ranking.

Use `--nodes area,rate` to select specific quantities or revisit existing
estimates. Drafts retain the old estimate and explicit source-definition tag
where present. Derived quantities, process outputs, and conditionally estimated
quantities cannot be elicited in this release. Growth-prior quantities can be
elicited as ordinary primitive inputs.

Each instrument freezes the project identity, model revision and digest,
quantity definitions, units, query context, decision options, and interval
contract. Default interval coverage is 80%; choose `--p .9` for a central 90%
interval. The quantity's space selects the fitted family: normal for linear,
lognormal for log, and logit-normal for logit. No empirical coverage correction
or automatic widening is applied.

## Response contract

`survey template NAME --output FILE` exports the required binding metadata.
Respondents supply a stable `id` and explicit `kind`: `asker`, `human_panel`, or
`llm_panel`. Additional respondent metadata is preserved. Iteration defaults to
zero; repeated model iterations remain separate responses, not additional
independent experts.

| Status | Required answer fields | Result |
| --- | --- | --- |
| `point` | `value`, `units` | Proposed point distribution |
| `interval` | `low`, `high`, `units` | Proposed distribution with the instrument's coverage and shape |
| `choice` | `option` | Proposed decision selection |
| `open` | Nonblank `reason` | Proposed deliberate nonselection |
| `unknown` | Nonblank `reason` | Recorded unknown, with no numerical write-back |
| `unanswered` | None | Slot remains open; no proposal |

`reason` is accepted for every answer. Missing slot answers become unanswered.
Numbers must be finite JSON numbers; booleans and numeric strings are rejected.
Compatible units are converted explicitly. Unknown fields, reversed intervals,
unknown decision options, and values attached to skipped answers are rejected.
An error anywhere rolls back the entire import.

Unknown responses are retained as evidence and suppress automatic re-asking
of the same slot. This records the response disposition; it does not establish
that nobody else knows the answer. `--reask` or explicit `--nodes` revisits it.
Unanswered slots remain eligible. A changed interval contract or quantity
snapshot constitutes a changed slot.

## EDSL compilation and Results import

Install the optional dependency:

```bash
uv pip install -e '.[fielding]'
```

Immediately after drafting, before applying inputs or changing the model:

```bash
stanton survey compile owner_input --output owner-input.edsl.json --project roof
```

Load the native objects from the bundle:

```python
import json
from edsl import Agent, Scenario, Survey

bundle = json.load(open("owner-input.edsl.json"))
survey = Survey.from_dict(bundle["survey"])
scenario = Scenario.from_dict(bundle["scenario"])
agent = Agent(name="respondent_001", traits={"stanton_respondent_id": "respondent_001"})
jobs = survey.by(scenario).by(agent)
# Select a model or delivery mechanism and execute explicitly in your fielding workflow.
```

The compiled Scenario carries the binding metadata and frozen prompts. Preserve
it through execution. EDSL skip rules select point versus interval follow-ups;
unknown and unanswered skip all numerical questions. Decision choices include
`__open__`, `__unknown__`, and `__unanswered__`. A reason is required for unknown
and deliberately open answers.

Export the resulting native Results object as JSON with inline scenarios, then
import it with the respondent source kind:

```python
from pathlib import Path
Path("results.json").write_text(json.dumps(results.to_dict(), indent=2))
```

```bash
stanton survey ingest owner_input --from results.json --input-format edsl --respondent-kind llm_panel --source "Named synthetic panel experiment" --project roof
stanton survey review owner_input --project roof
```

Results import checks instrument identifiers, revision, prompt context, question
contracts, slot names, types, and skip consistency. It preserves each full raw
Result, including agent traits, model metadata, and iteration. Use an Agent name
or `stanton_respondent_id` trait; anonymous Results are rejected. This release
imports `Results.to_dict()` JSON, not `.ep` archives. Portable response import
and review do not require EDSL. Compilation is tested with EDSL 1.0.8.

## Review, conflicts, and stale instruments

Ingestion creates proposals without changing numerical inputs. `survey review`
shows normalized proposals, raw responses, and conflicts. Apply one proposal per
slot using `--proposals ID1,ID2`, or `all` when unambiguous. Reject alternatives
with `survey reject NAME --proposals IDS --reason TEXT`.

Apply all selected slots together. Any numerical-model change, including an
application, invalidates remaining proposals and further imports for that
instrument. Changes to relations, definitions, context, scenarios, or estimates
are treated conservatively as model changes, even if they affect another target.
Notes, compilation, other survey drafts, ingestion, and rejection do not stale
the model. Existing responses remain readable and rejectable after staleness.
To collect revised evidence, draft a new instrument; do not relabel old Results
with new binding identifiers.

A respondent ID and iteration can be imported once per instrument, regardless
of file names or changed answers. Conflicting respondents are never silently
averaged, pooled, or treated as calibrated uncertainty. Accepted synthetic
inputs carry an explicit uncalibrated provenance record and a lint warning.
Accepted inputs create new estimate revisions or decision dispositions, and
historical sample runs keep their original inputs.

Project exports preserve instruments, raw responses, proposals, and review
decisions. Validation checks both typed contents and their historical bindings.
Schema 1–3 projects remain readable; new project states use schema 4, while the
numerical sampler remains schema 3. Outcome scoring, calibration fitting,
automatic panel aggregation, definition-probe generation, and external survey
delivery remain future work.
