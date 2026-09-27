# Software architecture — starter vocabulary

A first draft for describing a software estate. Edit it.

## What this shape is for

Most architecture documentation answers "what is this". This vocabulary is arranged to answer the
questions people actually ask under pressure:

- **"If we change this, what breaks?"** `consumes` is the edge that answers it. Coupling lives in the
  interfaces others depend on, not in the boxes. Record `exposes` and `consumes` before anything else.
- **"Who do I call?"** `owned_by` points at a `Team`, never a person. People move; the question does
  not.
- **"Why is it like this?"** `DecisionRecord` with a reason, and `decided_by` linking the thing to the
  decision. Architecture without recorded reasons gets re-litigated every year.
- **"What is fragile?"** `Risk` with `threatens` and `mitigated_by`. A risk nobody can trace to a
  component is not actionable.
- **"What does the business lose?"** `Capability`, reached through `supports`. This is the only class
  a non-engineer will use, so keep its names theirs.

## Two writers to one store

`writes_to` is separated from `reads_from` on purpose. Two components writing one data store is the
most common quiet cause of an inconsistency nobody can explain. Once it is an edge, you can ask for it:

```bash
oto query --project <project> neighbors "<the store>"
```

## What is missing on purpose

No `Person`, no `Server`, no `Ticket`. Add them only when a question needs them. A vocabulary that
tries to be a configuration management database will be neither, and it will be out of date within a
month because nothing keeps it honest.

Consider instead pointing at what already holds that data. If your estate has a service catalog,
this graph should reference it, not copy it.
