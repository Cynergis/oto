---
id: ADR-0003
title: Deployed is set only by events
status: accepted
decided_on: 2026-10-25
decided_by: Chiheb Dkhil
governs: [workitem.epic-m]
---

# Deployed is set only by events

## Context

Done means deployed, and the roadmap wants status to come from what happened, not from someone
updating a ticket.

## Decision

The deployed state is set only by an event, a merged pull request or a promotion to an environment, and `oto work set --state deployed` is refused.

## Consequences

An epic's later pull requests change nothing and say so; the same event delivered twice is recorded
once; a deployment lifts a block, since the item is where the event put it.
