---
id: ADR-0015
title: BigQuery can hold a graph, and a server reads it into memory rather than asking BigQuery each question
status: accepted
decided_on: 2026-11-05
decided_by: Chiheb Dkhil
governs: [workitem.a8]
---

# BigQuery can hold a graph, and a server reads it into memory rather than asking BigQuery each question

## Context

A team on Google Cloud wants its graph beside its data, in BigQuery, with no Neo4j to run. Until this decision BigQuery was
only an overlay: OTO could read a dataset someone else owned, and could not load a graph into one. `oto serve` knew SQLite and
Neo4j.

The obvious design is a third `Store` whose methods run SQL against BigQuery, as `Neo4jStore` runs Cypher. It fits badly.
The engine was written for cheap lookups: one `overview` answer on a two-node graph makes about a dozen store reads. Each would be a
query job, billed and taking about a second or more, though that hasn't been measured here. BigQuery's search also ranks differently
from FTS5, so answers would drift from the build's. The knowledge programme's plan (A8) went further and assumed BigQuery Graph and GQL. GQL
needs an Enterprise reservation, and OTO's reads are one hop, so nothing here needs it.

## Decision

- **A load mirrors the built store's tables into a dataset.** Each table becomes `<table>__b<n>`, in one load job, and one row
  appended to `oto_builds` commits the build. A view under each plain name lets people query the graph in SQL.
- **A server reads the newest committed build into an in-memory SQLite**, with the schema that build recorded, and serves it
  with `SqliteStore`'s reads. It looks for a newer load at most every `OTO_BIGQUERY_REFRESH` seconds (60 by default), and what it
  serves stays served when it can't.
- **Listing a table runs no query job**, so reading bills nothing and needs only `roles/bigquery.dataViewer`. A load
  needs `roles/bigquery.dataEditor` and `roles/bigquery.jobUser`.
- **One dataset holds one graph**, because BigQuery grants access per dataset.
- **Plain tables, no property graph and no GQL.** Nothing OTO reads needs them, and they would add a reservation to the bill.

## Consequences

- Answers match the build's to the character, search included, which no direct store could promise. The test runs
  every tool through both.
- A load that stops midway changes nothing a reader sees, and the next load goes over what it left. Load jobs are free, and no
  statement rewrites a table in place.
- A server starts by copying the whole graph, so the first question after scaling from zero is slower, and a very large graph
  needs more memory. A direct store remains possible for that case, behind the same interface.
- A new build reaches a running server within a minute, not at once. Neo4j is current on commit.
- People's own SQL through the views sees the graph's rows as the store holds them, with JSON fields as JSON text.
- `kg_read`, the overlay's read-only passthrough, is unchanged, and still runs a billed query.
