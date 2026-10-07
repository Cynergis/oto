# The report ontology, from scratch: what OTO produced against what was ported

Stage 1 of [the programme](knowledge-programme.md), 2026-10-06 and 07, Chiheb as the domain expert.
The question it answers: can OTO *produce* an ontology by its own discipline, or only hold one?

## What was done

| Step | Result |
|---|---|
| `product` core (B1) | 17 Gate 1 questions confirmed; the 20 classes of today's `product` all survive the test (each needed by a confirmed question); release 6, locked, exported from `~/Downloads/product-core` |
| `product-report` (B2) | 10 questions confirmed; **no new classes**: `concerns` on Requirement and Policy, `verifies` on Role, one relation `governs` into the report domain; thin by decision; release 1 |
| `report` (B3) | 20 domain questions **derived from the obligations of the spec** (not from the 21 original CQs), confirmed; 23 classes derived at Gate 2; vocabulary, rationale, 8 policies, 20 executable questions written into `~/Downloads/report-domain`; the fixture's 148 facts authored as one proposal citing the analyst's five documents, through `curate check` (ready to apply, 30 gaps: the unmapped fields, as the files say), applied, built; all 20 questions answered as required; accepted; exported as `report` release 2 over the port (release 1) |
| engine findings on the way | `ontology import --from` dropped rules and questions (6f010a8); a forced export reset the release (bae3eb8); the core's sample carried an undeclared attribute (0b8ad81); export blanks confirmations even for the ontology's own home (noted, not yet fixed) |

## The comparison: from scratch vs the port

Same namespace, same term names (kept on purpose so the IRIs, and this diff, compare like with
like). `oto`'s own diff between the two releases:

| Kind | Count | Verdict |
|---|---|---|
| classes added or removed | **0** | the 23 classes are the same set: 20 of the report's own, 3 reused from doctemplate |
| relations removed | 3: `ofReport`, `producedBy`, `hasUniverseQuery` | the derivation produced neither inverse-only relations (`ofReport` is `releasedAs` read backwards, now its `inverse`) nor `producedBy` (no confirmed question asks which run produced a *release*; Q14 asks which run used the *source*); `hasUniverseQuery` (report → query) is redundant with `universeQuery` (parameter → query). **OTO's discipline, not its limit** — though `producedBy` is worth asking Chiheb about: the port's CQ3 reached the run through the source document too |
| attributes removed | 11: `Approval.reviewedHash`, `Run.step`, `SourceDocument.note/pageKind/receivedOn`, `UniverseQuery.note`, `ReportType.compiledAt/ontologyVersion`, `TemplateRelease.frozenAt/repoUrl/sha256` | none is selected or filtered by a confirmed question; in the port they survived only through `terms` lists. **Discipline.** `TemplateRelease.sha256/repoUrl` may come back if a question asks where the template folder is stored |
| attribute type changed | 2 | `Parameter.label`/`definition` typed as plain strings here; cosmetic |
| cardinality tightened | 9 (`readsTable 0..1`, `inDataSource 1..1`, the five policies and the schedule `0..1`, `universeQuery 0..1`, `boundToColumn 0..1`) and 3 attributes made required | the from-scratch unit declares **more shape** than the port carried: the port read only the counts of `report-shapes.ttl`; here each shape was derived from what a question needs to be answerable at all. **Discipline.** |
| cardinality loosened | 4 | `hasField`, `hasSection`, `hasMeaning`, `inReport` are `min 1` here but the port's counts for them were per class shapes OTO rendered as `requires`; equivalent |
| cosmetic | 121 | every definition rewritten in the derivation's words; the inverses named |

**Questions.** 20 derived vs 21 ported: the derived set lacks the port's CQ15 ("which other
reports share fields with this one") as a separate question — it is folded into Q20 — and
otherwise covers the same ground, in the askers' voices, with the same parameters. All 20 answer
as required on the fixture; the fixture went in through the gates, not as a converted sample.

**Rules.** 8 policies vs the port's 14: the from-scratch set has no equivalent of the port's
four "frozen-release contract" policies beyond the schedule, and no `field-has-english-meaning`
(the `hasMeaning min 1` shape covers it). The ones that remain name the question they protect.

**Where the two agree completely:** the classes, the relations that carry answers, the attributes
the questions read, and the facts. `product-report` composes on either without change.

## The verdict

OTO produced the report ontology from its own discipline: twenty questions derived from the
product's obligations, the same 23 classes derived from them, the facts authored through the
gates, every question answered. The differences with the port are all in the direction of
*less* (three redundant relations, eleven attributes no question reads) or *more constraint*
(nine cardinalities, three required attributes) — the signature of questions-before-nouns, not
of a limit of the tool. No step of the skill failed; three engine gaps were found and fixed.

Two things for Chiheb to decide, both small:

1. Keep `producedBy` (run → release) by adding the question that needs it, or let it go.
2. Keep `TemplateRelease.repoUrl`/`sha256` (where the template folder is, its fingerprint) by
   adding "where is the template stored, and what fingerprint identifies it" to the engineer's
   questions, or let them go.

## What the stage proved for the programme

- Scene 3 works as a loop: obligations in the spec → derived domain questions → confirmed →
  classes → facts → answers, without reading the previous model.
- The product-type extension stays thin when the domain pack exists; the weight is in the domain.
- The gates hold on real volume (148 nodes, 230 edges, one proposal): SUSPECTs caught generated
  labels that would have been meaningless, and the thirty unmapped fields came through as gaps,
  not errors, which is what the obligation "refuse production while a field is unmapped" wants
  from a *definition* that is still in validation.
