# Questions that run and shapes that gate: executable competency questions and SHACL

Status: decided 2026-10-06 with Chiheb (see Decisions). All five steps done on the `semantic-layer` branch (engine 0.8.0); waiting for review. Step 3 also
wrote the SHACL rendering and its reading (planned for step 4), because the Turtle round-trip
tests need the shape keys to survive the export; the SHACL lives in the ontology Turtle itself
rather than in a separate `shapes.ttl`, so a vocabulary stays one file that round-trips. Follows
[semantic-layer.md](semantic-layer.md), which it builds on. Written from a comparison with the
report ontology, whose `questions/report_cq.yaml` (21 questions, each with a SPARQL answer, a gaps
query and the terms it covers) and `ontology/report-shapes.ttl` (28 node shapes, each violation
message naming the question it would leave unanswerable) are the model.

## The gap, measured

OTO already asks every class and relation what it exists to answer: `ontology.rationale.json`
carries a `question` per term, the interview writes it, `oto ontology check` refuses a term without
one. But nothing ever runs the question. Whether the graph can answer it is known only when a
person types it into `oto query` and reads the result. Built from `oto init --ontology auto-claims`:

| Where | What it does | Why it matters |
|---|---|---|
| `ontology.rationale.json` | `Coverage.question: "Which coverage is this claim being paid under, and what limit applies?"` | Prose. Nobody can run it, so nobody knows whether the sample graph, or any project graph, answers it |
| `oto ontology check` | checks the vocabulary's shape, hierarchy, schemes and rationale | It cannot say "the sample graph answers 11 of 14 questions"; an ontology whose own sample fails its own questions passes |
| `oto curate check` | blocking findings: unknown class, undeclared relation, domain or range mismatch, missing evidence; gaps: missing dates or sources | The constraints a domain needs are not expressible: "a Payment points at exactly one Coverage", "a Claim in state `closed` has a Decision", "a Component has an owner" |
| `rules.json`, kind `policy` | `{"not_edge": ["d", "documented_in", "*"]}` flags a decision without a document, with a `why` | The right idea, half-used: a policy can say "must have", not "at most one", not "the value must be a concept of X", and it is never exported, so no SHACL tool sees it |
| `ontology/<slug>.ttl` | the terms, with labels, definitions and hierarchy | No `sh:NodeShape`: a reader who validates with SHACL has nothing to validate against |
| `oto bench` | gold questions written from documents, model-authored, graded by citation | Evaluation of answers, not of the vocabulary: a bench question asks what a document says; a competency question asks what the ontology must be able to say about anything |

The report ontology closes both gaps with SPARQL and SHACL, which OTO's compile path cannot run:
the engine is stdlib-only and must stay so. So the design below writes each question and each
constraint once, in OTO's own pattern language, runs it in the engine over either store, and
exports it as SPARQL and SHACL for everyone else, with a test that the two executions agree.

## Goals

1. A **competency question is a file entry that runs**: a question in words, who asks it, why it
   exists, who confirmed it, and a query the engine executes over the store, with a gate (must
   return rows, must return none, or informational) and an optional **gaps** query that says why
   an empty answer is empty.
2. **An ontology ships its questions**, and `oto ontology check` runs them against the sample
   graph: an ontology whose sample cannot answer its own questions is not usable. Every term is
   cited by at least one question, as the rationale already demands in prose.
3. **A project runs its questions as a gate**: `oto curate check` reports the required questions
   the candidate would leave unanswered, and `kg_ask` answers one on demand with the rows and the
   gaps, so an agent asks "can this graph answer X" instead of guessing.
4. **Constraints are declared once and gate the candidate**: cardinality on relations and
   attributes, required attributes per class, concept-valued attributes checked against their
   scheme, and the `policy` rules that already exist; `oto curate check` evaluates them in the
   engine, with each violation naming the question it would leave unanswerable.
5. **The export carries both**: `shapes.ttl` beside the ontology Turtle (SHACL generated from the
   declarations and the policy rules) and `questions.yaml` with the SPARQL translation of each
   question, so a reader with rdflib and pyshacl checks the same things OTO checks.
6. **Equivalence is proven**: with the `rdf` extra installed, a test runs every shipped question
   both ways (engine over the store, SPARQL over `graph.ttl`) and every shape both ways (engine
   over the candidate, pyshacl over `graph.ttl` + `shapes.ttl`) and requires the same rows and
   the same violations. The SPARQL and SHACL are not a second truth; they are a rendering of the
   first one, and the test keeps the rendering honest.

