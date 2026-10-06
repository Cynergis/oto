---
name: build-knowledge-base
description: >-
  Take a folder of documents all the way to a served, queryable knowledge graph with OTO: ingest
  them to Markdown, survey and read them, design the vocabulary from what they say, author the
  graph document by document as proposal files, merge and check them through the curate gates,
  build every layer, verify with real queries, and serve the result over JSON-RPC. Use when a user
  says "build a knowledge base from these documents", "turn this folder into a knowledge graph",
  or an OTO project exists but has no vocabulary or no graph yet.
---

# From a pile of documents to a served graph

This is the end-to-end path. It chains the deterministic `oto` commands with the three judgment
steps only a reader can do: deciding what the documents are about, what the vocabulary should be,
and which facts each document actually asserts. The other skills are the detailed playbooks for two
of those steps; this one says when to run them and what to do in between.

    oto status        at any point, says where the project is and what comes next

The rules that never bend, from the other skills, apply here in full:

- **A class with no question behind it does not go in.**
- **Only assert what a source says.** Inference is marked as inference or left out.
- **Every fact cites its document and carries dates.**
- **A changed fact is superseded, never overwritten.**
- **Nothing reaches the live graph without `oto curate check` and a person saying yes.**

There are three confirmation gates. Do not add more; do not skip one.

---

## Phase 0 — Project and corpus

1. If there is no project, create one. Ask for a name; the slug derives from it unless the user
   wants a different one.

   ```bash
   oto ontology                                       # is one close to this domain?
   oto ontology show <name>                           # what it composes, and what it changed on the way
   oto init --project <root> --name "<name>" [--ontology <name>]
   ```

   Starting from an ontology is better than starting empty even when the fit is loose: the sample
   graph is replaced in Phase 3, and the temporal vocabulary it ships is what makes supersession work.

2. Put the documents in `<root>/inbox/` and ingest, or read them where they are:

   ```bash
   oto ingest --project <root>                     # from the project's inbox: files are claimed out of it
   oto ingest --project <root> --inbox <folder>    # from the user's folder: files are copied, originals untouched
   oto figures --project <root>                    # not optional for decks and PDFs
   ```

   A run claims the whole inbox into `processing/`, extracts each file, and writes
   `runs/<run-id>.json`. Files it could not extract go to `errors/<run-id>/` with a `.error.json`
   beside each; read those and tell the user file by file. A **blocked** file holds a credential or
   an identifier that is personal data on its own; do not pass `--allow-personal-data` on your own
   initiative. An **unsupported** file needs converting or an extractor; a legacy `.doc`, `.ppt` or `.xls` converts
   on its own when LibreOffice is on the PATH, and lands in `errors/` naming that requirement otherwise. A **new version** of a
   document the graph already cites is announced; its facts will need supersession in Phase 3.
   Figures that "need eyes" are invisible to retrieval until someone describes them; list them.

   Extracted files stay in `processing/` until Phase 5 closes the run. That is deliberate: a file
   there means "extracted, but the graph does not hold its facts yet".

3. **On a new domain, start with a seed batch.** If the folder holds more than about twenty
   documents, ingest ten to twenty representative ones first, the ones a newcomer would be handed,
   and design the vocabulary from those. The rest arrive in later runs and are authored against a
   vocabulary that already exists. Reading three hundred documents before declaring one class
   delays everything, and the extra documents mostly add instances, not new kinds of thing.

4. Survey, then read:

   ```bash
   oto survey --project <root>
   ```

   The survey is a map: each document's title, headings and size, and the capitalised phrases and
   acronyms that recur across documents. It is dumb on purpose. **Now read the documents in
   `<root>/build/documents/`, in full.** For a large corpus, read the survey first to choose the
   order, then read every document anyway. The vocabulary must use the words the material uses, and
   a summary of a summary loses exactly the specifics that make a fact checkable.

## Phase 1 — What must this answer? *(Gate 1)*

Do not list nouns. Write down the questions the knowledge base must answer, then show them.

- If the user is available, interview them as the **ontology-interview** skill describes: ten to
  twenty real questions, the ones asked under pressure.
- If the user is not available, or says "just build it", derive the questions from the documents:
  what does each document exist to tell someone? What would a reader of this corpus need to look up?
  What changes over time in it? Write them in the reader's words, and label them as yours.

**Show the question list and confirm it.** Every class in Phase 2 traces to one of these, and
every one of these ends up in `questions.json`, written so it runs (the ontology-interview skill's
Phase 4d): `oto query questions` then says, after every build, which the graph answers.

## Phase 2 — The vocabulary

Run the **ontology-interview** skill from its Phase 3 onward, with the questions from Gate 1 and the
survey's recurring phrases as the candidate nouns. Its four tests decide what becomes a class, what
stays an attribute, and what is two things. Its class-list confirmation is part of Gate 1 here:
show the classes with the question each answers, and confirm, before writing files.

Then write both files and validate:

```bash
oto ontology rationale --project <root> --strict      # every class has a recorded reason
oto ontology check --project <root>                   # zero domain and range violations
oto status --project <root>
```

