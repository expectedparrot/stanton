# Research reviews and issued conclusions

Stanton 0.8 provides an explicit path from research to an issued numerical conclusion:

```text
research → model → saved sensitivity runs → final notes/model → final run
         → research template → research review → report issue → report show
```

`sample`, `show`, and `report context` remain useful during exploration. They do
not issue a completed finding. `report issue` freezes a headline computed from
one saved run, along with the selected method, interval coverage, research
review, warning dispositions, and remaining gaps. A revised judgment belongs in
a revised model and new run, not an edited headline in a report.

Read `stanton guide` for the research requirements. The commands below are a
**synthetic demonstration**, not research evidence or an empirical estimate.

## Runnable walkthrough

<!-- walkthrough:start -->
```bash
stanton init reviewed-study --title "Synthetic research review demonstration"
stanton --project reviewed-study define population --units count --space linear --def "Synthetic unique firms"
stanton --project reviewed-study define rate --units dimensionless --space logit --def "Synthetic share with contact forms"
stanton --project reviewed-study define total --units count --space linear --status target --def "Synthetic unique firms with contact forms"
stanton --project reviewed-study anchor population --value 100 --source "Synthetic register fixture" --asof 2026-01-01
stanton --project reviewed-study estimate rate --interval .4 .6 --reason "Synthetic bounded prior"
stanton --project reviewed-study relate total = 'population * rate'
stanton --project reviewed-study sample total -n 1000 --seed 0 > baseline.json

# Vary a consequential input, save the comparison, and restore the intended model.
stanton --project reviewed-study estimate rate --value .8 --reason "Synthetic high-share sensitivity"
stanton --project reviewed-study sample total -n 1000 --seed 0 > sensitivity.json
stanton --project reviewed-study estimate rate --interval .4 .6 --reason "Restore intended synthetic prior"
stanton --project reviewed-study note total "Synthetic demonstration only. Register population and modeled share use the same scope. Raising the share to .8 gives 80 firms. No empirical coverage or independent corroboration claim. Stop because the API demonstration is complete."
stanton --project reviewed-study sample total -n 1000 --seed 0 > final-run.json
stanton --project reviewed-study research template total --output review.json
```

In a real study, fill the template from the work recorded in `RESEARCH.md`.
This example fills it with explicitly synthetic evidence:

```bash
python3 - <<'PY'
import json
from pathlib import Path

path = Path("review.json")
review = json.loads(path.read_text())
review.update(
    status="reviewed",
    scope="Synthetic unique firms in one fixture period; repeated listings excluded.",
    scope_details={
        "population": "Synthetic unique commercial firms", "geography": "United States",
        "counting_unit": "count", "inclusions": "Paid users", "exclusions": "Government, education, nonprofits, free-only accounts",
        "interpretation": "US-headquartered legal entities, not locations",
        "reference_period": {"start": "2026-01-01", "end": "2026-12-31"}
    },
    searches=[{"query": "Inspect synthetic register fixture", "outcome": "100 unique synthetic firms; no external search claimed."}],
    sources=[{
        "id": "register", "reference": "Synthetic register fixture, not a real publication",
        "claim": "100 unique synthetic firms", "population": "Synthetic unique firms",
        "target_mapping": "Same population as target; form share supplied as judgment, not observed.",
        "method": "Complete synthetic register", "limitations": "No empirical generalization",
        "publication_date": "Not applicable: synthetic", "observation_period": "Synthetic fixture period",
        "accessed_at": "Not applicable: synthetic", "applies_to": ["population"], "ancestry": ["fixture"],
        "observation_window": {"start": "2026-01-01", "end": "2026-12-31"},
        "temporal_status": "aligned", "temporal_mapping": "Same synthetic reference period"
    }],
    reconciliation="No competing measurements in this fixture. Population is a count; rate is a modeled assumption.",
    alternative_model="No second data-generating process exists in the fixture; duplicating the formula would not corroborate it.",
    dependence="Single route. Population and share are fixture inputs; no independent evidence claim.",
    uncertainty="Logitnormal share prior; an 80% model interval, without an empirical calibration claim.",
    sensitivity={"comparisons": [{
        "baseline_run": json.loads(Path("baseline.json").read_text())["data"]["run_id"],
        "variation_run": json.loads(Path("sensitivity.json").read_text())["data"]["run_id"],
        "reason": "Stress the eligible share at .8, holding the population fixed."
    }], "status": "performed", "reason": "Test the consequence of a higher form share"},
    stopping={"reason": "Synthetic API demonstration complete; no real-world finding is asserted.", "remaining_gaps": []},
)
path.write_text(json.dumps(review, indent=2) + "\n")
PY
stanton --project reviewed-study research check --from review.json
stanton --project reviewed-study research review synthetic_review --from review.json
stanton --project reviewed-study research show synthetic_review
stanton --project reviewed-study report issue synthetic_answer --review synthetic_review --method strategy:main --coverages .8,.9
stanton --project reviewed-study report show synthetic_answer
stanton --project reviewed-study research status total
stanton --project reviewed-study report context total --output reviewed-context.json
stanton --project reviewed-study validate
stanton --project reviewed-study save reviewed-study.gz
stanton --project restored-reviewed-study load reviewed-study.gz
```
<!-- walkthrough:end -->

