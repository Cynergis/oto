---
id: ADR-0001
title: Evolve the work ontology rather than ship a new pack
status: accepted
decided_on: 2026-10-25
decided_by: Chiheb Dkhil
governs: [workitem.epic-m]
---

# Evolve the work ontology rather than ship a new pack

## Context

The roadmap's work pack (Epic M) needs three states, blocks that carry their reason, and a board.
The engine already shipped a `work` ontology with five states, ten confirmed questions and projects
built on it.

## Decision

The work pack evolves the shipped work ontology in place, with the former state names kept as `was`, rather than shipping a new pack beside it.

## Consequences

Existing graphs read as the new states without a migration; the ten questions carry over; one
ontology to maintain. The rename mechanism from the Tools rename (L2) is reused for attribute values.