Not goals: a SPARQL endpoint; running arbitrary SPARQL in the engine; SHACL-SPARQL constraints
(`sh:sparql`) in the engine beyond what the pattern language can say; OWL reasoning; a question
language that competes with `kg_*` for ad-hoc queries.

## The question language

One form, in `questions.json` beside the ontology (shipped) or beside `graph.json` (a project's
own), the pattern language of `rules.json` with a `select`:

```json
{"_about": "What this ontology exists to answer. Each question runs; a gate decides what an empty answer means.",
 "questions": {
   "CQ3": {
     "who": "claims handler",
     "question": "Which coverage is claim $CLAIM being paid under, and what limit applies?",
     "why": "A payment charged to the wrong coverage is the costliest error in handling.",
     "validated_by": "",
     "params": {"CLAIM": {"type": "Claim"}},
     "ask": {"when": [{"edge": ["$CLAIM", "paid_under", "c"]}, {"node": "c", "type": "Coverage"}],
             "select": ["c", "c.limit", "c.deductible"]},
     "gate": "non_empty",
     "gaps": {"when": [{"node": "$CLAIM", "type": "Claim"}, {"not_edge": ["$CLAIM", "paid_under", "*"]}],
              "say": "the claim names no coverage"},
     "terms": ["Coverage", "paid_under", "Coverage.limit"]
   }
 }}
```

- `ask.when` is a rule's `when`: `node`, `edge`, `not_edge`, `not_node`, `where` conditions, dates
  against `$today`. `select` names variables, or `var.attribute`, or `var.type`, or `var.label`.
  Hierarchy is honoured (`type: Asset` matches a Component), as in rules.
- `params` are the question's holes: a `$NAME` bound to an entity id, resolved through the same
  resolver `kg_resolve` uses, so a person can pass a label. A question with no params asks about the
  whole graph (the catalogue questions).
- `gate`: `non_empty` (the graph must answer; empty is a finding), `empty` (nothing must match; a
  row is a finding, the shape of a policy rule), `any` (informational). The gate applies to a
  question only when every param is bound or the question has none; with a free param the
  check runs it over every node of the param's type and reports per node.
- `gaps`: a second pattern that runs when the answer is empty and says why, in words. The report
  ontology's lesson: a silent empty answer misleads, a gap does not.
- `terms`: the vocabulary terms this question covers beyond those its patterns mention. `oto
  ontology check` refuses a class, relation or attribute no question covers, replacing the
  prose-only check in the rationale; the rationale `question` stays as the sentence, the
  `questions.json` entry is the executable form, and the check links them by name.

The SPARQL rendering is mechanical: `node` → `?c a :Coverage` (with the subclass closure expanded
to a `VALUES` block), `edge` → a triple, `not_edge` → `FILTER NOT EXISTS`, `where` → `FILTER`,
`select` → the projection, `$today` → a literal at render time. `oto ontology export` and `oto build`
write it to `questions.yaml` in the shape of `report_cq.yaml` (prefixes, question, answer, gaps),
because that is a format people already run with rdflib.

## Shapes

Three sources, one evaluator, one export:

1. **Declared cardinality**, new keys in the vocabulary object form: on a relation `min` and `max`
   (per subject; `"max": 1` is "a Payment points at at most one Coverage"); on an attribute
   `required: true`; on a class `requires: ["owner", "part_of"]` naming attributes or relations
   every instance must carry. A `scheme:`-typed attribute already implies `sh:in` the scheme's
   concepts. These are breaking changes in the lock when tightened, additive when loosened.
2. **Policy rules** (`rules.json`, kind `policy`), as they are, with one addition: `answers:
   "CQ3"` so a violation names the question it protects, which is what the report ontology's
   `sh:message` carries.
3. **Questions with `gate: empty`**, which are policy rules spelled as questions.

