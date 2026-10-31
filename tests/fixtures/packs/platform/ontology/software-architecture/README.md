# Software architecture — starter vocabulary

How a product's solution is shaped. Sits on `product`: a requirement, a risk, a decision or a document is
the product's, and `satisfies` is the one edge from an asset back to the requirement it meets (SA8, SA17).

## What this shape is for

Most architecture documentation answers "what is this". This vocabulary is arranged to answer the
questions people actually ask under pressure:

- **"If we change this, what breaks?"** `consumes` is the edge that answers it. Coupling lives in the
  interfaces others depend on, not in the boxes. Record `exposes` and `consumes` before anything else.
- **"Who do I call?"** `owned_by` points at a `Team`, never a person. People move; the question does
  not.
- **"Why is it like this?"** The product's `Decision`, `about` the asset it shaped. Architecture without
  recorded reasons gets re-litigated every year.
- **"What is fragile?"** The product's `Risk`, with `threatens` and `mitigated_by` widened to the estate. A risk nobody can trace to a
  component is not actionable.
- **"What does the business lose?"** `Capability`, reached through `enables`. This is the only class
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
