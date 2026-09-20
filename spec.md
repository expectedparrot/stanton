# stanton — an estimation workbench — Spec v0.4

2026-09-19 · @Someone

## 1. Purpose & design principles

`q` is a CLI workbench that lets an LLM agent produce sourced numerical estimates with honest uncertainty — from "Starbucks net revenue FY2028" to "golf balls manufactured in 1987" to pure Fermi questions. The agent supplies judgment (strategy choice, sourcing, naming assumptions); the tool supplies machinery the agent is unreliable at (probabilistic arithmetic, unit discipline, provenance, correlated sampling).

**Naming:** the package and the CLI binary are both `stanton` (PyPI name confirmed unclaimed as of 2026-09-19; register early — single-word names get squatted).

- **Ontology in tools, policy in model.** No hard-coded strategy pipelines. Strategies are prompt-level guidance referencing CLI idioms; the tool doesn't care which the agent uses or invents.
- **Everything normalizes to a distribution with provenance.** The interlingua is a probability distribution over one scalar, wrapped with method, sources, assumptions, notes. This makes arbitrary strategies composable.
- **The provenance-and-honesty layer is the product.** The dry-runs showed the DAG/sampler core stable; nearly every gap was about recording context, justifications, abandonments, fuzzy dates. That layer is what raw-code agents never build for themselves.
- **Validators over enforcers.** `stanton lint` warns; the agent can override. Bounds warn rather than clip — violations are diagnostic signal.
- **Small probabilistic surface.** Lognormal/normal/mixture, scenarios, correlation via shared assumptions. Richness comes from composition, not knobs.
- **Source verification is the agent's job.** The tool guarantees no assertion has an empty provenance slot; the agent is responsible for slot contents being real. Lint does cheap mechanical checks; the calibration bank catches bad sourcing by consequences.
- **Disagreement is signal.** Divergence between strategies, decompositions, or sources is surfaced as a headline finding, never silently averaged away.

## 2. Core data structures

| Type | What it is | Key fields | Version notes |
| --- | --- | --- | --- |
| **Quantity** | The atom: a named scalar | name, units, space tag (log/linear/logit), definition string (tight: "net revenue, GAAP, nominal USD, FY ending \~Sep 2028"), status (known / estimated / target) | space tag added v0.4 (gap 27) |
| **Distribution** | The interlingua | quantiles or samples internally; constructors `from_interval(low, high, p, shape)`, `from_point`, `from_samples`, `from_quantiles` | — |
| **Estimate** | Distribution + provenance; immutable, revision creates new | method, sources (freetext, agent-verified), assumptions cited, notes, epistemic/aleatoric kind, timestamp | `stanton note` freeform context on any node (gap 1); kind tag (gap 14) |
| **Anchor** | An Estimate flagged as externally sourced | kind: `point` / `consensus` / `derived`; `--asof` date or date-range; definition tag (+ reconstruction confidence); ancestry | consensus kind (gap 4); fuzzy asof (gap 7); def tags (gaps 22, 24); ancestry for citation-loop lint (gap 29) |
| **Assumption / Factor** | Named proposition or latent variable, global registry per session | name, definition, prior | shared leaves across forks cite the same registry entry — correlation inferred, never declared pairwise |
| **Scenario** | Discrete regime with probability | p (requires `--reason`, lint-enforced, gap 2), definition, conditional estimates via `--given` | — |
| **Decision** | Variable the asker controls, never sampled | options, default, "deliberately open" terminal state | new v0.3 (gap 12); results reported per branch |
| **Definition** | Base measure + composable inclusion predicates; a mask over the DAG | measure, predicates, owner (asker / claimant / reconstructed+confidence) | new v0.3 (§10, gaps 21–25) |
| **Model DAG** | Quantities as nodes, relations as edges | arbitrary expressions; relations may mix spaces | **Leaves global to the session; forks fork only the relation graph** (gap 8) |
| **Series** | Quantity indexed by period (incl. periodic indices) | per-period anchors, autocorrelated growth sampling; serves function-valued targets evaluated at T | new v0.2 (gap 5); periodic use v0.4 (gap 26) |
| **Bound** | Hard floor/ceiling with reason | lower/upper, reason string | new v0.2 (gap 10): sampler warns on violation mass, truncates only with `--clip` |
| **StrategyRecord** | One estimation approach, attempted or not | fork ref, status: active / merged / **abandoned** (+ reason) | abandonments are first-class audit entries (gap 9) |
| **QueryContext** | Injected environment resolving context-dependent targets | now, tz, locale | new v0.4 (gap 26) |
| **Allocation** | Partition of a conserved known total | total ref; named shares on the simplex; cross-classified constraints | new v0.4 (gap 28) — first core sampler extension |

