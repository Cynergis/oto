# Data — a schema as facts, with what the schema cannot tell

On `software-architecture` (and so on `product` and `portfolio`): a `Table` is part of a `DataStore`
the estate already declares, its `Column`s carry type, key and meaning, a `LoadJob` loads it from a
`Feed`, a table or a store, and a `Usage` says who reads it and how. The data layer and the
architecture graph are one vocabulary: a component that reads from the store and the tables inside
it are one picture, and phase 5's architecture graph shares the terms.

**Four things, in the roadmap's order of priority.** The schema (tables, columns, keys) is what a
store's catalog says, introspected and cited to a schema snapshot. Lineage (`loaded_by`,
`sourced_from`, back to a `Feed`) is what ETL code and job configs say: the source of truth has a
name. Usage (`Usage`, transactional or analytical, from a query log or declared) is whom to tell
before a change. Meaning (`description`) is what an agent drafts and a person confirms:
`description_status` is `draft` until someone does, and a column with no status at all reads as a
draft, never as confirmed.

**Why a `Usage` and not a `reads_from` edge.** A read has a kind (an application reading by key, or
a report aggregating) and an evidence (seen in the log, or declared), and a team or a role reads
too. An edge carries none of that. The estate's `reads_from` stays at the store's grain.

Questions (DT1–DT6, awaiting confirmation): what a table holds and whether its meaning is confirmed
(DT1), where it comes from (DT2), who reads it and how (DT3), what is still a draft (DT4), what a
store holds (DT5), what is downstream of a feed (DT6).

**This release is the vocabulary.** The commands that fill it come next: `oto data introspect`
through an overlay connector (C1), lineage readers for dbt manifests and SQL files (C3), query-log
readers (C4), `oto data confirm` (C2), and the data project as a dependency of a concierge (C5).

This is a first draft: edit it. The sample describes the estate sample's ledger; replace it with your
store's tables as soon as you have introspected one.
