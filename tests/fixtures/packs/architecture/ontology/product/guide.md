# Reading a product graph

## What this graph is for

It holds why a product exists, for whom, what it must do, in which release, what was decided and
why, what is open, constrained, governed or at risk, and which document says so. Every fact
cites a document or a dated statement by a named role.

## The questions it answers well

- **Purpose and alignment.** "Why does this exist?" reads `Product` (problem, vision, domain,
  value stream). "What are we trying to achieve?" reads `Objective` nodes and `supports` between
  them; a `SuccessCriterion` `measures` an objective or a value proposition.
- **Traceability.** Requirement → `serves` → ValueProposition → `serves` → Objective is the spine.
  A `Feature` `realises` requirements; a `Scenario` `exercises` a requirement or a journey step.
- **Scope as of a date.** `in_scope_of` and `excluded_from` edges to a `Release` carry dates;
  ask with `--as-of` to see the boundary a builder saw when it started.
- **Governance.** A `Decision` is dated, reasoned, `decided_by` a role and `about` its subject; it
  `resolves` an `OpenQuestion` and `relies_on` an `Assumption`. A `Policy` `applies_to` what it
  governs and is `enforced_by` a role.

## What the rules flag

A requirement that serves nothing, a value proposition with no criterion, a decision with no
document, a requirement both in and out of one release (blocking), a shipped release still
blocked by an open question.

## What is deliberately not here

People by name (ownership sits on roles), delivery units such as stories, design surfaces such
as screens, and workflow stages or gates: each belongs to another vocabulary.
