# Running unattended in a pipeline

The author workflow runs the build-knowledge-base phases with no person present, on a branch
`oto/run-<run-id>` of a project repository, after an ingest run extracted documents into
`build/documents/`. The person comes later: a curator reads the pull request this run produces and
merges it, or comments and the agent revises. So every confirmation the interactive skill would
ask for becomes a section of one file, `runs/<run-id>.report.md`, and the pull request carries it
as its description. Nothing reaches `graph.json` on `main` except through that pull request.

## What is different from the interactive run

- **The report is the conversation.** Each gate's "show the user, then ask" becomes a section of
  `runs/<run-id>.report.md`, written in the order below. The curator's merge is the confirmation.
- **The workflow owns git.** Work in the checkout, but do not commit, do not push, and do not open
  the pull request: the workflow commits the working tree, pushes the branch and opens the pull
  request with the report as its body. Do not run `oto ingest complete`; completing the run belongs
  to the merge.
- **Stopping is allowed, and announced.** When a rule below says stop, write the report with a
  first line `BLOCKED: <why>`, the sections you completed, and what a person must decide; then end
  the turn. The workflow labels the pull request `blocked`. A blocked run with a clear reason is a
  good outcome; a run that guessed its way past a gate is not.
- **Use `oto` for every check.** Never edit `graph.json`, `changelog.jsonl` or `build/` by hand.

## Steps

1. **Read the repository's `CLAUDE.md`** and the run's manifest, `runs/<run-id>.json`: which files
   it claimed, their slugs, and which it could not extract (those are in `errors/<run-id>/`, with an
   issue already open; list them in the report, do not retry them).

2. **Gate 1 — questions and classes.** For each document, write two to five questions it should
   make answerable, from the document, before drafting. Check the vocabulary covers them:
   `oto ontology check --project .`. A document that names a kind of thing, a relation or an
   attribute nothing declares **needs the vocabulary**: that is an ontology change, and nobody is
   here to run the interview. Draft the other documents, leave that one's proposal out, and record
   under *Needs the vocabulary* what was needed, with a quote; if no document can be drafted
   without it, stop with `BLOCKED: needs the vocabulary: <what>`. Never edit
   `ontology.config.json` in a pipeline run, and never fill `validated_by`.

3. **Phase 3 — one proposal per document.** `oto curate start --project .`, then draft each
   document under [draft-proposal.md](draft-proposal.md), yourself or through drafting subagents,
   and merge the proposals in series, in reading order, with `--dry-run` first every time. A
   refused batch is information: fix the proposal. A SUSPECT you cannot settle from the documents
   goes under *Unsure*, with the id you kept. A contradiction between two documents of the run
   whose order you cannot tell is written as neither a supersession nor an overwrite: leave the
   earlier fact, list it under *Contradictions*, and let the curator decide.

4. **Gate 2 — check and diff.** `oto curate check --project .`. Fix every blocking finding. A
   contradiction here means a fact was overwritten by accident: fix the proposal and re-merge. Gaps
   stay gaps if the documents do not say; privacy findings follow the curate skill's judgment (the
   role, not the name) and are listed, never silenced: do not pass `--allow-personal-data`. Write
   the diff into the report. Then apply, with the ledger note a curator will read:

   ```bash
   oto curate apply --project . --by "oto author workflow, run <run-id>" \
     --note "<what the run made answerable; what it left open>"
   oto build --project .
   oto vet --project .
   ```

   **Never apply with `--force`.** If `apply` refuses, the report says why and the run is blocked.

5. **Phase 5 — verify the questions.** Run the Gate 1 questions with `oto query`. Record which the
   graph answers with a cited, dated fact, which partly, which not and why.

6. **Phase 5b — evaluate.** Follow the evaluate skill: `oto bench start` if the project has no
   gold set, `oto bench add` the run's questions with `authored_by_kind: model`, `oto bench run`,
   judge, and `oto feedback record` every verdict that is not right. **Never mark the gold set
   audited**: `audited_fraction` stays `0` and `audited_by` empty until a person checks questions.
   A `wrong` verdict outstanding means the run is not fit to merge: fix the fact through curate,
   rebuild, re-run; if it cannot be fixed from the documents, say so under *Needs a person*.

7. **Write `runs/<run-id>.report.md`.** It is the pull request's description, so it is for the
   curator, not for you.

## The report

Sections, in this order; "none" where empty:

1. **Recap** — the run id, the documents drafted, the documents not drafted and why (extraction
   error, needs the vocabulary), and whether the run is fit to merge in one sentence.
2. **What the graph will hold** — nodes and edges by class, from the `check` header, and the
   ledger note used for `apply`.
3. **What each document contributed** — the running list from Phase 3, and every supersession
   with its reason, in the document's words.
4. **Now answerable** — the Gate 1 questions the graph answers, with the citing fact; then the
   ones it answers partly; then the ones it cannot, and why.
5. **Evaluation** — the bench score line, the verdicts recorded, and the provenance line stating
   the questions were model-authored and nobody has audited them.
6. **Needs a person** — contradictions left unresolved, SUSPECTs kept, privacy findings, gaps the
   documents cannot fill, and anything under *Needs the vocabulary*. Each with what you propose.
7. **Not asserted** — what the documents are silent on that a reader of these facts might assume.

## Rules, none of which bend

- `runs/<run-id>.report.md` exists when you finish, whatever happened; its first line is
  `BLOCKED: <why>` if you stopped.
- do not commit, do not push, do not open or merge a pull request, do not run `oto ingest complete`.
- Never apply with `--force`; never pass `--allow-personal-data`; never fill `validated_by`.
- Never mark the gold set audited.
- A run that needs the vocabulary waits for a person; it does not invent a class.
- Say what the corpus does not say. The most useful line of the report is often "no document
  states who owns X".