Strategy library (guidance, not code): direct lookup · anchor + transform · decomposition · reference class · bounding · interpolation between knowns. Real questions run 2–4 in parallel as forks.

**Reference classes** get structure (`q refclass define`) but the data-backing question is open — see §7.

## 3. CLI verbs

```
# Defining & sourcing
stanton define <name> --units <u> --def "<tight definition>"
stanton define <name> --over hour_of_day         # function-valued target; evaluated at QueryContext.now
stanton context now                              # injected QueryContext: clock, tz, locale
stanton note <node> "<freeform context>"         # texture that drives reasoning; audit surfaces it
stanton anchor <name> --value X --source "..." --asof 2025-10
stanton anchor <name> --kind consensus --mean X --high Y --low Z --n 28 --asof <date>
stanton anchor <name> --value X --source "..." --asof 1998..2008   # fuzzy-dated source
stanton estimate <name> --interval LO HI --p 0.8 --shape lognormal \
    --assumes a1,a2 --source "..." --note "..."
stanton estimate <name> --given <scenario> --interval ...          # conditional estimation

# Structure
stanton relate <target> = "<expression over nodes>"
stanton relate <target> --path --series <s>      # path-structured, autocorrelated
stanton allocate <total> --into {a, b, c, ...}   # simplex shares of a conserved total
stanton scenario define <name> --p 0.45 --reason "..." --def "..."
stanton refclass define <name> --def "..."
stanton refclass populate <name> --quantiles "5:..., 50:..., 95:..." --source "..."
stanton bound <target> --lower X --reason "..."  # warn-don't-clip (--clip to truncate)
stanton fork <target> --as <strategy_name>       # forks relations; leaves stay global
stanton strategy abandon <name> --reason "..."   # roads not taken enter the audit

# Running & reading
stanton sample <target> -n 20000 --correlate auto [--calibration v2] # calibration flag proposed; v0.6 uses calibration apply
stanton show <target> --quantiles 5,25,50,75,95
stanton compare <target> --by fork               # per-strategy breakdown; divergence flagged
stanton merge <target> --from f1,f2 --weights 0.5,0.5 --reason "..." --method mixture
stanton sensitivity <target> [--rank voi]        # variance decomposition; VoI ranks resolvables
stanton check <claim> --against <target>@<def>   # percentile verdict + predicate-flip sensitivity
stanton audit <target>                           # provenance tree incl. notes & abandonments
stanton lint                                     # warnings, overridable

# Elicitation (§9)
stanton survey draft --phase triage|targeted --budget N
stanton survey compile / send --to asker|llm_panel:...|human_panel / ingest

# Session
stanton save / load / resolve <target> --outcome X   # feeds calibration bank
```

Design rule: roughly one verb per thing an analyst does. New verbs need a dry-run failure to justify them.

## 4. Sampling & merge semantics

- **Spaces (v0.4).** Every quantity carries a space tag: `log` (default for strictly positive quantities — estimation error is multiplicative), `linear` (sign-crossing: net income, anomalies, deltas), `logit` (bounded rates). `support-crosses-zero` lint enforces the tag; two-part models — P(negative) + conditional magnitudes each side — are the standard form for sign-crossing financials. Relations may mix spaces; correlation is defined in each node's own space.
- **Correlation via shared assumptions, `--correlate auto`.** Leaves citing the same Assumption/Factor/Scenario are tied through it; leaves with no shared citations sample independently. Degrades gracefully to independence. Because leaves are global, this works across forks too.
- **Scenarios** mix discretely: sample regime by p, then conditionals within it. Same sampled regime applies to every leaf citing it (and across periods in a Series).
- **Series** sample paths with persistent shocks (autocorrelated growth), not independent per-period draws. A Series over a periodic index (hour-of-day) also serves function-valued targets, evaluated at query time T.
- **Allocations (v0.4).** Parts of a conserved known total sample as simplex shares (Dirichlet-style), conservation holding by construction; cross-classified totals (holder × denomination) constrain cells from multiple directions — sampling scheme open (§7).
- **Bounds**: report violation mass ("4% of samples exceed upper bound") as a warning; truncate-and-renormalize only with `--clip`. Silent clipping hides broken models.
- **Merge**: default `mixture` (preserves disagreement as width); `logpool` available. Weights require a `--reason`. Built-in divergence flag when strategy medians differ by more than their internal widths — that flag is a headline finding. Anchors sharing ancestry are down-weighted, not treated as independent (gap 29).
- **Per-strategy results survive to the output.** `stanton show` on a merged target always offers the `--by fork` view; the merged interval never replaces the breakdown.

