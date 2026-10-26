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

**Filling it.** `oto data introspect [--path <store>] --store datastore.<id> --at <date>` reads a
store's catalog through an overlay connector (SQLite, Postgres or BigQuery) into a schema document and a proposal
in this vocabulary, every fact quoting its line, through the gates (C1). The store is a `DataStore`
the estate declares first. `oto data lineage --dbt target/manifest.json | --sql <dir|file> --store
datastore.<id> --at <date>` reads what the ETL already says into a lineage document and a proposal
of `LoadJob` and `Feed` nodes with `loaded_by` and `sourced_from` edges to the tables the graph holds
(C3): a dbt model, seed or snapshot is a job (tool `dbt`, schedule from `meta.schedule`), an
ephemeral model collapses to what it reads, a dbt source is a feed whose kind its `loader` suggests;
a SQL file is one job whose INSERT, MERGE, CREATE ... AS, COPY and LOAD say what it writes and whose
FROM and JOIN say what it reads, with `-- schedule:` and `-- tool:` comments for the rest. A job
that loads a table the graph lacks is a gap the command reports, never a table it invents: the
catalog says what exists, lineage says how it is loaded. `oto data usage --log <file> | --connector
postgres|bigquery [--reader principal=node.id ...] --store datastore.<id> --at <date>` reads the
store's query log (pg_stat_statements with its role, BigQuery's job history with its user, or a
file a person exported) into a usage document and a proposal of `Usage` nodes, one per principal
and table, `use_of` the table and `used_by` the component, team or role the principal is mapped to
(`--reader`, or `usage.readers` in project.config.json; an unmapped principal is a gap, never a
reader invented) (C4). The kind is one deterministic rule, weighted by calls: a write or a read by
key is transactional, an aggregate, grouping, window, DISTINCT, scan or range is analytical, and a
tie is transactional, the reader you must tell before a change. The statement text is hashed into
the document and never kept; counts are the document's, not the fact's, so the same log read twice
is one set of facts and a kind that flipped is a supersession the merge refuses. Meaning is the
data-meaning skill's: `oto data meaning --store datastore.<id> --at <date>` lists every table and
column without a description as a skeleton proposal, each with its schema line as evidence and what
the catalog, lineage and usage say about it; the skill fills one sentence per node, `oto data
meaning --check` refuses an empty description or a status other than draft, and the drafts go
through the gates (C2). A named person confirms with `oto data confirm <id> --by <name> --at
<date> [--description "..."]`: an assertion by them, `description_status` moved to `confirmed`
under the gates, which allow the move because the attribute is marked a `decision` and the node
now cites the assertion; no proposal can confirm. A concierge that depends on this graph routes a
question about a table to it (C5): `oto graph describe --reach <url>` here, `oto graph depend --on`
there.

This is a first draft: edit it. The sample describes the estate sample's ledger; replace it with your
store's tables as soon as you have introspected one.
