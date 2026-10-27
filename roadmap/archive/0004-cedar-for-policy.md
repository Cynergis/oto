---
id: ADR-0004
title: Cedar is what the access policy compiles to
status: accepted
decided_on: 2026-10-27
decided_by: Chiheb Dkhil
governs: [workitem.epic-e]
---

# Cedar is what the access policy compiles to

## Context

Epic E makes the graph the source of truth for access policy: a rule permits or forbids a
permission for a role, and the data layer says what each table and column holds. Something must
enforce it: the engine's own gates (curate apply, decide, promote), the factory's hooks on a
runner's machine, and whatever store or gateway sits in front of the data. Each needs the same rules
in a form it can evaluate, and a reviewer needs one form to read and approve. Writing an evaluator
of our own invents a policy language nobody else can audit; picking one of the existing languages
means living with its shape.

## Decision

The active policy rules of the graph compile to Cedar, the open policy language with a verified
evaluator, and the bundle carries a JSON form of the same rules beside the Cedar text, so the
engine's evaluator and the hooks stay plain Python over the standard library and never need a
Cedar engine on the machine that runs them.

## Consequences

A rule is already Cedar-shaped: a principal (a role or a team), an action, a resource narrowed by a
selector, `forbid` outranking `permit`; the compile is a projection, not a translation, and
`resource is <Class>` and `resource in [...]` say what a permission's class and a rule's singled-out
resources mean. Where a Cedar engine exists (a gateway, a store with a Cedar authorizer), the
`.cedar` file is the policy; where none does, the JSON form is, evaluated by the stdlib evaluator
the snapshot of E3 uses, and the two are one bundle with one hash and one signature, so neither can
drift from the other. The graph, not the files, is edited; the build writes the bundle, the deploy
pipeline carries it with the store, and `oto policy verify` refuses a file edited by hand. The
rules use the Cedar 3 syntax (`is`); an older authorizer gets the JSON form. What Cedar cannot say
in one policy (a priority between permits) stays a reader's aid in the bundle, not a semantic.