`validated_by` stays empty. Report "0 of N classes confirmed by a domain expert" as a fact about a
draft, not a failure.

Acronyms and floor jargon from the survey go into `<root>/lexicon.json`, or into the `aliases` of
the entity they name, so a question using them resolves:

```json
{"entries": [
  {"term": "FNOL", "aka": ["first notice of loss", "the FNOL form"], "targets": ["procedure.fnol-intake"],
   "status": "current", "note": "acronym from the survey"}
]}
```

`targets` must be node ids the graph holds; pre-flight refuses an unknown one.

Once the vocabulary is accepted, it can seed the next project in the same domain:

```bash
oto ontology export --project <root> --name <domain-name> --summary "<one line>"
```

That writes an ontology to your ontology directory, with an invented sample graph, the rationale
carried over, and `validated_by` blanked, because confirmation in one project does not carry to
another. `oto init --ontology <domain-name>` then starts the next project from it. Offer this to
the user; do not run it unasked.

## Phase 3 — Author the graph, one proposal per document

Start a candidate:

```bash
oto curate start --project <root>
```

Then produce one proposal per document. Two ways, same rules:

- **A few documents:** draft them yourself, in reading order, following the steps below.
- **A batch:** fan the drafting out and keep the review. Hand each document to a drafting
  subagent with the instructions in [references/draft-proposal.md](references/draft-proposal.md),
  the project root and the slug, and run five to ten at a time. Each drafter reads its document in
  full, writes `proposals/<slug>.json`, dry-runs it until clean, and returns the report the
  reference asks for. Drafters never merge. You merge their proposals **in series, in reading
  order**, and you do three things they cannot: reconcile ids two drafters invented for the same
  new entity (the merge flags them as SUSPECT; pick one id and fix the other proposal), settle the
  contradictions they reported as unresolved, and keep the running list for Gate 2. A drafter's
  report that says "needs the vocabulary" pauses the batch: that is an ontology change, and it
  goes through the interview and `oto ontology check` before any proposal that depends on it.

Reading in parallel and reviewing in series is the whole trick. What enters the graph is still
one proposal at a time, through the same merge, the same check and the same confirmation.

- **For volume, or without an interactive agent**, `oto draft <slug>` (the `draft` extra) has a
  model write the first draft of a proposal to the same rules; a drafter or the reviewer then reads
  the document against it. It is a first draft, never merged unread.

- **In a pipeline**, with no person present, the same phases run under
  [references/pipeline-run.md](references/pipeline-run.md): every gate becomes a section of the
  pull request's description, and the curator's merge is the confirmation.

For each document you draft yourself:

1. Brief yourself first, then read the document in full:

   ```bash
   oto survey --project <root> --doc <document-slug>
   ```

   The brief lists the document's headings and dates, its recurring terms, and for each term the
   entity the live graph or the open candidate already holds for it. A matched term means reuse
   that id; an unmatched one means a new id derived from the label, if it is an entity at all. The
   match is a hint from names, not a verdict: read the sentence before deciding.

2. Write `<root>/proposals/<document-slug>.json`:

   ```json
   {"source_doc": "<document-slug>",
    "as_of": "<the document's own date, YYYY-MM-DD>",
    "nodes": [
      {"id": "role.claims-adjuster", "type": "Role", "label": "Claims adjuster",
       "aliases": ["adjuster"], "summary": "<what it is, in the document's words>",
       "valid_from": "<when it became true, if the document says; else omit>",
       "evidence": [{"doc": "<document-slug>", "where": "p.12", "quote": "<the sentence that says it>"}],
       "attributes": {}, "tags": []}
    ],
    "edges": [{"from": "role.claims-adjuster", "rel": "performs", "to": "procedure.fnol-intake"}]}
   ```

   Rules for a node: `id` is lowercase, dotted, derived from the label, and stable; `type` is a
   declared class; `label` and `aliases` are how the document refers to it; `summary` is in the
   document's words. The `source_doc` and `as_of` at the top apply to every node that does not set
   its own. Status and dates are defaulted by `oto curate add`; set them explicitly only when the
   document says something more precise.

   **Every fact carries evidence:** the page, section or slide, and the sentence. That is what a
   reader opens to verify an answer; `oto curate check` reports a fact without one.

   **Reuse ids across documents.** Before inventing an id, look for the entity in the candidate:
   `oto curate resolve --project <root> --term "<label>"`. A second document that mentions an existing
   entity lists it again with the same id and nothing new: the merge adds the document as a source
   and refuses a duplicate. A second document that *contradicts* an existing fact is a supersession:
   a new id with `supersedes`, plus the old id with `status: superseded`, `valid_to`,
   `superseded_by` and a `change_note` saying why, in the document's words.

3. Validate it, then merge it:

   ```bash
   oto curate add --project <root> --from <root>/proposals/<document-slug>.json --dry-run
   oto curate add --project <root> --from <root>/proposals/<document-slug>.json
   ```

   The dry run reports exactly what the merge would do and refuses what it would refuse, without
   touching the candidate. Fix the proposal until the dry run is clean; then merge.

   Read the output. A **SUSPECT** is a new id whose name matches an existing node: decide whether it
   is one entity or two, fix the proposal, and merge again. A **refused** batch names a changed
   fact: it is a supersession, or you mis-typed an id. Nothing was written; fix and retry.

