---
id: ADR-0005
title: The generated system's IAM is derived from the policy and never enforced by OTO
status: accepted
decided_on: 2026-10-27
decided_by: Chiheb Dkhil
governs: [workitem.epic-e]
---

# The generated system's IAM is derived from the policy and never enforced by OTO

## Context

Epic E made the graph the source of access policy and OTO its enforcer: the active rules compile
to a Cedar bundle (ADR-0004), an agent runs under a signed snapshot, the hooks and the served
engine refuse what the snapshot does not permit. The system OTO helps build has access control of
its own, on the platform it runs on: a service account may read one dataset and write one table,
and the platform enforces that through its IAM. Writing those bindings by hand repeats the policy
in a second language that drifts from the graph; having OTO enforce them at runtime would put the
engine in the request path of a system it only describes.

## Decision

The platform's IAM bindings are derived from the access policy the graph already holds, written
by the build as a design-time output beside the policy bundle, and OTO never enforces them: the
platform does.

## Consequences

The model gains three facts and nothing else: a `Component` (or a `System`) `runs_as` a
`Principal`, the service account it runs under; a `Permission` names the platform role it maps to
(`cloud_role`, `roles/bigquery.dataViewer`), a fact the organisation states rather than a catalogue
the engine keeps, so the engine knows no provider's roles; and a resource says where it is on the
platform (`resource_uri`). Read through the roles each principal holds, the same active rules that
compile to Cedar give the bindings: a member, a role, a resource. A forbid withholds the binding a
permit would have made for the same member, resource and action, as it outranks the permit in
Cedar, so the two outputs never disagree. What cannot bind is named and left out, never guessed: a
permission without a platform role, a resource without a place, a principal without an identity.

`oto policy iam` and the `iam` build stage write `build/iam/`: the bindings, the GCP form resource
by resource in the shape `set-iam-policy` takes, and a manifest hashed and signed like the policy
bundle, so a reviewer verifies the bindings the way they verify the rules and the deploy pipeline
carries both. GCP is the first provider; another is a second shape over the same derivation, not a
second model.

The bindings are written back into the graph as generated `Control`s in the architecture
vocabulary, one per resource, that `safeguards` the resource and the components running as its
members and `derives_from` the rules it came from, carrying `generated_by` so nobody edits one by
hand. They enter the graph through the gates (`--apply`), never by writing it, and the CALM export
carries them, so the architecture document shows the IAM the policy implies. OTO does not enforce
them: the hooks, the snapshot and the served engine keep enforcing the policy on OTO's own actions,
and the platform enforces the bindings on the system's. Had OTO enforced both, a revoked permission
would have had two clocks; now it has the snapshot's TTL on one side and the platform's apply on
the other, and the audit log records only what OTO itself refused.
