# Working with Stanton

For empirical estimation tasks in this repository, run `.venv/bin/stanton guide`
(or `stanton guide` with another installation) before research or modeling and
follow its agent research contract. This applies on resumed studies too; consult
existing research records and continue from them rather than repeating completed
work. High-effort research is the default unless the user explicitly requests a
lighter pass. Do not ask permission to do the default research.

Maintain `RESEARCH.md` in each study directory using the guide's evidence
requirements. Before presenting a completed estimate or polished report, review
the evidence for every research step, document remaining gaps and the stopping
rationale, and append a substantive summary to the target's Stanton notes before
saving the final run. Read `report context` before final narration. A successful
sample, lint, validation, or report export is not a research-quality check.

Seek independent source families, investigate contradictions, attempt an
alternative estimation route, and test consequential assumptions. Do not create
fake independence by reusing the same underlying count, fabricate a demand model
from unsupported inputs, or present an arbitrary uncertainty multiplier as
empirically validated. If material research remains incomplete, disclose the gaps
and label the estimate provisional. Explicit user constraints take precedence.

The workflow is defined once in `src/stanton/research.py` and surfaced by `guide`,
`next`, and `report context`. Keep those surfaces consistent when changing it.
See `docs/agent-research.md` for the research-record template and a worked critique.

These research requirements apply to empirical studies, not ordinary code
maintenance or explicitly synthetic examples. For code changes, run checks
appropriate to the change; do not perform unrelated estimation research.