The evaluator is the rules matcher, already honouring hierarchy and `intended` facts; `oto curate
check` runs it on the candidate and reports violations as blocking (cardinality, required, scheme)
or warn (a policy rule's `severity`). The export writes `shapes.ttl`: a `sh:NodeShape` per class
with `sh:property` for each cardinality, required and scheme constraint, `sh:message` naming the
question, and a `sh:sparql` constraint for each policy rule whose pattern needs one (`not_edge`).
The engine never reads SHACL; it writes it.

## Reading

- `oto ontology check` prints, after the vocabulary checks, "questions: 14, answered by the sample:
  14" or the list of those the sample cannot answer, with the gaps; then the terms no question covers.
- `oto curate check` gains two sections: **unanswerable** (required questions with a bound or
  no param that return nothing on the candidate, each with its gap) and **shape violations** (with
  the question each protects), both blocking.
- `kg_ask <id> [params]` returns `{question, who, status, rows, gaps}`; `kg_questions` lists the
  questions and, for each, whether the live graph answers it (the ontology's health, as the
  query-knowledge skill should open with). `oto query ask` is the CLI form; `/api/ask` the HTTP one.
- `ontology.md` lists the questions under each class it covers, with who asks and who confirmed.
- The ontology-interview skill writes the executable form alongside the prose one: the interview
  already asks "what does this exist to answer"; it now also asks "show me on the sample graph",
  and the answer is the pattern.

## Order of work

1. **The language and the runner** (`oto/reason/questions.py`): parse `questions.json`, bind
   params, run `ask` and `gaps` through the matcher over a store, apply the gate. CLI `oto query
   ask`, `kg_ask`, `kg_questions`, HTTP routes. Tests on auto-claims' sample. *Stop for review.*
2. **Questions in the ontology unit**: `questions.json` carried by `carries`, composed through
   `extends` (a question keeps the namespace of the ontology that declared it), locked, diffed
   (a changed `ask` is a breaking change; a changed `why` cosmetic), checked against the sample by
   `oto ontology check`, term coverage enforced. Write the questions for the shipped ontologies,
   from their rationale. The registry packs are republished. *Stop for review.*
3. **Shapes**: the three vocabulary keys, the evaluator in `curate check`, `answers` on policy
   rules, lock kinds. Shipped ontologies get the constraints their rationale implies.
4. **Export**: `shapes.ttl`, `questions.yaml`, `ontology.md` sections; the `rdf` extra equivalence
   test (rdflib for the questions, pyshacl for the shapes, both dev-only).
5. **Skills and docs**: ontology-interview, build-knowledge-base Gate 1 ("write the questions,
   run them"), query-knowledge (open with `kg_questions`), curate, ARCHITECTURE, README,
   CHANGELOG, 0.8.0.

Then the next plan: port the report ontology as an OTO pack (its classes, schemes, questions and
shapes through `oto ontology import`), which is the acceptance test of all of this.

## Decisions

Taken with Chiheb on 2026-10-06: the pattern language is the source of truth (1), and the recommended answer to each of 2 to 6.

1. **One language, rendered to SPARQL; or SPARQL as the source, run by rdflib?** Recommended: the
   pattern language is the source, because the engine must answer `kg_ask` from Neo4j and SQLite
   without rdflib, and because the interview's agent writes patterns it can already write for rules.
   SPARQL as source would make the `rdf` extra mandatory for any gate. The cost: a question SPARQL
   can express and the pattern language cannot (aggregation, paths of unknown length, string
   functions) is not writable; the plan accepts that and lists what is not expressible in the check.
2. **Where a project's own questions live**: `questions.json` beside `graph.json` (recommended,
   symmetrical with `rules.json`), or inside `ontology.config.json`.
3. **Term coverage as a hard check** (an ontology with a term no question cites fails `oto
   ontology check`, as `kgctl terms` does), or a warning. Recommended: hard, for the shipped
   ontologies and for `oto ontology accept`; the interview makes it cheap to satisfy.
4. **`curate check` blocking on unanswerable required questions** from day one, or warn first.
   Recommended: blocking; the questions are the ontology's contract and nothing has used it yet.
5. **Cardinality keys** named `min`/`max`/`required`/`requires` as above, or SHACL's names
   (`minCount`/`maxCount`). Recommended: OTO's words, since the export translates.
6. **Does `bench` learn anything from this?** Recommended: no change now; a competency question
   confirmed by a person could later be promoted into the gold set, but that is a different
   artefact with a different author, and mixing them would make `audited_fraction` lie.

## Not done here

- SHACL read in: `oto ontology import` of a `shapes.ttl` into cardinality keys and policy rules
  (the report ontology port will want the simple part of it; the `sh:sparql` part cannot be read).
- SPARQL read in for questions, for the same reason.
- Paths of unknown length (`part_of+`) in the pattern language: a derivation rule gives the
  closure today, and that stays the answer until a question needs more.
