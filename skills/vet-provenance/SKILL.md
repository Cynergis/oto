---
name: vet-provenance
description: >-
  Audit an OTO knowledge graph so every fact traces to a document the corpus actually holds. Finds
  citations to documents that have left (de-scoped, renamed, replaced), separates a stale citation
  from a fact about to be lost, and produces a candidate graph that goes through the normal curate
  gates. Use when the document set has changed and you need to answer "is anything in here sourced
  to a file nobody can open?"
---

# Vetting provenance

A graph outlives its documents. A deck gets de-scoped, a draft is replaced, a file is renamed, and
the facts stay behind still citing it. The graph keeps answering, and every answer grounded in a
missing document is unfalsifiable. This pass finds those and fixes what can be fixed.

Run on a model with judgment. The mechanical part is one command. The decisions are not mechanical,
and two of them can destroy real knowledge.

## 1. Audit

```
oto vet --project <root>
```

Reports the source tags the corpus does not hold, how many facts cite each, and which facts would be
at risk. Nothing is written.

## 2. Sort the aliases from the phantoms

**This is the step that matters most.** A tag that matches no filename is usually an alias for a
document that is present: `kickoff` for the kick-off document, a short name for a long filename.
Treating an alias as a phantom deletes knowledge that was never missing.

Read the dead tags against the actual filenames in the corpus. Ask the user about any you cannot
resolve, one at a time, naming the facts that depend on it. Then whitelist the confirmed aliases:

```
oto vet --project <root> --vetted kickoff,q1-review
```

Repeat until every remaining tag is genuinely a document that has left.

Curation markers (`manual-*`, `assertion-*`, and similar) are reported separately and are never
treated as dead. Do not whitelist them; they are already handled.

## 3. Decide what happens to the facts at risk

The audit splits them:

- **Stale citation, live fact.** The node cites at least one document that is still there. The dead
  citation is stripped and the fact stands. No decision needed.
- **Re-sourced.** A neighbouring entity cites a surviving document, so that document becomes the
  citation. **This is an inference and it can be wrong.** Adjacency is not attestation: that a
  document mentions a neighbour does not prove it mentions this fact. Every re-sourced node is
  marked `provenance: inferred` with a note naming what it lost, so the guess stays visible. Read
  the list and object to any that look wrong.
- **Orphaned.** Nothing attests it. These are left completely untouched, including their dead
  citation, because a citation you can see names the document to go and find. Decide per node:
  remove it, give it a fallback source, or leave it and go find the document.
- **Removed.** Only nodes you name. `oto vet` never removes anything on its own.

Removing a well-sourced node is not a provenance fix, and `oto vet` refuses it. Use `oto curate`.

## 4. Produce a candidate

```
oto vet --project <root> --vetted <aliases> --remove <ids> --fallback <slug> --apply
```

Writes `graph.candidate.json`. Nothing is live.

## 5. Review and apply through the normal gates

```
oto curate check --project <root>     # what changes, and whether it contradicts anything
oto curate apply --project <root>     # promote, keeping the previous graph
oto build --project <root>            # recompile every layer
oto vet   --project <root>            # expect only the orphans you chose to keep
```

`oto curate check` reports provenance changes on their own line: the facts are unchanged and who
attests them is not. Read that count and make sure it matches what you expected.

## Guardrails

- **Never run this against an empty corpus.** Every citation would look dead and the audit would
  tell you to delete everything. `oto vet` refuses, but understand why.
- **Surface before removing.** Present the footprint and the edges that would dangle, and get
  confirmation. In the project this was ported from, applying the removal rule by default gutted an
  org chart.
- **Losing a fact is worse than carrying a stale citation.** The citation can be fixed once the
  document is found. The fact has to be re-derived from a document that may be gone.
- **Re-vet, do not re-author.** To bring removed content back, put its source document in the inbox
  and re-ingest. Do not hand-restore nodes.
- **A contradiction is not a provenance problem.** This removes unsourced facts, never contested
  ones. Contradictions are resolved by supersession through `oto curate`.