## 5. Lint rules (warnings, overridable)

| Rule | Catches |
| --- | --- |
| unsourced-leaf | Estimate with no source AND no reference class AND no reason |
| unsourced-scenario-p | Scenario probability with no `--reason` (vibes-as-probability) |
| unsourced-merge-weights | Merge weights with no `--reason` |
| narrow-for-horizon | Interval suspiciously tight given target horizon (calibration-informed) |
| unit-mismatch | Relation combining incompatible units; dozen/count-style conversion traps |
| def-drift | Refclass or anchor definition mismatching target definition (manufactured vs. sold; worldwide vs. US; fiscal vs. calendar) |
| orphan-assumption | Assumption cited by exactly one leaf (possible misspelling of an existing one) |
| stale-anchor | Anchor `--asof` predates a registered major event on the same quantity |
| empty-source-slot | Provenance field mechanically blank (content verification stays the agent's job) |
| future-leak | For backtests: source dated after the question's as-of time |
| bound-violation | Sample mass outside declared bounds |
| divergent-strategies | Fork medians differ by more than internal widths at merge time |
| shared-ancestor | Anchors whose provenance plausibly descends from a common origin entering a merge as independent evidence (citation loops endemic to aggregator market sizes) |

## 6. Calibration layer

Every Estimate records method, horizon, question shape, and (eventually) outcome via `stanton resolve` — so the resolved-question bank accumulates as a side effect of use. Calibration is **pattern-level, not domain-level**: overconfidence factors are measured per strategy type and question shape (direct lookups vs. decompositions vs. long-horizon projections), because failure modes belong to the method, not the subject. Learned variance-inflation factors are proposed to apply at sample time (`--calibration v2`) with zero agent effort.

**Implemented in v0.6:** explicit `calibration fit/show/apply/evaluate` on fixed
cohorts. Training-only CRPS grid search selects a linear spread scale for one
named strategy or mixture. Immutable artifacts pin training evidence; application
returns raw/adjusted overlays, and test reports disclose pre-fit observations.
Pattern membership is supplied through cohort selection, not automatically
classified. Sample-time integration and joint calibration remain proposed.
See [the calibration contract](docs/calibration.md) for exact behavior and limits.

Seed the bank three ways: historical facts estimated without retrieval, backtests run "as of" past dates with `future-leak` lint enforced, and live questions resolved over time. Consensus-kind anchors carry their own bias profile (herding, optimism at long horizons) applied at ingestion.

Calibration also closes the sourcing loop: an agent whose freetext sources don't hold up produces estimates that score badly, and the per-method correction catches it by consequences.

## 7. Open questions

- [ ] **Reference-class data backing** (biggest open item, gap 3). Interface is agent-entered summary stats with sources; should a curated dataset ship for common domains (company financials first) as an accelerator? Where does it live, who maintains it?
- [x] **Multiple candidate definitions.** Resolved v0.3: definitions are composable predicate objects built by vignette + boundary-probe elicitation (§10); `stanton decision` covers transactional ambiguity. Remaining sliver: probe design for domains without natural edge cases.
- [ ] **Fuzzy `--asof` propagation mechanics.** Date-ranges on anchors are specced; how exactly date uncertainty widens a fitted trend needs a concrete rule.
- [ ] **Series ⇄ scenario interaction.** A regime sampled once should shape a whole path; the API for "scenario-conditional growth within a Series" is sketched but not exercised.
- [ ] **LLM-panel validity.** Synthetic expert elicitation (gap 20) needs its calibration story run before it's trusted: which question shapes do persona panels answer calibratedly, if any?
- [ ] **Asker reliability priors.** Interval-widening constants and per-answer-type error models (sq ft vs. pitch vs. preference) need literature values or bank data.
- [ ] **Cross-classified conservation.** Allocation sampling under simultaneous partitions (holder × denomination) needs a scheme — iterative proportional fitting over Dirichlet draws? The one place genuinely new sampler math is required (gap 28).
- [ ] **Cross-question coherence.** Out of scope for the single-question analyst tool, but shared macro factors across questions would matter if scope grows.
- [ ] **Refclass def-drift enforcement.** Lint rule exists; matching definitions semantically (not string-wise) is unsolved — probably an LLM-judge lint pass.

Resolved in v0.2: retrieval and source verification are the agent's job (tool checks slots are filled, not that contents are true); forks share global leaves; merge defaults to mixture.

## 8. Changelog v0.1 → v0.2

All changes trace to gaps found in two dry-runs (Starbucks FY2028 revenue; golf balls manufactured 1987).

| # | Gap (session) | Spec change |
| --- | --- | --- |
| 1 | Anchor texture had nowhere to live (SBUX) | `stanton note` on any node; `stanton audit` surfaces notes |
| 2 | Scenario p's were vibes (SBUX) | `--reason` required; `unsourced-scenario-p` lint |
| 3 | Refclass had no data story (SBUX) | Interface: agent-entered quantiles + sources; curated-dataset accelerator → open (§7) |
| 4 | Consensus ≠ point anchor (SBUX) | `--kind consensus` with mean/high/low/N + bias profile |
| 5 | Lumped 3-year growth; FY26 guidance unusable (SBUX) | `Series` type; `stanton relate --path` |
| 6 | Source objects vs. freetext (SBUX) | Resolved: agent's job; tool checks slots filled; calibration catches by consequences |
| 7 | Undated anchor (golf) | Fuzzy `--asof` date ranges; propagation mechanics → open (§7) |
| 8 | Forks silently contradicted each other (golf) | **Global leaves, forked relations** — deepest v0.2 decision |
| 9 | Roads not taken vanished (golf) | `stanton strategy abandon --reason`; abandonments in audit |
| 10 | Bounding had no verb (golf) | `stanton bound`, warn-don't-clip, `--clip` opt-in |
| 11 | Merge semantics hand-waved (golf) | mixture default, weight `--reason`, divergence flag |
| 12 | Decisions sampled like uncertainties (roof) | `stanton decision` type; results per branch; "deliberately open" terminal state |
| 13 | Unknowable-from-desk facts (roof) | `--resolvable` tag; sensitivity ranks variance × resolvability (VoI) — became the survey generator |
| 14 | Quote spread ≠ ignorance (roof) | `--kind epistemic\|aleatoric`; target functionals (`min(quotes, k=3)`); sensitivity split by kind |
| 15 | Clarification was unstructured (survey capability) | Elicitation layer (§9): questions bound to model slots, typed write-back |
| 16 | Asker knowledge untapped (survey capability) | Asker-as-source with reliability model; interval-answer overconfidence widening |
| 17 | Question selection ad hoc (survey capability) | VoI-budgeted generation; two-phase triage/targeted; range-acceptance stop rule |
| 18 | No skip logic (live survey demo) | Delegated to EDSL; validated in-container (Survey + add\_skip\_rule) |
| 19 | Survey↔model plumbing (EDSL) | `stanton survey compile`; `question_name` as binding key; Scenarios inject model state |
| 20 | Single-respondent assumption (EDSL) | Respondent axis asker/LLM-panel/human-panel; panel numericals → `from_samples`; synthetic-expert strategy, uncalibrated-until-scored |
| 21 | "Pick a definition" fails askers (creator econ) | Definition = base measure + predicates, built from vignette + boundary probes (§10) |
| 22 | Published anchors embed unstated definitions (creator econ) | Definition-tagged anchors; `stanton bridge` factors as ordinary uncertain estimates |
| 23 | Definition isn't always the asker's to choose (creator econ) | Purpose elicited first; claim-check pins definition to claimant's; conflicting elicitations kept with roles (primary/branch) |
| 24 | Reconstructing someone's definition is itself uncertain (creator econ) | `--def-reconstructed --confidence`; bridges inherit reconstruction uncertainty |
| 25 | Claim-check ≠ distribution (creator econ) | `stanton check` verb: percentile verdict + predicate-flip sensitivity |
| 26 | "Right now" unresolvable; some targets are functions (quick-fire: NYC asleep) | Injected QueryContext (now, tz, locale); `define --over` for function-valued targets evaluated at T; Series reused for periodic profiles |
| 27 | Log-space default breaks on sign-crossing quantities (quick-fire: Tesla NI) | Per-quantity space tag (log/linear/logit) + support-crosses-zero lint; families on all of ℝ; two-part loss models; relations may mix spaces, correlation lives in each node's own space |
| 28 | Conserved totals inexpressible (quick-fire: ATM cash) | Allocation type: simplex shares of a known total, conservation by construction, cross-classified partitions — first true core sampler extension in eight rounds |
| 29 | Aggregator anchors descend from the claim under test — citation loops (Goldman end-to-end run) | ancestry field on anchors; shared-ancestor lint; merge down-weights non-independent evidence instead of dropping it |

Meta-observation, updated after eight rounds: the gaps cluster into three subsystems — the **provenance-and-honesty layer** (1–11), the **decision-support layer** (12–17), and the **definition layer** (21–25) — with the elicitation layer (15–20) feeding all three. The DAG/sampler core survived seven rounds unchanged; round eight produced the first true core extension (allocation/conservation, gap 28) and one default that had to become a parameter (space tags, gap 27). Everything else remains composition — the original bet held longer, and failed more gracefully, than expected.

## 9. Elicitation layer (EDSL integration) — v0.3 draft

The asker (and, generalized, any respondent) is a first-class source, reached through structured surveys built on [EDSL](https://github.com/expectedparrot/edsl) rather than chat clarification. Core principle: **every question is generated from, and bound to, an open slot in the model; answers write back typed.**

- **Binding convention:** `question_name = "<slotkind>__<node_id>"` (e.g. `decision__cedar_type`, `leaf__roof_area_sqft`). Ingest is a dict-merge into model slots. Validated 2026-09-19 in-container: `Survey` + `add_skip_rule` compile with these names; rules are Jinja2 expressions over prior answers.
- **Skip logic & piping:** delegated to EDSL (closes gap 18). Conditional follow-ups ship inside phase 1 instead of costing round-trips.
- **Two-phase administration.** Phase 1 *triage* (pre-modeling): purpose, decisions, definitional probes, "what private data do you hold." Phase 2 *targeted* (post-sensitivity): top-k of the VoI ranking filtered by answerable-by-asker; model state injected into question text via EDSL Scenarios ("current estimate {{ scenario.p10 }}–{{ scenario.p90 }} — acceptable?"), doubling as the stop rule.
- **Question-type mapping:** decision → multiple choice, with "show both branches" a legitimate terminal state distinct from unasked; contested definition → vignette + boundary probes (§10), never "pick a definition"; knowable fact → numerical, units enforced, "don't know" allowed; asker's own uncertainty → interval elicitation with overconfidence widening (\~90% requested → \~50% actual coverage); output priorities → ranking.
- **Informative nulls are provenance.** "No quotes exist" writes an audit entry so later sessions don't re-ask; unanswered questions leave slots wide and are logged like abandoned strategies. Conflicting answers (purpose vs. boundary probes, seen live) are surfaced as roles, not averaged (§10).
- **Respondent axis:** `asker` | `llm_panel(persona, n)` | `human_panel` (Coop), ordered by cost. Panel answers to a numerical question = `Distribution.from_samples` with respondent provenance. LLM-persona panels enter the strategy library as *synthetic expert elicitation*, flagged uncalibrated-until-scored — EDSL's own docs note panel responses reflect statistical patterns, not real opinions — but backtests make panel calibration an empirical column in the bank rather than a debate.
- **Verbs:** `stanton survey draft --phase triage|targeted --budget N` (assembled from decisions + lint flags + VoI ranking) · `stanton survey compile` (→ `edsl.Survey`) · `stanton survey send --to asker|llm_panel:...|human_panel` · `stanton survey ingest` (typed write-back).

## 10. Definition layer — v0.3 draft

For contested targets ("how big is the creator economy"), the definition is not an input string — it is a first-class, uncertain, multi-owner object. Grown from dry-run five (creator economy, gaps 21–25).

- **Definitions are composable predicates.** `Definition = base measure (earnings | spend | ecosystem) + inclusion predicates ({etsy: IN, adult: IN, ...})`. Built by elicitation — a vignette for the measure axis, boundary probes for the predicates — never by asking the asker to pick from abstract candidates they can't evaluate.
- **One model, many definitions.** Definition-conditional leaves carry predicate switches (Etsy GMV enters iff `etsy: IN`), so a definition is a *mask over the DAG*, not a fork. Every definition branch reuses the same leaves, correlations, and provenance.
- **Purpose pins the definition.** Claim-checking snaps the primary definition to the claimant's; opportunity-sizing sets it to the asker's addressable slice. When the asker's probes conflict with the pinned definition (observed live), both survive with roles — primary vs. branch — and the gap between them is sized, not averaged away.
- **Anchors are definition-tagged; bridging is estimation.** A published number attaches only under its own definition. `stanton bridge D_a D_b --interval ... --source ...` is an ordinary uncertain estimate. Def-drift lint stops being a warning and becomes the model's substance.
- **Reconstructed definitions carry confidence.** `stanton anchor ... --def-reconstructed --from "GS Apr-2023 report" --confidence medium`: definition uncertainty about someone else's number compounds with value uncertainty, and bridges inherit it.
- **Claim-checking is an output type.** `stanton check <claim> --against <target>@<def>` → percentile placement of the claimed value in the independent distribution under the reconstructed definition, plus *predicate-flip sensitivity*: which definitional choices change the verdict. For contested quantities the headline is usually "under which definition is this claim true," not "is it true."

## 11. Worked example: the Goldman claim-check (first end-to-end run)

**Question:** is Goldman Sachs' claim — creator economy ≈ $250B (2023), → $480B (2027) — defensible? Purpose elicited via phase-1 survey: *claim-check*, which pinned the primary definition to Goldman's (§10); asker's own boundary probes (maximal inclusion) survived as a branch.

**1. Reconstruction** (`--def-reconstructed`, public summaries only): GS frames the number explicitly as *total addressable market*, operationalized through three named channels — brand deals (≈70% of creator income), platform ad-rev share, subscriptions/donations/direct payments — with ≈50M monetizing creators. Confidence tags: HIGH on the channels and TAM framing; MED-OUT on commerce GMV and adult platforms; UNCLEAR on China; **LOW on the dominant axis — whether $250B measures current flows or addressable pools**. Top VoI action recorded: the paywalled report itself would collapse most reconstruction uncertainty.

**2. Predicate-masked bottom-up (2023 flows):** components enter iff their predicates fire — brand deals ex-China $18–30B; China KOL market $8–15B; platform payouts $14–24B (YouTube's "$70B/3yr" anchor def-drift-corrected: it includes artists and media companies, so creator share ×0.5–0.7); core fan-direct $2–4B; OnlyFans gross ≈$6.6B (adult); China livestream tipping $15–30B; commerce GMV $80–300B (courses, merch, KOL live-shopping). One model, five definitions by toggling predicates: strict three-channel p50 ≈ **$58B**; +China ≈ $95B; +commerce GMV ≈ **$250B**; TAM-inflated strict+China ≈ $170B.

**3. Gap 29 found in flight:** third-party "corroborations" (2025 ≈ $250B, 2026 ≈ $310–323B) are aggregator figures whose ancestry plausibly includes Goldman's own number — circular validation. Down-weighted, not dropped.

**4. Verdict (`stanton check`):** as money that actually reached creators through GS's three named channels, $250B sits **beyond p99.9 — not defensible** (that quantity was ≈$60–100B); with commerce GMV counted, **≈p50 — defensible**; as addressable-pool accounting, **≈p55–70 — defensible**. Predicate-flip: the verdict is decided almost entirely by {commerce\_gmv, tam\_vs\_flows}; {china, adult} move the number 2× but never rescue the strict reading. The growth claim (17.7% CAGR) lands ≈p55–75 of definition-consistent paths — optimistic but inside. **Headline: "$250B" was never a measurement; it is an accounting choice — off ≈3–4× under the literal reading of Goldman's own channels, reasonable under GMV-inclusive or TAM readings, with a defensible growth rider.**

**5. Pipeline scorecard:** every subsystem load-bearing (reconstruction confidence → conditional verdict; predicate masks → one model, five definitions; resolvable tag → "buy the report" as top VoI; def-drift caught inside a component anchor; genealogy-aware merge). One new gap (29), zero core changes — and the machinery changed the answer: naive averaging of published numbers would have blessed $250B; the definition layer located where the claim lives and dies.
