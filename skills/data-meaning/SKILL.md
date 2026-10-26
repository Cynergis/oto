---
name: data-meaning
description: >-
  What a table or a column is about, in one sentence each, for a store the data layer has
  introspected. Use when someone asks "what does this table hold", "describe the columns",
  "document the schema", "which meanings are still drafts", or after `oto data introspect`,
  `lineage` or `usage` has run and the tables carry no description. The agent drafts descriptions
  from what the catalog, the lineage and the usage say, takes the drafts through the gates, and
  hands the person the command that confirms each one. The agent never confirms.
---

# Data meaning

A store's catalog says what a table's columns are, its lineage says what loads it and from where,
its usage says who reads it and how. None of them says what the table *is about*. That sentence is
drafted by you and confirmed by a named person: `description_status` is `draft` until someone runs
`oto data confirm`, and a column with no status at all reads as a draft. The steward's list is
`oto query ask DT4`.

## Talking with the person

- **Plain language, in their words.** Say "the postings table" and "the amount column", never ids,
  class names or file names, unless they ask.
- **Technical details only when the person asks for them.** Never offer them, not even as a choice.
- **Say what you cannot tell.** A draft that guesses is worse than a node left out: when the schema,
  the lineage and the usage do not say what a column means, drop the node and name the gap.
- **The decision is theirs.** You draft; they confirm. Never run `oto data confirm` yourself, and
  never write `confirmed` into a proposal: the engine refuses both ways.

## The playbook

1. **See what has no meaning yet.** `oto query ask DT4 --project <dir>` lists every table and column
   whose meaning nobody confirmed. Then
   `oto data meaning --store datastore.<id> --at <today> --project <dir>` writes
   `proposals/meaning-<store>.json`: one node per table and column without a description, each with
   its schema line as evidence and, under `_context`, what is known of it: its type, key and
   nullability, the table it belongs to, what loads the table and from which feed, who reads it and
   how. `_context` never carries a meaning.
2. **Read what the documents say.** `build/documents/schema-<store>.md` (the catalog),
   `build/documents/lineage-<store>-*.md` (the jobs and feeds) and `build/documents/usage-<store>-*.md`
   (who reads what). A dbt model's description, a feed's description and a source file's comments
   are what the people who built it said: prefer their words.
3. **Fill one sentence per node, or drop the node.** A table: the grain (one row per what) and the
   subject. A column: what it means, the unit, the encoding, what a null means. Keep
   `description_status` as `draft`, remove `_context` and `_about`, and keep the evidence as it is.
4. **Check before the gates.** `oto data meaning --check proposals/meaning-<store>.json --project <dir>`
   refuses an empty description, a node the graph lacks, anything that is not a table or a column,
   and a status other than draft. Fix what it names.
5. **Through the gates, like any change.** `oto curate start`, `oto curate add --from
   proposals/meaning-<store>.json`, `oto curate check`, `oto curate apply --by <the person> --note
   "<what was drafted>"`, then `oto build`. DT4 now lists each draft with its sentence.
6. **Hand over the confirmation.** Show the person the drafts in their words and give them, for each
   one they agree with, the command: `oto data confirm <id> --by "<their name>" --at <date>
   --project <dir>`. A draft they want worded differently: they state it themselves,
   `oto data confirm <id> --description "<their sentence>" --by "<their name>" --at <date>`. After
   `oto build`, DT1 says the meaning is confirmed and DT4 no longer lists it.

## What the engine refuses, and what to say

- `--check` says *empty description*: the sentence was not written; write it or drop the node.
- `--check` says *description_status is confirmed*: a proposal drafts; tell the person which command
  confirms, do not change the status.
- `curate add` says *a changed fact is a supersession*: a description already in the graph was
  reworded in the proposal. A draft is reworded by the person at confirmation (`--description`),
  not by a second draft.
- `confirm` says *no description to confirm*: nothing was drafted for that node; draft it, or the
  person states it with `--description`.
- `confirm` says *already confirmed*: nothing to do.
