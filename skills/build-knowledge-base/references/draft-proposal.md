# Drafting one proposal

You are drafting the facts one document asserts, for a knowledge graph a person will review. You
receive the project root and the document's slug. You return a proposal file and a short report.
You do not decide what enters the graph; the reviewer merges, in series, in reading order. Be
faithful to the document and easy to check.

## Steps

1. Brief yourself, then read the document in full:

   ```bash
   oto survey --project <root> --doc <slug>
   cat <root>/build/documents/<slug>.md
   ```

   The brief lists the document's headings and dates, its recurring terms, and for each term the
   entity id the live graph or the open candidate already holds. A matched term is a hint from
   names, not a verdict: read the sentence before deciding. The brief also names the classes,
   relations and attributes the vocabulary declares; those are the only ones you may use.

2. Write `<root>/proposals/<slug>.json`:

   ```json
   {"source_doc": "<slug>",
    "as_of": "<the document's own date, YYYY-MM-DD>",
    "nodes": [
      {"id": "role.claims-adjuster", "type": "Role", "label": "Claims adjuster",
       "aliases": ["adjuster"], "summary": "<what it is, in the document's words>",
       "evidence": [{"doc": "<slug>", "where": "p.12", "quote": "<the sentence that says it>"}],
       "attributes": {}, "tags": []}
    ],
    "edges": [{"from": "role.claims-adjuster", "rel": "performs", "to": "procedure.fnol-intake"}]}
   ```

3. Dry-run it until it is clean, and never merge:

   ```bash
   oto curate add --project <root> --from <root>/proposals/<slug>.json --dry-run
   ```

   The dry run says exactly what the merge would do and refuses what it would refuse, without
   touching the candidate. A **SUSPECT** is a new id whose name matches an existing node: if it is
   the same entity, reuse the existing id; if you cannot tell, keep your id and say so in the
   report. A **refused** line names a changed fact or a mis-typed id: fix it. Repeat until the dry
   run reports nothing refused.

4. Return the report (below). Do not run `oto curate add` without `--dry-run`, `oto curate apply`,
   `oto build`, or any `oto ontology` command. Never edit `graph.json`, the candidate, or another
   document's proposal.

## Rules, none of which bend

1. **Only what the document states.** If it implies something but does not state it, leave it
   out, or include it with `"source_type": "inference"` on the node and a line under
   *Inferences* in the report. A confident wrong fact is worse than a missing one.
2. **A thing with identity, dates or relationships is a node.** A value about a thing is an
   attribute on its node, using the attribute names and types the vocabulary declares for that
   class. Prefer attributes; they are cheaper.
3. **Every `type` is a declared class.** If the document names a kind of thing no class covers, do
   not invent a class and do not force it into the wrong one: leave the fact out and list it under
   *Needs the vocabulary*. The same for a relation nobody declared, and for an attribute the class
   does not declare.
4. **Reuse ids.** A term the brief matched is listed again with the existing id and nothing new
   but `evidence` and any alias the document adds; do not restate its label or summary. Before
   inventing an id, look once more: `oto curate resolve --project <root> --term "<label>"`. A new
   entity gets a new id: lowercase, dotted, `<class>.<label-slug>`, stable, never a number.
5. **A contradiction is a supersession, or it is reported.** When the document contradicts a fact
   the graph holds and is newer, write both sides: the old id with `"status": "superseded"`,
   `valid_to` and `superseded_by`; a new id with `supersedes`, its own `valid_from`, a
   `change_note` in the document's words, and evidence. When you cannot tell which is newer, do
   not supersede; list it under *Contradictions* and leave the graph's fact alone.
6. **Every node carries evidence:** `{"doc": <slug>, "where": <page, section or slide>, "quote":
   <the sentence that says it>}`. That is what a reader opens to verify an answer; a fact without
   one is reported by `oto curate check` and will not pass the gate. Every edge uses a declared
   relation whose domain and range fit the two nodes' classes. Dates are `YYYY-MM-DD` or absent,
   never guessed; `as_of` is the document's own date, and the report says where it came from.
7. **The report is for the reviewer.** Say what the document does not say that a reader might
   assume, and anything you were unsure about. Be generous; that is what the review is for.

## The report

Return this, in this order, with "none" where a section is empty:

- **Document date:** the `as_of` you set and what in the document gave it.
- **Reused ids:** the existing ids this proposal lists again, one per line.
- **New entities:** the ids you invented, each with its class.
- **Supersessions:** each old id → new id, with the change note.
- **Contradictions:** facts the graph holds that this document disputes, where you could not tell
  which is newer.
- **Needs the vocabulary:** kinds of thing, relations or attributes the document uses that nothing
  declares, with one quote each. A non-empty section pauses the batch: that is an ontology change
  and it goes through the interview before any proposal that depends on it.
- **Inferences:** what you included with `source_type: inference`, and why.
- **Not asserted:** what the document is silent on that a reader of these facts might assume
  (who owns X, since when, whether Y still applies).
- **Unsure:** anything else the reviewer should read twice, including every SUSPECT you kept.
- **Dry run:** the last `--dry-run` summary line, verbatim.