## Evidence fields and checks

Run `stanton schema research_review` for the input schema. A template contains
its saved `run_id` and current findings, with blank narrative fields. Empty
narratives fail validation; filling fields does not certify their truth.

| Field | What to record |
| --- | --- |
| `scope` and `scope_details` | Narrative plus structured population, geography, counting unit, inclusions, exclusions, interpretation, and reference period with ISO start/end dates. |
| `searches` | Actual queries/investigations and their findings, failures, or access limits. |
| `sources` | Reference, claim, measured population, method, dates, limitations, ancestry, and model quantities under `applies_to`. |
| Source `target_mapping` | Explain how the measured population informs the requested population, including selection bias and deduplication. |
| `reconciliation` and `discrepancies` | Contradictions, attempted resolutions, remaining implications. A resolved discrepancy requires supporting `evidence`. |
| `numeric_checks` | Source numerator, denominator, denominator population, and reported ratio as a fraction; arithmetic mismatches become research gaps. |
| Source timing | `observation_window`, `temporal_status`, `temporal_mapping`, and `temporal_evidence` for adjustments. Unknown dates are explicit gaps. |
| `input_dependencies` | Quantity, `depends_on` quantities, and reason when a judgment borrows another input’s evidence, even if their graph leaves differ. |
| `alternative_model` | Different estimation routes or concrete reasons an attempted alternative is unsupported. |
| `dependence` | Shared data, assumptions, and conceptual derivations across strategies. |
| `uncertainty` | Reasons for distributions, mixture weights, and their interpretation. |
| `sensitivity.comparisons` | `baseline_run`, `variation_run`, and `reason`; results are computed from saved draws. |
| `sensitivity.status` and `reason` | `performed` with actual comparisons; `not_performed` records a gap; `not_applicable` requires a deterministic model and justification. |
| `stopping` | Specific stopping `reason` and a list of material `remaining_gaps`. |
| `warning_dispositions` | One `warning_id` and substantive `reason` for each retained warning. Preview all IDs with `research check --from review.json` after filling the evidence fields. |

Write unknown dates and unavailable methods explicitly. There is no source quota;
`reviewed` requires a nonempty source ledger and search log, while a provisional
review can honestly record that evidence is still missing. Each source must map
to at least one known quantity. The application cannot decide whether a mapping
is defensible: a count of directory listings is not automatically a lower bound
on unique firms.

Reviews compute pairwise shared leaves, source IDs, declared ancestry, and input
evidence dependencies across strategies. Detected overlap becomes a prominent
finding and remains visible in issued reports even when acknowledged. They retain the agent's dependence explanation alongside these
checks. No detected overlap does **not** establish independence: one prior may
have been derived from another without a shared variable or citation.

Sensitivity records require different numerical inputs and the same outcome
scope and strategy set. A different seed, more draws, new provenance, or separate
runs of two strategies alone does not qualify. Comparisons retain run hashes,
changed input components, medians, labeled intervals, and median differences.
Save runs for one definition and decision context at a time when testing a model
with several contexts. The final run can contain multiple contexts. The tool
checks changed inputs, not whether the selected range is consequential or
empirically justified. The review must explain that judgment.

