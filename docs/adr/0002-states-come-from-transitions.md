---
id: ADR-0002
title: An item's state comes from appended transitions, never from the item
status: accepted
decided_on: 2026-10-25
decided_by: Chiheb Dkhil
governs: [workitem.epic-m, workitem.epic-n]
---

# An item's state comes from appended transitions, never from the item

## Context

A state written on an item is overwritten and its history lost, and only a person can write it.
Events (a merged pull request, a promotion) and people must set state the same way.

## Decision

A change of state is a Transition fact appended to the graph, the previous one superseded, and a rule derives the item's state from the current transition.

## Consequences

History comes free through the engine's own supersession and `--as-of`; a block is a transition that
must carry its reason and whom it waits on; the board, the inbox and the questions read one thing.
Two transitions on the same day keep their order through the chain.
