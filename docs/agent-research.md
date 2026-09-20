# The agent's research contract

For empirical estimation, `stanton guide` defaults to high-effort research.
The guide leads with research requirements; the CLI reference follows them.
This contract applies to the calling agent, which supplies browsing, judgment,
and synthesis. Stanton supplies the numerical model and preserves its record.

An agent should read the guide at the start of an estimation task. `stanton next`
puts a research-review reminder before computational suggestions, even when a
saved run exists. `stanton report context TARGET` includes the same structured
contract alongside the frozen numerical evidence. Repository agents also receive
this instruction through [AGENTS.md](../AGENTS.md). For installations used by an
external agent, copy the [README's agent instructions](../README.md#instructions-for-your-agent),
which install Stanton from GitHub and run the guide as the next command.
Installing a Python package cannot change another agent's system instructions
automatically.

The contract lives in `src/stanton/research.py`. All three CLI surfaces use it.
The guidance contract keeps research quality `not_assessed`: the application
cannot establish whether the agent actually investigated the evidence. Version
0.8 separately records agent-declared `reviewed` or `provisional` status in
immutable run-bound research reviews. Schema-2 reviews distinguish performed,
unperformed, and inapplicable sensitivity work and require explicit scope and
source observation dates. Detected shared evidence and unresolved discrepancies
remain visible in issued presentations. These are declarations with mechanical
checks, not an assessment of research quality. A
successful `sample`, `validate`, or report export must never be described as
verification of research quality. The agent must perform and document the review.

## Required work

1. Define the observable, including time, scope, counting rules, and whether it
   is a historical measurement or a forecast.
2. Search primary records, independent reporting, and relevant domain evidence.
   Read underlying sources and trace shared ancestry. Multiple websites repeating
   one agency number remain one source family.
3. Investigate discrepancies, suspicious zeros, missing categories, measurement
   changes, and evidence against the first plausible answer.
4. Attempt a substantively different estimation route. For activity counts,
   consider a demand model, seasonal decomposition, or stock × utilization.
   Source its important inputs. Explain why an alternative cannot be supported
   or adds no value when that is the case; do not manufacture one for appearances.
5. Test assumptions that could change the answer. Explain uncertainty choices,
   distinguish their causes, and keep strategy disagreement visible.
6. Review the evidence before final synthesis. Continue feasible research that
   could materially alter the answer. Record why stopping is justified and
   disclose unresolved issues. Label materially incomplete work provisional.

There is no source-count quota or fixed order for choosing numerical strategies.
Strong direct measurements may deserve more weight than a demand model built on
weak inputs. Research depth means investigating that judgment, not forcing a
mixture of every method or executing more searches with no decision value.
Only an explicit user request should lower the default effort. Record time,
budget, access, or scope limits and their effect on the result. Do not ask for
permission merely to follow the default research workflow.

## Research record template

Create `RESEARCH.md` in the study directory. Fill this with evidence and results,
not just claims that steps were completed. Keep it current when resuming work.

```markdown
# Research record: <question>

## Scope and constraints
Observable, units, geography, period, repeated-counting rules, interpretation
of ambiguous terms, and any explicit user limits. Default effort: high.

## Search log and source ledger
For each meaningful search: query/source investigated, finding or failure,
and what it changed. For each retained source: title, URL, publisher,
publication date, observation period, access date, supported claim,
measurement/coverage limits, and underlying source family.

## Discrepancies and contrary evidence
Conflicting claims, possible explanations, attempted checks, resolutions,
and remaining implications for the target. Identify unavailable evidence.

## Competing estimation routes
Equations, sourced inputs versus judgment, distinct evidence and shared
dependencies, resulting estimates, and reasons for rejecting a method.

## Stress tests
Consequential assumptions varied, defensible ranges, resulting changes,
and which additional evidence could most alter the conclusion.

## Synthesis review
For each of scope, source_search, reconcile, alternative_model, stress_test,
and synthesis_gate: evidence references and met/unresolved/not-applicable
with an explanation. State whether the result is provisional, which issues
remain, why further accessible research is unlikely to change the answer
materially (or what concrete constraint prevents continuing), and the next
most useful investigation.

## Saved model
Project location, target, final run ID, model revision, and research note.
```

Before the final run, append a substantive summary of the review with
`stanton note TARGET "..." --project PROJECT`. Include findings, source
independence, unresolved issues, sensitivity results, status, and the stopping
rationale. A link to `RESEARCH.md` alone is insufficient: `stanton save` preserves
project notes but does not bundle arbitrary external files. After sensitivity tests, restore the intended model, write the final note, and
sample. Then fill `research template TARGET --output review.json`, save it with
`research review NAME --from review.json`, and use `report issue` to freeze the
computed conclusion. Follow the [runnable review walkthrough](research-review.md)
for source mappings, actual sensitivity comparisons, warning dispositions, and
issuance rules. Run IDs can be added to the external record after sampling
without changing the frozen project.

## Cape Cod Canal: what should have happened

The first study located reported annual counts, averaged recent years, applied
a judgmental multiplier, and produced an HTML report. That is a useful baseline,
but it does not fulfill this research contract. In particular:

- A zero small-vessel count and differing agency summaries needed investigation
  before being treated as comparable evidence about actual traffic.
- Additional articles needed to be traced to their underlying evidence rather
  than accepted as independent merely because they used different websites.
- Alternative evidence could include seasonal traffic, vessel tracking with
  its coverage limits, or commercial/recreational demand. These are research
  avenues, not evidence already obtained or grounds for invented input values.
- The 30% multiplier needed a substantive sensitivity/uncertainty rationale;
  generating 20,000 draws did not supply that missing support.

Under this contract the first report would have been described as a provisional
lookup-based baseline, with those gaps visible. The next step would be to perform
the missing research, not to claim that the guide itself has completed it.