## Issuance rules

- `reviewed` is the agent's declaration. Issuance requires no material gaps and
  a disposition for every remaining warning. Unperformed sensitivity, unresolved
  discrepancies, inconsistent ratios, and unknown/unreconciled source dates force
  provisional issuance even if their warnings have dispositions. Stanton does not certify research
  depth, source truth, representativeness, independence, or calibration.
- `provisional` preserves unresolved warnings and material gaps in the issued
  record. It does not waive invalid rate support, incompatible units, or invalid
  scenario probabilities. Correct those and sample again.
- `--space logit` makes an interval estimate use `logitnormal` by default. An
  explicit `--shape` overrides the default and lint checks support. Interval
  endpoints must be strictly inside `(0,1)`; use `--value 0` or `--value 1` for
  exact endpoints. Previously saved distributions are never silently converted.
- A relation overrides an estimate or anchor on the same node in that fork.
  Lint flags this. Use a separate evidence leaf or an explicit justified `bound`
  when appropriate. Bounds warn by default; `--clip` conditions joint draws.
- Choose `--method strategy:FORK` or `--method mixture` if multiple methods are
  present. For ambiguous outcome contexts, also select `--definition NAME` and
  `--decision NAME=OPTION`. Other strategies remain visible in the issued record.
- Reported intervals use explicit coverage and linear quantile interpolation:
  **p10–p90 is 80%; p5–p95 is 90%**. They are central model intervals, without
  a frequentist confidence or empirical calibration claim. Outcome scoring
  continues to use its documented empirical-CDF quantile convention.
- Model or note changes make an earlier run stale. `show` and `report context`
  disclose this, and review/issuance of that model as current is blocked. Adding
  reviews, issued reports, outcomes, or calibration records alone is bookkeeping
  and does not invalidate the model. Freshness is conservatively project-wide.
- Reviews and issued reports are immutable. Revisions use new names. `report show`
  preserves the historical conclusion and states whether it matches the current
  basis. `validate` and archive import reproduce bindings and computed results;
  they reject altered or removed records, including rehashed numerical tampering.

`save` bundles structured reviews and issued conclusions. It does not bundle
arbitrary files such as web pages or `RESEARCH.md`. Keep substantive findings in
notes and review fields, and preserve source artifacts separately where useful.


## Scope, discrepancies, and skipped work in schema 2

Use the issued `presentation` when writing the final answer. It includes the
status, population, geography, reference period, inclusions/exclusions, labeled
intervals, and limitations. Do not strip those fields away when reporting the
number. A historical estimate using later observations needs a supported temporal
mapping; access date alone does not establish when the population was measured.
A source window extending outside the target period cannot be declared aligned.

`research check --from review.json` is read-only. It reports newly computed
findings before the agent saves an immutable review. Include the relevant finding
IDs and substantive reasons in `warning_dispositions` for acknowledged limitations.
Dispositions do not remove shared evidence from the final report or turn research
gaps into completed work. A provisional result must retain those gaps.

For example, this numeric check surfaces an unexplained denominator conflict:

```json
{
  "id": "us_share_check", "source_id": "S5",
  "numerator": 41009, "denominator": 82255, "reported_ratio": 0.6191,
  "denominator_population": "All reported global detections",
  "explanation": "The geography percentage may use a smaller subset; not established."
}
```

The calculated ratio is about 0.4986. An unverified smaller-denominator hypothesis
does not resolve the mismatch. Reconcile the population and record the correct
inputs and evidence, or retain provisional status. Tolerance is for rounding only
(default 0.0001, maximum 0.01), not a way to waive an unexplained discrepancy.
Similarly, a global detection count containing foreign entities or nonprofits
cannot establish a lower bound for US commercial paid users without a supported
population mapping. Record unresolved mapping problems in `discrepancies`.

Schema-1 reviews and reports remain readable and validate under their historical
engine. Reading them adds current warnings without changing the records. New
issuance requires a new schema-2 review. Sources, discrepancies, and narratives
remain agent-supplied evidence; the tool cannot establish their truth.