4. Keep a running list of what each document asserted that the previous ones did not, and what it
   contradicted. That list is the Gate 2 report.

Do not build between documents. The candidate is a file; the merge command is the registry.

## Phase 4 — Check, and show the diff *(Gate 2)*

```bash
oto curate check --project <root>
```

Fix every **blocking** finding. Read every **contradiction**: with proposal files there should be
none, because contradictions were written as supersessions; one here means a fact was overwritten
by accident. Read the **gap** list and add the missing dates or sources. Read the **privacy** scan
and apply the judgment the curate skill describes: the role, not the name, unless the question
needs the name.

Then show the user, in this order:

1. What the graph will hold: nodes and edges by class, from the `check` header.
2. The running list from Phase 3: what each document contributed, and every supersession with its
   reason.
3. What you left out because the documents did not say it, and what you inferred, if anything.
4. The remaining gaps and privacy warnings, and what you propose for each.

**Ask before applying.** This is the only step that changes what the knowledge base believes.

## Phase 5 — Apply, build, verify

```bash
oto curate apply --project <root> --by "<you>" --note "<what the batch made answerable; what it left open>"
oto build --project <root>
oto ontology accept --project <root>
oto vet --project <root>            # every citation resolves to a document in the corpus
oto ingest complete --project <root>   # the graph holds the run: processing/ -> archive/
```

`complete` refuses while a candidate is open or the build predates the run's documents, so
"archived" keeps meaning "in the graph". After it, `processing/` is empty; anything left there is
work still owed. `oto status` says so.

Then verify with the questions from Gate 1. Run them: `oto query --project <root> questions` says
which the graph answers as required and which it cannot, with the gap; `oto query --project <root>
ask <id> NAME=<entity>` shows one answer with its rows. For what the questions do not cover, run the
query that should answer it:

```bash
oto query --project <root> resolve "<a term the question uses>"
oto query --project <root> entity "<the entity>"
oto query --project <root> neighbors "<the entity>" [<relation>]
oto query --project <root> search "<words from the question>"
oto query --project <root> stale
```

Report which questions the graph answers with a cited, dated fact, which it answers partly, and
which it cannot answer and why: a class that is missing, a document that does not say, a relation
nobody declared. That report is the honest state of the knowledge base, and it is what the user
should read before trusting an answer.

## Phase 5b — Evaluate before closing the run

Run the **evaluate** skill: a few gold questions per document, written from the document, run
against the graph, judged and recorded. A `wrong` verdict outstanding means the run is not fit to
complete; fix the fact through curate, rebuild, and re-run the questions first.

## Phase 6 — Serve *(Gate 3)*

If the OTO plugin is installed, the host already runs `oto serve` for this project and the agent has
the `kg_*` tools; confirm with one call. Otherwise ask before wiring the server into a host, and add
it to the host's MCP configuration; for Claude Code, in `.mcp.json` at the project the host opens:

```json
{"mcpServers": {"<slug>-kg": {"command": "oto", "args": ["serve", "--project", "<root>"]}}}
```

The server speaks JSON-RPC 2.0 over stdio, exposes seventeen `kg_*` tools, answers current facts by
default with `history` and `as_of` for time slices, and picks up a rebuilt database on the next call
without a restart. Confirm it with a one-shot query from the shell first; the server answers the
same way.

Start the benchmark so the next change can be measured:

```bash
oto bench start --project <root>
```

Fill its `_meta` honestly: the questions came from you or from the user, and nobody independent has
audited them yet. Put the Gate 1 questions in it, with the answers the graph gave that the user
confirmed.

---

## Afterwards

- **A new document** goes through the **curate** skill, one document at a time, with its four gates.
  The proposal-file path above still works for it: `oto ingest`, `oto curate start`, write the
  proposal, `oto curate add`, `oto curate check`, show, `oto curate apply`, `oto build`, then
  `oto ingest complete`.
- **A correction someone says aloud** goes through `oto curate assert`, as the curate skill describes.
- **A document that leaves** is found by `oto vet`, as the **vet-provenance** skill describes.
- **A reader who says an answer is wrong** is recorded with `oto feedback record` and, once the right
  answer is known, promoted into the gold set with `oto feedback promote`.

## Guardrails

- **Read every document.** The survey chooses the order; it does not replace the reading.
- **Three gates: questions and classes, the diff, the server.** Stop at each. Do not batch them.
- **Never fill `validated_by`.** Only a named person who knows the domain confirms a class.
- **Never `--force` past a gate.** A refused batch or a blocking finding is information.
- **Do not pass `--allow-personal-data`** without the user deciding, file by file.
- **One proposal per document, cited.** A node with no `source_doc` is not knowledge, and a proposal
  that mixes documents cannot be re-checked against any of them.
- **Say what the corpus does not say.** The most useful line in the Phase 5 report is often "no
  document states who owns X".
