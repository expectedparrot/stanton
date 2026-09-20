"""Shared agent research contract, distinct from numerical validity checks."""

from copy import deepcopy

RESEARCH_WORKFLOW = {
    "version": "stanton.research.v3",
    "default_effort": "high",
    "applies_to": "Empirical estimation studies; not software maintenance or explicitly synthetic demonstrations.",
    "override": "Use a lighter pass only when the user explicitly requests it; record the constraint and omitted work. Do not ask permission to perform the default research.",
    "completion_status": "not_assessed",
    "verification": "Agent-reviewed evidence is required. Stanton does not browse, verify sources, assess research completeness, or certify fulfillment of this contract. Structured research reviews and issuance enforce run bindings, required records, warning dispositions, and reproducible numerical summaries. Sampling, lint, validation, and a saved report are not evidence of research completion.",
    "record": "Maintain RESEARCH.md in the study directory. Append a substantive summary of its findings, limitations, review status, and stopping rationale to the target using note before the final saved run. A bare link or checked checklist is insufficient. Then create a run-bound research template, fill it with actual evidence, save a research review, and use report issue before presenting a completed conclusion. External files are not bundled by project save; target notes, structured reviews, and issued reports are.",
    "steps": [
        {
            "id": "scope",
            "title": "Define the observable",
            "instruction": "State geography, period, units, populations, inclusions/exclusions, and repeat-counting rules. Distinguish measured historical totals, unique entities, typical-year estimates, and forecasts. State reasonable assumptions and proceed; ask only when ambiguity materially changes the target. Carry the selected population, inclusions/exclusions, geography, and reference period into the final headline and presentation. Do not silently replace a current question with an older reference year or mix later observations into a historical estimate without a documented adjustment.",
            "evidence": "Target definition and the interpretation selected for ambiguous terms.",
        },
        {
            "id": "source_search",
            "title": "Search broadly and trace evidence",
            "instruction": "Search primary records, independent reporting/articles, and relevant operator, industry, or academic evidence. Seek different data-generating processes, not just different websites. Open relevant underlying sources; inspect methods, dates, scope, and tables. Do not stop at the first authoritative number. Record observation windows separately from publication/access dates. Distinguish directly observed source claims from your hypotheses about detection errors or coverage. Record unsuccessful searches and inaccessible evidence honestly; never invent sources to satisfy a quota.",
            "evidence": "Search log and source ledger: URL/title, publisher, publication and observation dates, accessed date, supported claim, method/coverage limits, and original source or shared ancestry.",
        },
        {
            "id": "reconcile",
            "title": "Investigate contradictions and omissions",
            "instruction": "Investigate anomalous zeros, abrupt changes, reporting coverage, missing categories, stale summaries, duplicate counts, and mismatched definitions. Seek contrary evidence. Distinguish missing observations from measured zero. Recompute cited shares from their numerators and denominators; identify the denominator population rather than assuming a geography percentage covers the reported global total. Record these in numeric_checks. A plausible explanation is not a resolved contradiction: record discrepancies as unresolved until supporting evidence exists. A global detected count containing foreign entities or nonprofits is not a lower bound for US paying commercial companies. Explain disagreements or retain them as unresolved; do not average incompatible counts or silently invent a correction.",
            "evidence": "Discrepancy ledger with attempted checks, competing explanations, and their implications for the estimate.",
        },
        {
            "id": "alternative_model",
            "title": "Build and challenge an alternative estimate",
            "instruction": "Develop a substantively different estimation route when feasible: demand/stock times utilization, component totals, seasonal activity, capacity constraints, or a comparable reference class. Source material inputs and label the rest as judgment. Check overlap and double-counting. A restatement of the same reported total is not independent corroboration. In particular, correcting a crawl count using the official total creates dependence on that total. Record borrowed inputs in input_dependencies and source applies_to mappings even when the numerical graphs share no leaves. Never claim independent corroboration merely because two formulas or vendor websites differ. If a complete direct measurement makes modeling redundant, or evidence cannot support another route, document the attempted cross-check and concrete reason; do not fabricate a model or a second method merely to comply.",
            "evidence": "Equations, input evidence, shared dependencies, separate strategy results, and rejection reasons for unsupported methods.",
        },
        {
            "id": "stress_test",
            "title": "Test consequential assumptions",
            "instruction": "Identify the inputs, selection choices, coverage gaps, and dependence assumptions that could change the conclusion. Vary them over evidence-supported or explicitly judgmental ranges and save the resulting comparisons. Distinguish annual variation, measurement error, forecast uncertainty, and model disagreement. Explain interval endpoints and mixture weights; an arbitrary percentage around one number is not a researched uncertainty model. Monte Carlo sampling does not create empirical support. Set sensitivity.status to performed only with saved changed-input comparisons. Comparing strategies, observing overlapping intervals, or drawing more samples does not substitute for sensitivity. Use not_performed for omitted work and disclose it as a research gap. Not_applicable is restricted to deterministic models with a concrete justification; it cannot excuse stress tests in an uncertain model.",
            "evidence": "Sensitivity/scenario results, rationale for uncertainty choices, and what additional evidence would most change the answer.",
        },
        {
            "id": "synthesis_gate",
            "title": "Review research before presenting a completed estimate",
            "instruction": "Before final synthesis or a polished HTML report, review each step against actual evidence. Continue tractable work that could materially change the result. Stop when additional accessible research is unlikely to alter the conclusion materially, or explicit user constraints/access limits prevent further progress; record why. Disclose remaining gaps and label the result provisional when material research remains incomplete. Do not call a lookup-plus-judgment range a triangulated estimate. Never relabel p5–p95 as an 80% interval: it is 90%. Do not revise the headline in prose without a revised saved model. Keep strategy disagreement and source dependence visible; synthesize only with a defensible rationale. A user-requested interim report must disclose its incomplete status. Read the issued presentation and include its scope and limitations; acknowledged shared evidence and research gaps must remain visible. Provisional issuance is for honest interim reporting, not a reason to stop feasible consequential research.",
            "evidence": "Agent review with links to completed work, unresolved items, result status, and a specific stopping rationale; final answer distinguishes observations, assumptions, and computed results.",
        },
    ],
}


def research_workflow():
    """Return guidance, never a claim that the current study passed a review."""
    return deepcopy(RESEARCH_WORKFLOW)


def research_guide():
    workflow = RESEARCH_WORKFLOW
    steps = "\n\n".join(f"{i}. {s['title']}. {s['instruction']}\nRecord: {s['evidence']}"
                          for i, s in enumerate(workflow["steps"], 1))
    return ("AGENT RESEARCH CONTRACT — HIGH EFFORT BY DEFAULT\n"
            "For empirical estimation, follow this workflow before presenting a completed estimate. "
            + workflow["applies_to"] + "\n" + workflow["override"] + "\n\n" + steps
            + "\n\nResearch record: " + workflow["record"]
            + "\nVerification boundary: " + workflow["verification"] + "\n\nCOMMAND REFERENCE\n")
