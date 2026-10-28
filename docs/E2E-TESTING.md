# Testing OTO end to end

Sixteen stages, in the order a real project goes through them. Each one names what it exercises,
the commands, and what "pass" looks like, so you can tell a bug from a misunderstanding. Stages 1
to 10 run on one machine with no account but Docker. Stages 11 to 13 need a GitHub organisation,
an Anthropic API key and a Neo4j host; stage 16 needs a secret on the engine repository.

Throughout, `oto` means the engine run from its repository, which is public: `uvx` and `pip`
clone it with no credential.

```bash
alias oto='uvx --from "oto-kg[all] @ git+https://github.com/Cynergis/oto" oto'   # every extra
# or only what a stage needs: extras combine inside the brackets
alias oto='uvx --from "oto-kg[intake,neo4j] @ git+https://github.com/Cynergis/oto" oto'
```

## How to read this document

The sections follow the order the features were built, and [ADR-0006](adr/0006-the-core-and-the-packs.md)
draws one line through them. The **core**, the knowledge graph with its tools and its deploy, is
sections 1 to 17, 19, 20, 23 to 27 and 33: install, a project, documents in, the vocabulary, rules,
authoring under the gates, time, query and serve, evaluation, Neo4j, repository mode, the query
repository, specs and decisions, an ontology of your own, tools, deploy, audit and tracing, graphs
that know each other, the engine's own CI, the ontology explorer, and the pack seams. Drive these first: they are
the product, and they need no pack. The **packs**, each an ontology with the tools that work on it,
are sections 18 (work and communication), 21 (data), 22 (architecture, with CALM as the first
framework adapter), 28 to 30 and 32 (policy, the snapshot and guards, the generated IAM) and 31
(the inbox and reminders). Each is optional: a project that does not compose the pack never sees
its commands or its build stages.

## What needs your accounts

| You provide | Used in stages | Where it goes |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) on each machine | all | nothing else has to be installed |
| Docker, for a local Neo4j 5 | 10 | `docker run ... neo4j:5` |
| LibreOffice, only for `.doc`, `.ppt`, `.xls` | 3 | found on the PATH as `soffice` |
| A token that can read the engine repository, only if you install from a private fork of it | 11, 12 | repository secret `OTO_ENGINE_TOKEN` |
| An Anthropic API key | 6 (`oto draft`), 11, 12, 14 | `ANTHROPIC_API_KEY` in your shell; the repository secret of the same name |
| A GitHub organisation where you can create repositories, secrets and variables | 11, 12, 13, 16 | the knowledge repository, the query repository, the engine's CI |
| A Neo4j reachable from GitHub Actions (a public endpoint, or a self-hosted runner beside it) | 11 | repository variable `NEO4J_URI`, secret `NEO4J_PASSWORD` |
| A token that can write to the query repository | 11, 13 | repository secret `OTO_QUERY_REPO_TOKEN` |
| Your deny terms for the publishability gate | 16 | `OTO_DENY_TERMS` in your shell, and as a secret on the engine repository |

Secrets live in the environment or in GitHub secrets, never in a file in either repository.

---

## 1. The engine installs from its repository

Exercises: packaging without PyPI, `uvx`, the greenfield self-test.

```bash
oto version
oto verify            # init, author, build, query on a throwaway domain
oto ontology
```

Pass when `version` prints, `verify` ends with `OTO VERIFY: PASS`, and four starter vocabularies
are listed (auto-claims, organization-process, professional-services, software-architecture).

## 2. A project from an ontology, built and queried

Exercises: `init`, the build transaction, the six stages, the query engine on the local store.

```bash
oto init --name "Acme Platform" --ontology software-architecture --project acme
oto status --project acme
cat acme/GUIDE.md                        # the ontology's guide to reading this domain's graph
oto build --project acme
oto query --project acme entity "Payments platform"
oto query --project acme neighbors "Payments platform"
oto query --project acme overview
oto query --project acme explain datastore.ledger
oto query --project acme policy
oto clean --project acme && oto build --project acme
```

Pass when the slug is derived from the name (`acme-platform`), `status` names the next step,
`GUIDE.md` is installed from the ontology, and in Claude Code the **concierge** skill quotes the
status, explains the station and names the build-knowledge-base skill for the next step,
the build prints the stages `knowledge`, `rules`, `ontology`, `semantic`, `sqlite` and skips
`neo4j` with a note, the entity card shows `status`, `as_of`, `valid_from` and `source_doc`,
`overview` shows counts by class and the ledger, `explain` shows a derived edge with its rule and
premises, `policy` lists the `decision-is-documented` finding, and a build after `clean` is
identical.

## 3. Your documents, ingested

Exercises: every extractor, the inbox state machine, privacy blocking, figures, the corpus survey.

Put five to ten real documents of mixed formats in `acme/inbox/`: Word, PowerPoint, PDF, Excel, an
HTML page, an `.mht` archive, a `.doc` if LibreOffice is installed, and one deliberately
unsupported file. Include a deck with diagrams and one document containing a payment card number.

```bash
oto ingest --project acme
oto ingest runs --project acme
oto figures --project acme
oto survey --project acme
oto survey --project acme --doc <slug>
oto status --project acme
```

Pass when `inbox/` is empty, each success sits in `processing/` with its Markdown at
`build/documents/<slug>.md` (headings, tables, images as `assets/image-NN.*` with a `[DIAGRAM]`
placeholder), each failure sits in `errors/<run>/` beside a `.error.json` whose reason you can act
on, the card-number document is `blocked` and its number appears nowhere, `runs/<id>.json` records
a sha256 per file, `figures` lists the undescribed diagrams, `survey` lists the recurring terms and
`--doc` says which already resolve to entities, and `status` reports the open run.

## 4. The vocabulary, four ways

Exercises: ontologies merged, the interview, import from a file, the lock, diff, impact and
rationale.

Open the project in Claude Code with the plugin (`/plugin marketplace add Cynergis/oto` then
`/plugin install oto@oto`, or `claude --plugin-dir <a clone of the engine>`). Try each way at
least once:

1. Two ontologies merged: `oto init --ontology software-architecture,organization-process ...`
2. From the documents: ask for the **ontology-interview** skill after stage 3; it reads the
   survey, asks its questions, and writes `ontology.config.json` and `ontology.rationale.json`.
3. From a file you own: `oto ontology import --project acme --file ontology.ttl` (any OWL, RDFS or SKOS in any RDF syntax, with `oto-kg[rdf]`; or a `.csv` or `.json` vocabulary).
4. By interview alone, with no documents.

Then:

```bash
oto ontology check --project acme --strict
oto ontology rationale --project acme --strict
oto ontology accept --project acme
# rename a class in ontology.config.json, then:
oto ontology check --project acme
oto ontology widen --project acme
```

Pass when `check` reports conformance and, after the rename, a breaking change with the number of
nodes it touches; `rationale --strict` fails until every class has a reason and a named person;
`accept` writes `ontology.lock.json`; a typed attribute declared under `attributes` (an enum, a
date, a number) is enforced later by `curate check`; and `widen` proposes honest domain and range
widenings rather than silently accepting a violation.

## 5. Rules and derived facts

Exercises: rule validation, the fixpoint, derived marks, explanation chains, policy findings.

Edit `rules.json` (the ontology ships three of its own and inherits `intended-fact-overdue` from the core). Add a `derive` rule and a `policy` rule of your own,
and one deliberately wrong rule (a negation inside a `derive`).

```bash
oto rules check --project acme
oto rules explain risk-reaches-system --project acme   # its reason, its pattern, what it derived
oto rules diff --project acme
oto rules accept --project acme
oto build --project acme
oto query --project acme explain <an entity your rule touches>
oto query --project acme policy
```

Pass when `check` refuses the wrong rule with a reason and dry-runs the others with counts,
`explain` prints the rule's `why`, its pattern in words and what it derived on the last build,
`diff` shows what changed against the accepted set, derived edges appear in cards as
`[derived by <rule>]`, `explain` walks each premise down to a document, `policy` lists findings
with blocking ones first, and superseding a premise and rebuilding makes the derived fact go.

## 6. Authoring, under four gates

Exercises: proposals, the candidate, dry-run merge, the check report, apply, the ledger, run
completion, and optionally the model drafter.

In Claude Code, ask to **build a knowledge base from the documents in acme**; the skill runs the
commands below and stops at the gates. To do it by hand, write one `proposals/<slug>.json` per
document, then:

```bash
oto curate start --project acme
oto curate add --project acme --from proposals/<slug>.json --dry-run
oto curate add --project acme --from proposals/<slug>.json
oto curate check --project acme
oto curate diff --project acme
oto curate apply --project acme --by "<you>" --note "<what is now answerable>"
oto build --project acme
oto ingest complete --project acme
oto curate log --project acme
```

With an API key, let the model draft one proposal:

```bash
export ANTHROPIC_API_KEY=...
uvx --from "oto-kg[draft] @ git+https://github.com/Cynergis/oto" oto draft --project acme <slug>
```

Pass when the dry run reports what would be added, what repeats an existing fact and what is
refused; `check` sorts problems into blocking, contradiction, gap and privacy, and a fact without
an evidence locator is a gap; `apply` refuses with blocking problems and appends to
`changelog.jsonl` otherwise; `ingest complete` refuses while a candidate is open or the build is
older than the document, and moves the files to `archive/` when it can; `status` says up to date;
and the drafted proposal records which model wrote it and reads like the dry-run report.

## 7. Knowledge changes over time

Exercises: supersession, history and as-of queries, re-attestation, undo, spoken corrections,
provenance vetting.

- **Supersede a fact.** In a candidate, mark the old node `superseded` with `valid_to` and
  `superseded_by`, add the new node with `supersedes` and a `change_note`, re-point the edges.
  Then `entity <old> `, `entity <old> --history`, `entity <old> --as-of <a date before>`, `stale`.
- **Overwrite a value without a record**, and run `oto curate check`.
- **A new version of a document.** Drop a revised copy of an archived file in `inbox/` and run
  `oto ingest`, then `oto curate check`, then `oto ingest complete`.
- **Undo.** `oto curate undo --project acme`.
- **A correction someone said.** `oto capture --project acme --title "<topic>" --by "<who, role>"
  --at <date> --statement "<their words>"`, then the pipeline from stage 6. Or, locally,
  `oto curate assert --text ... --by ... --at ...` and a fact citing `assertion:a-0001`.
- **A document that disappears.** Delete one file under `build/documents/` and run
  `oto vet --project acme`, then `oto vet --project acme --apply`.

Pass when the card of a superseded id says so and shows the current fact, `--history` lists the
predecessor with its validity window, `--as-of` returns the old fact, `check` reports the
unrecorded overwrite as a contradiction, the new version is announced and every fact citing the
old one is listed as pending re-attestation until the proposal lists it again, `complete` refuses
until then, `undo` restores the previous graph and the ledger says so, the captured statement
becomes a dated source document whose facts name the speaker, a fact citing an assertion not in
the log is blocking, and `vet` lists every fact citing the missing document and writes a candidate
only with `--apply`.

## 8. Query and serve

Exercises: the MCP server and its twelve tools, the CLI, the lexicon, global questions, theme
notes, hot reload.

In Claude Code the plugin registers `oto serve` for the open project. Ask questions and use the
**query-knowledge** skill; then the same from the shell:

```bash
oto query --project acme resolve "<jargon from your documents>"
oto query --project acme docs
oto query --project acme search "<a phrase from a document>"
oto query --project acme by-type Risk
oto query --project acme count --type DecisionRecord
oto query --project acme group status --type Requirement
oto serve --project acme        # then paste a JSON-RPC tools/list request on stdin
oto serve --project acme --http 8765     # then open http://127.0.0.1:8765/ (the explorer) and /api/entity?term=<label>
oto serve --project acme --http 8765 --view reader   # the page-shaped reader instead
oto query --project acme pending                     # what is on its way in, by station
oto serve --project acme --http 8765 --watch        # the preview, rebuilt on every change while you author
oto build --project acme --target site   # build/site/: the explorer and data.json, to open from disk or host anywhere
oto serve --project acme --http 0.0.0.0:8765                     # refused: no token
OTO_SERVE_TOKEN=$(openssl rand -hex 16) oto serve --project acme --http 0.0.0.0:8765   # then, from another
     # machine: curl -H "Authorization: Bearer <token>" http://<host>:8765/api/status, and in a browser
     # http://<host>:8765/?oto_token=<token> once
```

Add entries to `lexicon.json` for your jargon, including one with `"status": "not_ingested"`, and
rebuild. Ask a global question ("what is this organisation most concerned with") and keep the
answer as `notes/themes/<slug>.md`. Rebuild while the server is running.

Pass when the host lists seventeen `kg_*` tools, a proposal dropped into `proposals/` shows in `pending`
and, with `--watch`, appears in the explorer dotted with its station within a few seconds and disappears
from the lane once applied and built, `/api/entity` over HTTP returns the same text as the CLI
plus the rows as JSON, the explorer at `/` draws the graph in columns, lights a neighbourhood on hover,
shows an entity's provenance, evidence and a derived edge with its rule in the panel, and says "live";
the reader shows the home map, an entity card and a document page; `build/site/index.html`
opened from disk shows the same and says "static"; `/api/graph` and `build/site/data.json` are the same object, every answer cites entity ids and sources with dates,
`resolve` maps jargon to ids and says plainly when a thing is not ingested, a global answer is
labelled as a synthesis and names the facts it rests on, the theme note is found by `search`
after the next build, the running server answers from the new build on the next call with no
restart, the bind beyond localhost is refused without a token and, with one, every call without
the bearer header answers 401 while the browser that opened the app once with `oto_token` keeps
working.

## 9. Evaluate

Exercises: the gold set, the benchmark against baselines, ablations, reader feedback.

```bash
oto bench start --project acme
oto bench add --project acme --from questions.json      # a few questions per document; the evaluate skill writes them
oto bench validate --project acme
oto bench run --project acme --ablations
oto feedback record --project acme --question "<q>" --verdict wrong --by "<who>" --at <date> --expected "<the right answer>"
oto feedback promote --project acme
```

Pass when `validate` refuses a malformed set, `run` scores OTO against the lexical baseline and
reports the dense baseline as unmeasured without the `bench` extra, the ablations with the graph
off and with time off score lower on the metric each pillar claims, and a promoted complaint
becomes a gold question that then runs.

## 10. Neo4j, the production store

Exercises: the loader, verification, serving from Neo4j, the honest failure, the two stores
answering alike.

```bash
docker run -d --name oto-neo4j -p 7687:7687 -p 7474:7474 -e NEO4J_AUTH=neo4j/<password> neo4j:5
export NEO4J_PASSWORD=<password>
```

In `acme/project.config.json` set `"targets": ["sqlite", "neo4j"]`, `"neo4j": {"uri":
"bolt://localhost:7687", "database": "neo4j"}` and `"serve": {"backend": "neo4j"}`. Then:

```bash
oto build --project acme --verify
oto status --project acme
oto query --project acme entity "Payments platform"                     # stderr says: serving Neo4j
oto query --project acme --backend sqlite entity "Payments platform"    # the same card
docker stop oto-neo4j && oto query --project acme entity "Payments platform"; docker start oto-neo4j
```

Open the Neo4j Browser at `http://localhost:7474` and run
`MATCH (n:Entity {project: "acme-platform"}) RETURN n LIMIT 50`. From a clone of the engine, run
the equivalence battery:

```bash
NEO4J_URI=bolt://localhost:7687 NEO4J_PASSWORD=<password> python -m pytest -q tests/test_store_equivalence.py
```

Pass when the build prints `neo4j: loaded ...` and `verified`, `status` says `serving Neo4j ...
build_seq N`, the two backends print the same card, a stopped Neo4j gives `cannot reach Neo4j`
with exit code 1 and no silent fallback, the Browser shows nodes labelled by class with `kind`
on relationships, and the battery passes.

## 11. Repository mode, journey 1: documents pushed to GitHub

Exercises: `oto init --repo`, the six workflows, the Claude Code Action, the pull request as the
human gate, the deploy to Neo4j and the query repository.

```bash
oto init --name "Acme Platform" --ontology software-architecture --project acme-kb --repo
cd acme-kb && git init -b main && git add -A && git commit -m "oto project"
gh repo create <org>/acme-kb --private --source . --push
gh secret set ANTHROPIC_API_KEY
gh secret set OTO_ENGINE_TOKEN          # only if the engine is installed from a private fork
gh variable set NEO4J_URI --body "bolt://<host>:7687"; gh secret set NEO4J_PASSWORD
gh repo create <org>/acme-query --private
gh variable set OTO_QUERY_REPO --body "https://github.com/<org>/acme-query"; gh secret set OTO_QUERY_REPO_TOKEN
```

In the repository settings, under Actions, allow GitHub Actions to create and approve pull
requests, and protect `main` so the `oto checks` workflow is required. Then:

```bash
cp <a document> inbox/ && git add inbox && git commit -m "ingest: <the document>" && git push
```

Watch, in order: **oto ingest** commits `processing/`, `runs/` and `build/documents/`;
**oto author** opens a pull request from `oto/run-<id>` whose description is
`runs/<id>.report.md`; **oto checks** runs the gates as status checks; a comment `@claude <what
to change>` makes **oto review** revise the branch; merging runs **oto deploy**, which builds,
loads Neo4j with `--verify`, keeps the store as an artifact and publishes it to the query
repository. Push an unsupported file too.

Pass when each workflow is green in turn, the pull request reads as a recap with what changed,
what is now answerable and what needs a person, a revision request is answered on the branch,
the merge reaches Neo4j (`oto status` against it says the new `build_seq`), the query repository
holds exactly the store, the identity, a manifest and a README, and the unsupported file lands in
`errors/` with an issue opened for it.

## 12. Journey 2: a correction made in conversation

Exercises: the capture skill inside a repository, and the same pipeline from a spoken source.

Open the `acme-kb` checkout in Claude Code and tell the agent a correction ("the ledger moved to
Postgres in April"). The **capture** skill writes `inbox/<date>-<title>.md` in the speaker's
words. Commit and push it.

Pass when the pull request that follows carries the statement as a fact whose source is the
capture document, names the speaker, dates it to the date you gave and not to today, and
supersedes the fact it contradicts with a change note in your words.

## 13. The query repository for readers

Exercises: `oto publish`, `oto sync`, serving a checkout.

On a second machine, or a clean directory:

```bash
oto sync --repo https://github.com/<org>/acme-query          # OTO_QUERY_REPO_TOKEN in the environment if private
oto status --project ~/.acme-platform-kg
oto query --project ~/.acme-platform-kg entity "Payments platform"
oto sync --repo https://github.com/<org>/acme-query          # again: a fast-forward
```

Open `~/.acme-platform-kg` in Claude Code with the plugin. Without a deploy, publish by hand from
the knowledge project: `oto publish --project acme-kb --repo https://github.com/<org>/acme-query`
(add `--site` after `oto build --target site` to carry the static site beside the store). In
repository mode, `gh variable set OTO_SITE_VIEW --body explorer` makes the deploy workflow do the same
on every merge.

Pass when `status` says it is a published store with the build sequence and source commit, the
answers match the knowledge project's, the plugin's server serves the checkout, no `build/`
appears inside it, and a second publish of an unchanged store pushes nothing.

## 14. Specs and decisions

Exercises: the spec skill, the decisions convention, the round trip from document to fact.

In Claude Code on either project, ask: "write an architecture decision record for <a choice in
your domain> from the graph". Then put the document in `inbox/` (or capture its decisions) and
run the pipeline.

```bash
oto query --project acme by-type DecisionRecord
oto query --project acme neighbors decision.<slug>
oto query --project acme policy
```

Pass when every claim in the document cites an entity and a source, the section "What the graph
does not say" is present and honest, the decisions appear as `DecisionRecord` nodes dated and
related by `decided_by` to what they shaped, and the `decision-is-documented` rule no longer
flags them because they cite the document.


An architecture decision record is markdown with frontmatter under `docs/adr/`, compiled into a
`Decision` node without a model:

```bash
cp docs/adr/0003-deployed-only-by-events.md roadmap/inbox/ && oto ingest --project roadmap
oto curate start --project roadmap && oto curate propose --from roadmap/processing/0003-deployed-only-by-events.md --project roadmap
oto curate add --from roadmap/proposals/0003-deployed-only-by-events.json --project roadmap && oto curate check --project roadmap
oto curate apply --by "<you>" --note "ADR-0003" --project roadmap && oto build --project roadmap
oto query --project roadmap ask PR26 THING=workitem.epic-m      # which decisions govern Epic M, by whom, current?
```

Pass when the node is `decision.adr-0003`, cites the ADR's Decision sentence word for word, governs
the epic the frontmatter names, and a later ADR with `supersedes: ADR-0003` retires it on its date so
`oto query entity decision.adr-0003 --as-of <earlier>` still reads it; a frontmatter the graph cannot
read (a status that is not proposed or accepted, a nested map, no `## Decision`) is refused before
the gates, and a `governs` target the graph lacks is named and not proposed.

## 15. An ontology from your own vocabulary, and a registry

Exercises: ontology export, the privacy scan on the sample, init from a user ontology, a
registry added by URL, an ontology fetched by name, a pinned version, an update.

```bash
oto ontology export --project acme --name acme-arch --from-graph 12 --summary "<one line>"
oto ontology show acme-arch
oto init --name "Try" --ontology acme-arch --project try && oto build --project try
```

Then publish it into a registry: create an empty private repository (`gh repo create
<org>/oto-registry --private`) and, with `OTO_REGISTRY_TOKEN` or `gh auth setup-git` in place:

```bash
oto ontology publish --project acme --to https://github.com/<org>/oto-registry --name acme-arch \
    --summary "<one line>" --note "first cut" --registry-name <org> --plugin
```

`--plugin` also makes the ontology a Claude Code plugin and lists it in the registry's
marketplace, so in Claude Code `/plugin marketplace add <org>/oto-registry` then
`/plugin install acme-arch@<org>` gives the agent a skill that starts a project from it.

From another machine or a clean user directory:

```bash
oto registry add https://github.com/<org>/oto-registry
oto ontology                                                       # lists it as "in a registry, not on this machine"
oto ontology add acme-arch
oto init --name "Try2" --ontology acme-arch@1 --project try2
# change a class in acme, then publish again with --note, and:
oto status --project try2                                           # "v2 available: oto ontology diff"
oto ontology diff --project try2
oto ontology update
```

Pass when the export is refused if the sample would carry personal data, the new ontology is
listed beside the shipped ones and shadows a shipped one of the same name, a project made from it
builds and answers, the first publish creates the index and the tag `acme-arch/v1`, a publish with
a deny term in the vocabulary is refused and pushes nothing, the fetched ontology's
`manifest.json` records the registry, source and commit, `oto init` names the registry and the
command when an ontology is only there, a wrong pin is refused, `status` announces the newer
version, `diff` classifies the change and says how many of the project's nodes it touches, and
`update` brings the newer version, and the plugin installs in Claude Code with its skill.

## 16. Tools: the graph's hands, described and never invoked

Exercises: the tool files an ontology ships (the class Tool, called Action until 2026-10; `oto actions` and `actions/` still work), the catalog, readiness, the intended status, a
recorded run becoming evidence through the gates, the act skill. The guided version, with a stand-in for GitHub so it needs no token, is
[scenarios/tools.md](scenarios/tools.md).

The software-architecture ontology ships `Repository`, `implemented_by`, a current sample
repository and three tools (`tools/`): a daily repository check and a create-repository
tool bound to the GitHub MCP server, and a weekly read of what an `Interface` answers. Add an
intended repository to `graph.json` (`"status": "intended"`, `owner` and `name` attributes,
`implemented_by` from a component) to see the create tool become ready. Or write one of your
own:

```bash
cat > acme/tools/tool.check-repository.json <<'EOF'
{"id": "tool.check-repository", "label": "Check that a repository exists",
 "description": "Reads the repository's metadata and records its default branch.",
 "subject": "Repository", "executed_by": "team.payments",
 "annotations": {"readOnlyHint": true, "destructiveHint": false, "idempotentHint": true},
 "inputSchema": {"type": "object", "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}}, "required": ["owner", "repo"]},
 "bind": {"owner": "$attr.owner", "repo": "$attr.name"},
 "when": [{"node": "r", "type": "Repository", "where": {"status": "intended"}}],
 "invoke": {"transport": "mcp", "server": "github", "tool": "get_repository"},
 "needs": ["GITHUB_TOKEN"],
 "result": {"kind": "proposal", "then": {"node": "$subject", "status": "current", "attributes": {"default_branch": "$response.default_branch"}}},
 "schedule": "daily"}
EOF
oto tools check --project acme
oto tools list --project acme                                  # ready on the intended repository
oto tools show tool.check-repository --on repo.payment-api --project acme   # the bound invocation
oto build --project acme && oto query --project acme tools --on repo.payment-api   # the same from the store
# invoke it yourself (gh api repos/<owner>/<name> > response.json), then:
oto tools record tool.check-repository --on repo.payment-api --by "<you>" --response response.json --project acme
oto ingest --project acme
oto curate start --project acme && oto curate add --project acme --from acme/proposals/tool.check-repository.<date>.json --dry-run
oto curate add --project acme --from acme/proposals/tool.check-repository.<date>.json && oto curate check --project acme
oto curate apply --project acme --by "<you>" --note "the repository exists" && oto build --project acme
oto query --project acme entity repo.payment-api && oto query --project acme policy
oto tools list --project acme --due          # the daily check is due until it runs, then not until tomorrow
```

In repository mode (stage 11), `oto init --repo` also writes `.github/workflows/oto-tools.yml`
and `.github/scripts/oto-tools-invoke.py`; run the workflow by hand from the Actions tab once:
it invokes the due read-only tools it can (the interface probe over HTTP; the GitHub check is
bound to an MCP server and is skipped with a note), records them, and opens a pull request
labelled `oto-tools` with the run summary.

Pass when `oto ontology show software-architecture` lists three tools and `oto init` installs
them, `check` names a mistake you plant (a `bind` to a neighbour, a schedule on a non-read-only
action), `list` says the check is ready on both repositories, the create action on the intended
one only and the probe on the interface, in Claude Code the **act** skill shows the bound
invocation and asks you by name before the create action,
`show` prints the inputs bound from the node and the variable name it needs, the entity card says
INTENDED before and `current` after with the run document as evidence, `vet` is clean after
ingest, the action's card shows `acts_on` the repository and its last run, the explorer draws the
intended fact dotted and the action with a "ran" flag, the same action list comes from the store
and from the files, a second run with a different branch is refused at merge as a conflict, and an
intended fact older than ninety days appears under `policy` as `intended-fact-overdue`, `--due`
lists the check before a run and not after, and the workflow's pull request holds the run
records, the run documents in `processing/`, the proposals and, when the check was clean, the
applied graph.

## 17. Deploy: one config, environments, the same build promoted

Exercises: `oto deploy init` and `check`, `oto publish --to dev`, promotion with `--promote` and
`--by`, the record on each environment's branch, `oto sync --branch`, `oto deploy status`, and the
refusals (a skipped environment, a different commit, a tampered store, a missing approver). The
query repository can be a bare git repository on this machine; nothing needs GitHub.

```bash
git init --bare -b main /tmp/acme-store.git
oto deploy init --project acme --repo you/acme --to /tmp/acme-store.git
oto deploy check --project acme                         # dev -> test -> prod; test and prod name approvers
oto publish --project acme --to dev --source you/acme@abc123
oto publish --project acme --to test --promote abc123 --by "<you>"
oto publish --project acme --to prod --promote abc123   # refused: prod names approvers; add --by
oto publish --project acme --to prod --promote def456 --by "<you>"   # refused: test holds abc123
oto deploy status --project acme                        # what each environment holds, and who approved it
oto sync --repo /tmp/acme-store.git --branch test --dest /tmp/acme-test && oto status --project /tmp/acme-test
```

Pass when dev, test and prod hold the same store hash, each record names the approver, prod is
refused without one and with another commit, and a store edited by hand on the dev branch is
refused at the next promotion ("does not match its manifest"). In repository mode, `oto init --repo`
writes the deploy workflow with `promote-test` and `promote-prod` jobs behind GitHub Environments of
the same names: create them in the repository's settings with your login as required reviewer,
merge a change, and the run stops at test until you approve; the record then names `github` as the
approver's kind.

## 18. Work: the plan as facts, three states from transitions, the board, messages

Exercises: the `work` ontology and `communication` on top of it, `oto work set`, the derived
state, the block's shape, `oto work board` and the snapshot's `work` section, the workbench's Work
page, `oto work notify`, `oto work inbox` (what a session opens with, through the plugin's
SessionStart hook), `oto work reply --resolve`, `oto work event merged-pr`, the board's questions
and the history; the scenario `tests/scenarios/roadmap` plays the same story with this roadmap's
epics.

```bash
oto init --name "Plan" --ontology communication --project plan && oto build --project plan
oto query --project plan ask WK12                                   # deployed, and where: the sample's checkout epic, prod
oto work set "Daily settlement batch" --state blocked --reason "the acquirer's file format is not published" \
    --waiting-on "Payments team" --by "<you>" --at 2026-10-20 --project plan
oto build --project plan && oto query --project plan ask WK11       # blocked: since when, why, on whom
oto work set "Daily settlement batch" --state open --by "<you>" --at 2026-10-24 --project plan && oto build --project plan
oto query --project plan entity transition.s-settlement-batch-1 --as-of 2026-10-22   # the block, superseded, as it was
oto work set "Daily settlement batch" --state deployed --by "<you>" --at 2026-10-25 --project plan   # refused: never by hand
oto work set "Ledger read replica" --state blocked --by "<you>" --at 2026-10-25 --project plan       # refused: no reason, no waiting-on
oto work board --project plan                                       # blocked by whom it waits on, deployed by environment, open
oto serve --project plan --http 8795 --view workbench               # the Work tab shows the same board, live
oto work notify "Ledger read replica" --by "<you>" --at 2026-10-26 --due 2026-10-30 --body "Can you decide this week?" --project plan
oto build --project plan && oto query --project plan ask CM1 PERSON=person.m-okafor   # what waits for her: the message, with the item
oto work inbox --as "Mina Okafor" --project plan                    # the same, as her session would open (git identity by default)
oto work reply message.t-ledger-replica-2 --body "Approved." --resolve --by "Mina Okafor" --at 2026-10-27 --project plan   # resolved, and the block lifted
oto work event merged-pr --repo you/plan --number 7 --item "Ledger read replica" --environment qa --at 2026-10-28 --project plan   # deployed to qa; run it twice
oto build --project plan --target site --view workbench             # the published snapshot: the person she is shown as "M.O."
```

Pass when the state follows the current transition (blocked, then open), the block names the person
or team it waits on and the date, the superseded transition reads as blocked as of a date between
the two, `deployed` and a block without its context are refused with nothing written, and a graph
whose items still assert `planned`, `in-progress` or `done` answers the questions as open and
deployed (`oto ontology diff` reports the values renamed, not a type change). The board and the
Work tab agree with `oto query ask WK11`; the message `notify` writes carries the item, the block's
date and reason and your words, goes to whom the block waits on (`--to` for someone else; refused
when the item is not blocked, or in a vocabulary without `Message`), and the published copy of the
snapshot shows the person it waits on as initials. The inbox lists the pending messages for a person
with the item and the block, and nothing once they are answered; a reply marks the message replied, a
resolving reply marks it resolved and appends the Open transition in the same gated change; the
merged-PR event appends one deployed transition and, delivered again, says so and appends nothing. In
a project with a git identity, `oto work inbox --hook` prints what waits and is silent otherwise:
open a Claude Code session in the project and the inbox is the first thing it says. The real
project is [roadmap/](../roadmap/README.md): this roadmap, tracked with these commands, built and
checked by `tests/test_roadmap_project.py`.

## 19. Audit and tracing: every write on a chain, every operation in a span

Exercises: the audit log appended by every write path, `oto audit verify`, `oto audit for <node>`,
the stable IRI of a node promoted through the environments, and tracing behind the `otel` extra
with its redaction policy.

```bash
oto work set "Epic C" --state blocked --reason "..." --waiting-on "Chiheb Dkhil" --at 2026-10-27 --project roadmap
oto work set "Epic C" --state blocked --at 2026-10-27 --project roadmap          # refused: recorded too
oto audit verify --project roadmap                                              # chain intact
oto audit for workitem.epic-c --project roadmap                                 # who did what to it, refusals included
sed -i '' '2s/applied/refused/' roadmap/audit.jsonl && oto audit verify --project roadmap   # BROKEN at record 2: edited (then git checkout the file)
oto publish --project plan --to dev ... && oto publish --project plan --to test --promote <commit> --by "<you>"   # publish and promote append
```

Pass when every write (the work pack's set, notify, reply and event, their refusals, a no-op event,
`curate apply` and `undo`, `ingest complete`, `publish`, each promotion) appends one record with the
principal, the nodes, the graph's version and the decision; an edited record breaks the chain at its
number, a removed or reordered one at the record after it; and the node ids, hence the IRIs under the
project's namespace, are the same in dev, test and prod.

```bash
pip install "oto-kg[otel] @ git+https://github.com/Cynergis/oto"
OTO_TRACE=console oto build --project roadmap 2>spans.json            # one span per stage under oto.build
OTO_TRACE=console oto work set "Epic C" --state open --at 2026-10-28 --project roadmap 2>>spans.json
oto audit log --project roadmap                                        # the record's trace_id is the span's
grep -c '"name": "oto.work.set"' spans.json; grep -c 'Epic C' spans.json   # 1, and 0: the item's name is text someone wrote
OTO_TRACE=1 OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 oto serve --project roadmap --http 8790   # kg.<tool> spans to a collector
```

Pass when the build opens `oto.build` with a child per stage, a tool call opens `kg.<tool>` with its
arguments redacted (`arguments.query` is a size and a hash, never the words), the audit record written
inside `oto.work.set` carries that span's trace id, and no prompt, body, reason or email appears in any
span's attributes; without `OTO_TRACE`, or without the packages, nothing changes and no span exists.

## 20. Graphs that know each other: descriptors, dependencies, the concierge root

Exercises: the descriptor `oto init` writes, `oto graph describe`, `oto graph depend`, `oto graph
dependencies`, CORE4, a concierge root, `kg_dependencies` and `kg_call` across two served graphs.

```bash
oto init --name "Policy KB" --slug policy --ontology auto-claims --project policy
oto graph describe --reach https://kg.example.org/policy --project policy > policy.descriptor.json
oto graph depend --on policy.descriptor.json --by "<you>" --at 2026-10-27 --project roadmap   # the roadmap now depends on it
oto build --project roadmap && oto query --project roadmap ask CORE4 GRAPH=graph.oto-roadmap
oto graph dependencies --project roadmap
oto graph describe --record --by "<you>" --at 2026-10-27 --project <an older project>   # a project made before descriptors
oto init --name "Policy KB, the copy" --slug policy-2 --ontology auto-claims --project policy-2
oto graph describe --reach https://kg.example.org/policy-2 --project policy-2 > policy-2.descriptor.json
oto graph depend --on policy-2.descriptor.json --by "<you>" --at 2026-10-27 --project roadmap   # warns: a near-duplicate of policy
oto ontology check --project roadmap                                                            # the graphs section reports the pair
oto graph describe --subject "Policy KB, the copy: the 2027 policy wording only" --project policy-2   # sharpen, then depend again
```

Pass when a new project's graph holds `graph.<slug>` with its subject, classes, reach and slug (an
`--empty` project holds that one node; a bare project with no vocabulary holds none); the descriptor
printed carries what another project needs and nothing of the graph's facts; `depend` adds the other
graph's node and the edge through the gates and says so when it is already there; CORE4 lists the
dependency with its reach; a descriptor missing its subject or reach, or a graph's own, is refused.
Two descriptors that say nearly the same words are a near-duplicate: `depend` warns as the second is
declared and `ontology check` prints "graphs: 3 descriptor(s); 1 near-duplicate pair(s)" with the
words that tell them apart ("told apart only by (nothing) / copy"); it is advisory, so `--strict` and
the build still pass, and a `--subject` that says what only that graph holds clears it.

```bash
oto init --name "Concierge" --slug root --concierge --project root            # oto-core alone, no sample, descriptors only
oto serve --project roadmap --http 8790 &  oto serve --project policy --http 8791 &
oto graph describe --reach http://127.0.0.1:8790 --project roadmap > roadmap.descriptor.json
oto graph describe --reach http://127.0.0.1:8791 --project policy  > policy.descriptor.json
oto graph depend --on roadmap.descriptor.json --by "<you>" --at 2026-10-27 --project root
oto graph depend --on policy.descriptor.json  --by "<you>" --at 2026-10-27 --project root
oto build --project root && oto serve --project root --http 8789 &
curl 'http://127.0.0.1:8789/api/dependencies?question=which+epics+are+blocked'   # the roadmap ranks first
curl 'http://127.0.0.1:8789/api/call?graph=graph.oto-roadmap&tool=kg_ask&question=WK11'   # answered from the roadmap, over HTTP
```

Pass when the root's graph holds nothing but Graph nodes (a stray Document fails its build with
"descriptors only"), `kg_dependencies` ranks the roadmap first for a question about epics and offers
both when neither descriptor says more than the other, `kg_call` returns the dependency's own text
prefixed with where it came from, refuses a `kg_call` of a `kg_call`, a tool a dependency does not
answer, a graph not among the descriptors, and a reach that is not HTTP, and says in words when the
reach does not answer.

## 21. The data pack: a schema as facts, lineage back to the feed, who reads what

Exercises: the `data` ontology on `software-architecture`, its shapes, DT1 to DT6, the `draft` default.

```bash
oto init --name "The ledger, described" --slug ledger --ontology data --project ledger
oto build --project ledger
oto query --project ledger ask DT1 TABLE=table.ledger-postings        # columns, types, keys, meaning, confirmed or draft
oto query --project ledger ask DT2 TABLE=table.ledger-postings        # the job that loads it, its schedule and tool, the feed behind it
oto query --project ledger ask DT3 TABLE=table.ledger-postings        # who reads it: the payment API, transactionally, from the log
oto query --project ledger ask DT4                                    # every table and column whose meaning nobody confirmed
oto query --project ledger ask DT5 STORE=datastore.ledger             # what the estate's ledger holds
oto query --project ledger ask DT6 FEED=feed.custodian-settlements    # downstream of the custodian file
oto ontology check --project ledger                                   # shapes: every node satisfies them
```

Pass when the sample's ledger answers all six (the store and the components are the architecture
sample's own: one vocabulary); DT4 lists `posted_at` and `ledger.accounts`, which carry no status, and
not `posting_id`, which is confirmed; a column attached to a second table or a `Usage` of no table
fails `oto ontology check --strict` with the shape named.

Then a real store, read in place through the SQLite overlay (the project's own built store will do):

```bash
oto connectors check sqlite --project ledger                          # the kit's overlay half: introspect, read-only, log
oto data introspect --store datastore.ledger --at 2026-10-27 --project ledger        # this project's own store, as the catalog says it
oto data introspect --path /path/to/any.sqlite --store datastore.ledger --at 2026-10-27 --project ledger
oto curate start --project ledger && oto curate add --from proposals/schema-ledger.json --project ledger
oto curate check --project ledger && oto curate apply --by "<you>" --note "the ledger's schema" --project ledger
oto build --project ledger && oto query --project ledger ask DT5 STORE=datastore.ledger
```

Pass when the kit lists `overlay introspect`, `overlay read-only` and `overlay log` as ok; introspect
writes `build/documents/schema-ledger.md` (one line per table and column) and
`proposals/schema-ledger.json` with a `Table` per table or view, a `Column` per column carrying type,
nullability and key, `column_of`, `references` and `part_of` edges and a `Document` of kind `schema`,
every node quoting its line; `curate check` holds every quote and shows no blocking problem; DT5 lists
the store's tables and DT4 lists every column as a draft; introspecting the unchanged store again and
applying it adds nothing; a project whose vocabulary has no `Table`, a store the graph does not hold,
a missing file and a missing `--at` are each refused in words.

Then a store OTO does not own, and the passthrough:

```bash
OTO_POSTGRES_DSN=postgresql://ledger@db.internal:5432/ledger PGPASSWORD=... oto connectors check postgres --project ledger
OTO_POSTGRES_DSN=... oto data introspect --connector postgres --store datastore.ledger --at 2026-10-27 --project ledger
OTO_BIGQUERY_PROJECT=acme OTO_BIGQUERY_DATASET=ledger oto data introspect --connector bigquery --store datastore.ledger --at 2026-10-27 --project ledger
# oto.deploy.json: "overlay": {"connector": "postgres", "connection": {"endpoint": "postgresql://ledger@db.internal/ledger", "auth": "basic", "secret": "PGPASSWORD"}, "native_read": true}
oto deploy check --project ledger
oto serve --project ledger --http 8795 &
curl 'http://127.0.0.1:8795/api/read?sql=SELECT+count(*)+AS+n+FROM+postings'        # read-only, through the postgres overlay
curl 'http://127.0.0.1:8795/api/read?sql=DELETE+FROM+postings'                        # refused in words
```

Pass when the kit's overlay half passes against the live store; introspect reads the same tables,
columns, keys and references from information_schema as from SQLite (`pip install "oto-kg[postgres]"`
or `"oto-kg[bigquery]"` first; without the package the connector says so); `kg_read` answers a SELECT
with where it was read and that nothing could be written, refuses anything else, and is off (saying
what to set) without `overlay.native_read: true` in `oto.deploy.json`; `deploy check` refuses an
overlay naming a connector that is not one, a `native_read` that is not true or false, and a
password inside the endpoint.

Then where the rows come from, read from what the ETL already says (the fixtures under
`tests/fixtures/lineage/` are a dbt manifest and three SQL files for the same ledger):

```bash
oto data lineage --dbt tests/fixtures/lineage/dbt-manifest.json --store datastore.ledger --at 2026-10-27 --project ledger
oto data lineage --sql tests/fixtures/lineage/sql --store datastore.ledger --at 2026-10-27 --project ledger
oto data lineage --sql etl/nightly.sql --tool airflow --store datastore.ledger --at 2026-10-27 --project ledger
oto curate start --project ledger && oto curate add --from proposals/lineage-ledger-dbt.json --project ledger
oto curate check --project ledger && oto curate apply --by "<you>" --note "the ledger's lineage" --project ledger
oto build --project ledger
oto query --project ledger ask DT2 TABLE=table.ledger-daily-balances  # the dbt job, nightly at 03:00, sourced from postings
oto query --project ledger ask DT6 FEED=feed.custodian-settlements    # the jobs the custodian file feeds and the tables they load
```

Pass when the dbt reader proposes three jobs (`postings`, `daily_balances`, the seed `accounts`) and
two feeds, reports `unknown_report` as a gap (it loads a table the graph lacks) and proposes nothing
for the ephemeral model or the test; the SQL reader proposes one job per file with its `-- schedule:`
and `-- tool:`, `posting_load` sourced from the `s3://custodian/settlements` feed and the `accounts`
table and not from its own staging table, `balance_rollup` sourced from `postings` and not from its
CTE, and `audit_export` reported as a gap; `build/documents/lineage-ledger-dbt.md` has a section per
job and a Feeds section and every node quotes its line; `curate check` holds every quote; DT2 and
DT6 answer after the apply; reading the same manifest again and applying it adds nothing; no `--dbt`
or `--sql`, both at once, a missing `--at`, a store the graph lacks, a file that is not a manifest
and a directory with no `.sql` are each refused in words.

Then who reads what, from the query log (the fixture under `tests/fixtures/usage/` is an exported
log for the same ledger; the estate must declare the readers it names, here a component and a role):

```bash
oto data usage --log tests/fixtures/usage/ledger-log.json --store datastore.ledger --reader payment_api=component.payment-api --reader compliance=role.r-compliance --at 2026-10-27 --project ledger
OTO_POSTGRES_DSN=... oto data usage --connector postgres --store datastore.ledger --at 2026-10-27 --project ledger   # pg_stat_statements, with the role
oto curate start --project ledger && oto curate add --from proposals/usage-ledger-log.json --project ledger
oto curate check --project ledger && oto curate apply --by "<you>" --note "the ledger's usage" --project ledger
oto build --project ledger
oto query --project ledger ask DT3 TABLE=table.ledger-postings        # the payment API transactionally, compliance analytically, both from the log
grep -c SELECT build/documents/usage-ledger-log.md                    # 0: the statement text is hashed, never kept
```

Pass when the command proposes seven uses (the payment API's reads of `postings` and `accounts`
transactional; compliance's aggregates analytical; the analyst's scan analytical; the ETL's insert
transactional), reports the staging table the graph lacks and the two unmapped principals as gaps
and proposes nothing for them, and the document holds a hash, a kind and a call count per statement
shape and no query text; `curate check` holds every quote; DT3 answers with the reader's type, the
kind and `query_log`; reading the same log again and applying it adds nothing; a log in which the
payment API's reads of `postings` turned analytical is reported as a changed use before the gates
and refused by `curate add` as a supersession; a reader map naming a node the graph lacks, a
`--reader` without `=`, both `--log` and `--connector`, a missing `--at` and the SQLite overlay
(which keeps no log) are each refused in words.

Then what it all means, drafted by an agent and confirmed by a person, and the graph as a dependency
of a concierge:

```bash
oto data meaning --store datastore.ledger --at 2026-10-28 --project ledger            # the skeleton: every table and column without a description
# load the data-meaning skill: fill one sentence per node or drop it, keep description_status draft
oto data meaning --check proposals/meaning-ledger.json --project ledger
oto curate start --project ledger && oto curate add --from proposals/meaning-ledger.json --project ledger
oto curate check --project ledger && oto curate apply --by "<you>" --note "meanings drafted" --project ledger
oto build --project ledger && oto query --project ledger ask DT4                       # the drafts, with their sentences
oto data confirm table.ledger-postings --by "<you>" --at 2026-10-29 --project ledger
oto data confirm column.ledger-postings-posted-at --description "When the posting was booked, in UTC." --by "<you>" --at 2026-10-29 --project ledger
oto build --project ledger && oto query --project ledger ask DT1 TABLE=table.ledger-postings   # confirmed
oto audit verify --project ledger
oto graph describe --reach http://127.0.0.1:8795/ledger --project ledger > ledger.descriptor.json
oto init --name Concierge --slug root --concierge --project root
oto graph depend --on ledger.descriptor.json --by "<you>" --at 2026-10-29 --project root && oto build --project root
oto serve --project root --http 8796 &
curl 'http://127.0.0.1:8796/api/dependencies?question=which+job+loads+the+postings+table'   # ask graph.ledger
```

Pass when the skeleton lists twelve nodes with their schema lines as evidence and a `_context` that
never carries a meaning; `--check` refuses the unfilled skeleton ("12 empty description(s)") and a
node whose status is `confirmed` (naming `oto data confirm`); the filled drafts pass the gates and
DT4 lists each with its sentence; `confirm` records an assertion by the person, moves the status,
passes the gates and the audit chain verifies; confirming again changes nothing and says so; a
column with no draft is refused unless the person states it with `--description`; a store or a node
that is not a table or column, a missing `--at` and an empty `--by` are refused in words;
`curate add` of a proposal that says `confirmed` is refused as a supersession; and the concierge
ranks the data graph first for a question about a table and the plan first for a question about a
work item.

## 22. The architecture pack: CALM as facts, the trace to code

Exercises: the `architecture` ontology on `software-architecture`, framework-neutral, with the `calm` pack as the first framework adapter, its shapes, AR1 to AR9.

```bash
oto init --name "Invoice approval, as architecture" --slug invoice --ontology architecture --project invoice
oto build --project invoice
oto query --project invoice ask AR1 NODE=component.invoice-intake      # what it connects to: the database over JDBC, the policy over AMQP via the events exchange
oto query --project invoice ask AR2 NODE=datastore.invoice-db          # the control that safeguards it, with its requirement URL
oto query --project invoice ask AR3 FLOW=flow.invoice-approval         # three steps, in order, over three relationships
oto query --project invoice ask AR4 NODE=component.invoice-intake      # REQ-042, p95 within 900 ms
oto query --project invoice ask AR5 NODE=component.invoice-intake      # src/intake, last touched by 9f3c2a1
oto query --project invoice ask AR6 NFR=nfr.req-042                    # the k6 run: 870 ms on 2026-10-20
oto query --project invoice ask AR7                                    # CP-001, open, prompted by the gate's verdict
oto query --project invoice ask AR8                                    # nodes no control safeguards
oto query --project invoice ask AR9                                    # src/legacy: a module nothing implements
oto query --project invoice ask SA1 SYSTEM=system.invoice-platform     # the estate's own question still answers
oto ontology check --project invoice
```

Pass when all nine answer from the sample (the roadmap's invoice-approval example), the relationships
are one of each CALM shape with a protocol from CALM's list, the flow's steps come out in sequence, the
open proposal is listed and the implemented one is not, `src/legacy` is the one untraced module, and
`oto ontology check` says every node satisfies the shapes.

Then a real model in and out (the fixture is the FINOS trading-system example):

```bash
oto init --name "Trading system" --slug trading --ontology architecture --empty --project trading
# the estate declares an environment first: {"id": "environment.production", "type": "Environment", ...} through the gates
oto arch import --framework calm --file tests/fixtures/calm/trading-system.architecture.json --at 2026-10-27 --environment environment.production --project trading
oto curate start --project trading && oto curate add --from proposals/calm-trading-system.json --project trading
oto curate check --project trading && oto curate apply --by "<you>" --note "the CALM model" --project trading
oto build --project trading
oto query --project trading ask AR1 NODE=component.web-gui                 # five connections over HTTPS
oto query --project trading ask SA1 SYSTEM=system.trading-system           # the estate's question, from the derived part_of and runs_in
oto arch export --framework calm --out trading.exported.json --project trading       # equals the input, up to empty containers
```

Pass when import reports 13 nodes, 8 interfaces, 18 relationships, 2 controls and 7 flows, names
what the model does not say (nothing deployed anywhere: `--environment` supplies it), the document
has a line per fact and every quote holds at `curate check`, the gates apply, AR1 and SA1 answer, and
the exported model equals the input once empty interface and control lists are dropped; a model
without `--environment` whose services CALM composes in nothing is named at `curate check` by the
estate's `part_of` shape; a missing file, a file that is not JSON, a missing `--at`, an environment
the graph lacks and a project without the architecture vocabulary are each refused in words, and
`export` on a graph with no CALM facts says so.

Then the code map and compile on merge (H2), against a git checkout of the code:

```bash
# the estate declares the repository: {"id": "repo.invoice-platform", "type": "Repository", "attributes": {"owner": "acme", "name": "invoice-platform"}}
cat > /path/to/invoice-platform/oto.codemap.json <<'EOF'
{"modules": [{"path": "src/*", "component": "component.invoice-{name}", "except": ["src/legacy"]}, {"path": "lib/*", "component": null}], "ignore": ["node_modules"]}
EOF
oto arch map --repo /path/to/invoice-platform --repository repo.invoice-platform --at 2026-10-27 --project invoice
oto curate start --project invoice && oto curate add --from proposals/codemap-invoice-platform.json --project invoice
oto curate check --project invoice && oto curate apply --by "<you>" --note "the code map" --project invoice && oto build --project invoice
oto query --project invoice ask AR5 NODE=component.invoice-intake      # src/intake, python, its last commit
oto query --project invoice ask AR9                                    # the modules no component implements
# project.config.json: "arch": {"calm": ["architecture/invoice.calm.json"], "environment": "environment.production", "codemap": {"repo": "../invoice-platform", "repository": "repo.invoice-platform"}}
oto arch compile --at 2026-10-28 --by "<you>" --note "compiled from <sha>" --project invoice
oto init --name Invoice --slug invoice --ontology architecture --repo --project invoice-repo   # writes .github/workflows/oto-architecture.yml
```

Pass when the map lists each module with its language and component, the modules the convention
cannot trace are proposed without `implemented_by` and AR9 lists them, each module's last commit is a
`Commit` that `touches` it, mapping again after a new commit adds one node and changes no module,
`compile` imports and maps what the config declares, applies with the note in the audit log and
builds, a compile the gates refuse leaves no candidate and names the finding, a project with no
`arch` section is refused in words, and the workflow file runs `oto arch compile` on every push to
`main`, commits the graph as "oto architecture" and skips its own commits.

Then what an agent reads before it edits, and what a change reaches (H3, H4), on the pack's sample:

```bash
oto init --name "Invoice approval" --slug invoice --ontology architecture --project invoice && oto build --project invoice
oto serve --project invoice --http 8797 &
curl 'http://127.0.0.1:8797/api/arch-context?path=src/scheduler/jobs/nightly.py'    # the scheduler: ADR-007, no control, CP-001 open
curl 'http://127.0.0.1:8797/api/arch-context?node=component.invoice-intake'         # REQ-042 budget 900 ms, measured 870 ms; the PII control on its JDBC connection
oto arch impact --decision ADR-007 --project invoice                                 # what it governs, what that reaches, the modules, CP-001
oto arch impact --orphans --untraced --project invoice
oto arch impact --files docs/adr/0007-read-through-the-intake-api.md --format markdown --project invoice   # what the checks workflow posts
```

Pass when the tool answers a path through the longest module that covers it and says so when no
component implements the module; a node's requirements come with their budget and latest
measurement; a control on a connection of the node is listed with the connection; `impact` of a
decision names what it governs, the modules that implement it, the open proposals and what the
connections reach, and says when the decision is superseded; `--orphans` lists the estate sample's
components no relationship reaches and not the invoice platform's; `--untraced` lists `src/legacy`
and the components with no module; `--files` prints a markdown report for a decision record, nothing
for a file that is not one, and a note for a record the graph does not hold yet; and the checks
workflow comments the report on a pull request that changes `docs/adr/`.

Then the factory's domain graph (Epic I): a storming board in, and the analyst's sign-off:

```bash
oto init --name "The invoice domain" --slug domain --ontology ddd --project domain && oto build --project domain
oto query --project domain ask DD2 CONTEXT=bc.invoice-approval                 # the sample's context runs as the architecture sample's CALM node
oto query --project domain ask AR1 NODE=component.invoice-intake               # the same node, the architecture's question
oto ddd storm --from board.json --at 2026-10-21 --project domain              # the board: build/documents/storm-<context>.md and captures/storm-<context>.json
oto curate propose --from captures/storm-invoice-approval.json --project domain
oto curate start --project domain && oto curate add --from proposals/storm-invoice-approval.json --project domain
oto curate check --project domain && oto curate apply --by "<you>" --note "the storming session" --project domain && oto build --project domain
oto query --project domain ask DD8 EVENT=domainevent.invoice-submitted         # the command that raises it, the aggregate that emits it
oto decide boundedcontext.invoice-approval readiness=ready --by "Ana Lyst" --at 2026-10-22 --project domain
oto build --project domain && oto query --project domain ask DD23              # the ready context whose aggregate is still a draft
```

Pass when the ddd project answers DD2 and AR1 from one node; the board becomes a document with one
line per sticky and a capture whose items quote their stickies, with the root entity of each
aggregate, the trigger of each command (its actor, the policy that issues it, or the external system
that sends it), the events in board order preceding each other, and every element part of the
context; `propose` makes the proposal and the gates take it; DD8, DD9, DD12 and DD22 answer; a command
with no aggregate and a sticky pointing at nothing are said by `storm` before the gates; `decide`
moves readiness with an assertion by the named person and the chain verifies, refuses a value the
vocabulary does not take, an attribute that is a fact, a node the graph lacks, a missing name or date,
and says when nothing changes; and DD23 names the ready context's draft aggregate.

Then the factory's inputs, read from the graph (I3 to I5):

```bash
oto query --project domain ask AR10 NODE=component.approval-policy            # the contracts it consumes, frozen
oto factory spec component.invoice-intake --out specs/invoice-intake.spec.json --project domain
oto factory spec --check specs/invoice-intake.spec.json --project domain       # holds; edit the file by hand and it is refused
oto factory plan --all --project domain                                         # 3 build(s) in 1 group(s): the contracts are frozen
oto decide contract.invoice-events-v1 status=draft --by "Sam Lee" --at 2026-10-27 --project domain
oto factory plan --all --project domain                                         # 2 groups: the policy waits for the intake
oto factory plan --project domain                                               # the components of the contexts a person signed off
```

Pass when AR10 lists the policy's two frozen contracts; the spec carries the context, the use case,
the exposed interfaces with their contracts, REQ-042 with its budget and measurement, the PII
control on the JDBC connection, the connections, the module with its last commit, and a hash that
`--check` holds and that a hand edit breaks; the plan is three parallel builds while every contract
is frozen, two groups once one is a draft, nothing while no context is signed off (said with the
command that signs one off), the signed-off context's component once one is, and a cycle of draft
dependencies is named rather than looped.

Then the factory plugin on files (J1, J2, J7 first cut), in the code repository:

```bash
oto factory spec component.invoice-intake --out /path/to/invoice-platform/.factory/spec.json --project domain
oto factory scope component.invoice-intake --cap 3 --allow tests/intake --out /path/to/invoice-platform/.factory/run.json --project domain
cd /path/to/invoice-platform
echo '{"tool_name": "Edit", "tool_input": {"file_path": "src/scheduler/main.py"}, "cwd": "'$PWD'"}' | python3 -I /path/to/oto/factory/hooks/guard.py; echo "exit $?"      # 2: outside the scope
echo '{"tool_name": "Write", "tool_input": {"file_path": "contracts/x.json"}, "cwd": "'$PWD'"}' | python3 -I /path/to/oto/factory/hooks/guard.py; echo "exit $?"      # 2: read-only
echo '{"tool_name": "Edit", "tool_input": {"file_path": "src/intake/app.py"}, "cwd": "'$PWD'"}' | python3 -I /path/to/oto/factory/hooks/guard.py; echo "exit $?"      # 0
echo '{"cwd": "'$PWD'", "stop_hook_active": false}' | python3 -I /path/to/oto/factory/hooks/loop.py                                                             # block: no verdict yet
echo '{"verdict": "fail", "gaps": ["the IBAN is not validated"]}' > .factory/verdict.json
echo '{"cwd": "'$PWD'", "stop_hook_active": true}' | python3 -I /path/to/oto/factory/hooks/loop.py                                                              # block: the gap
# twice more: the cap of 3 is reached, the run is escalated
/plugin marketplace add Cynergis/oto && /plugin install oto-factory@cynergis-engine                                                                              # in Claude Code
```

Pass when the scope names the component's modules and what `--allow` adds, `contracts/` read-only,
the cap and the spec's hash; the guard refuses an edit outside the scope or into `contracts/`, and
a shell command that writes a contract, allows reads and edits inside the scope, does nothing with
no run and blocks every write with a broken snapshot; the loop sends the runner to the evaluator
without a verdict, back to the gaps on a fail, ends on a pass, and at the cap lets the session stop
with the run escalated; the agents' definitions give the evaluator no edit tool and say it never
sees the runner's reasoning; and the marketplace lists `oto-factory` beside `oto`.

Then the run graph and promotion (I8, J4, M4):

```bash
oto factory plan --all --json --out plan.json --project domain
oto factory run start --plan plan.json --at 2026-10-27 --id r-001 --runs .factory/runs          # one OTO project per run
oto factory run status --run .factory/runs/r-001                                                 # 3 builds, planned
# the loop hook appends its decisions to .factory/events.jsonl in the code repository (run.json names the run: "run": "r-001")
oto factory run sync --run .factory/runs/r-001 --events /path/to/invoice-platform/.factory/events.jsonl
oto factory run record --run .factory/runs/r-001 --component component.invoice-intake --iteration 2 --verdict pass --at 2026-10-27T11:00:00Z
oto factory run replay --run .factory/runs/r-001 --component component.invoice-intake
oto build --project .factory/runs/r-001 && oto query --project .factory/runs/r-001 ask FR1 RUN=run.r-001
oto factory run promote --run .factory/runs/r-001 --component component.invoice-intake --commit <sha> --at 2026-10-28 --into domain
oto curate start --project domain && oto curate add --from proposals/run-r-001-invoice-intake.json --project domain && oto curate check --project domain && oto curate apply --by "<you>" --note "promoted from run r-001" --project domain
oto work event verdict --item workitem.e-checkout --run r-001 --component component.payment-scheduler --verdict escalated --gap "cap reached" --waiting-on person.m-okafor --at 2026-10-28 --project plan
```

Pass when the run project holds the Run with its plan instance and a planned Build per component,
its audit log names the engine, and starting the same id again is refused; `sync` reads each event
once (a second sync adds nothing) and the builds read passed or escalated with their iterations; an
iteration is recorded once and `replay` lists them in order with their gaps; FR1 to FR3 answer;
`promote` refuses a build that has not passed, and for one that has writes the run document and a
proposal with the evidence, the commit touching the component's modules and no run state, which
the gates take and AR5 then shows; and a failed or escalated verdict blocks the work item on the
named person with the gaps as the reason while a pass is noted and changes no state.

Then the criteria, a deviation and a measurement (I6, I7, H5, H6):

```bash
oto factory criteria --context bc.checkout --out criteria/checkout --project domain          # criteria.md, criteria.json, test_criteria_checkout.py
oto factory criteria --component component.invoice-intake --out criteria/intake --project domain   # its context's scenarios and rules, its budget, its control
oto factory deviate --run .factory/runs/r-001 --component component.approval-policy --about contract.invoice-events-v1 \
  --observed "InvoiceSubmitted carries no supplier id, which the approval rules need" --proposes "Add supplier_id as version 2 of the invoice events contract" \
  --at 2026-10-28 --into domain                                                                 # the siblings through the contract, the build failed
oto curate start --project domain && oto curate add --from proposals/deviation-r-001-1.json --project domain && oto curate check --project domain && oto curate apply --by "<you>" --note "a deviation" --project domain
oto query --project domain ask AR7                                                              # the proposal, prompted by what was observed
oto arch measure --nfr nfr.req-042 --from k6-summary.json --at 2026-10-29 --source https://ci.invoice.example/runs/2026-10-29/k6 --project domain
oto curate start --project domain && oto curate add --from proposals/measure-req-042-2026-10-29.json --project domain && oto curate check --project domain && oto curate apply --by "<you>" --note "the k6 run" --project domain
oto build --project domain && oto query --project domain ask AR6 NFR=nfr.req-042                # p95 870 ms over 5000 requests
```

Pass when the criteria name every scenario (given, when, then), rule, policy, budget and control
with the nodes they came from, the skeleton compiles with one skipped test per criterion, a
component no context runs as is refused with the way out; the deviation's document, evidence and
change proposal cite each other, the siblings are the components that consume or expose the
contract and never the deviating one, the run's build reads failed, and AR7 lists the proposal
after the gates; and a JUnit, a coverage.py and a k6 report each read as one value, the
measurement goes through the gates, and AR6 and `arch_context` show it next to the budget.

**The last cut of phase 5: the spec-context skill, the Actions path, metrics, the release.** The
runner starts from the graph, both execution environments run the same hooks, and the metrics are
queries over the run graph.

```bash
# the runner's first move, locally in Claude Code with the oto-factory plugin: load the spec-context skill, then
oto factory spec component.invoice-intake --out .factory/spec.json --project domain
oto factory spec --check .factory/spec.json --project domain                                    # the hash in run.json must agree
oto factory criteria --component component.invoice-intake --out .factory/criteria --project domain
oto query --project domain ask DD22 CONTEXT=bc.invoice-approval                                 # what the builder must produce
oto query --project domain ask AR10 NODE=component.invoice-intake                               # the contracts it consumes, frozen or draft
# in CI: copy factory/workflows/oto-factory.yml to .github/workflows/ of the code repository, set ANTHROPIC_API_KEY,
# run it with component=component.invoice-intake; the same plugin, so the same guard and loop hooks; the run graph is the artifact
# the evaluator writes what the tests said beside its verdict: {"verdict": "fail", "gaps": [...], "tests": "pass"}
oto factory run record --run .factory/runs/r-001 --component component.invoice-intake --iteration 2 --verdict fail --tests pass \
  --gap "the IBAN is not validated" --at 2026-10-27T11:00:00Z                                  # by hand, where there is no hook
oto factory run metrics --run .factory/runs/r-001                                               # iterations to pass, escalation rate, disagreements, cost
oto factory run metrics --runs .factory/runs --json                                             # over every run
oto build --project .factory/runs/r-001 && oto query --project .factory/runs/r-001 ask FR4 RUN=run.r-001   # tests passed, the evaluator failed
# the release: factory/.claude-plugin/plugin.json and .claude-plugin/marketplace.json both say 0.2.0; the README has a Releases section
# the roadmap: a phase is reached when a named person says so
oto decide milestone.phase-5 state=reached --by "Chiheb Dkhil" --at 2026-10-26 --project roadmap
oto build --project roadmap && oto audit verify --project roadmap
```

Pass when the skill parses, names only commands the engine has and the runner loads it first; the
workflow runs `anthropics/claude-code-action` with the `oto-factory` plugin, writes spec, scope and
criteria from the graph, syncs the events after the build and uploads the run graph; `--tests` is
kept on the iteration and the loop hook carries it from `verdict.json` into the events; the metrics
give the mean iterations to pass over the passed builds, the escalation rate over the ended ones,
the FR4 and FR5 disagreements by build, and say cost is not recorded; the two version numbers are
equal; and `milestone.phase-5` reads reached with the assertion among its sources, phase 6 still
planned, the audit chain intact.

## 23. The engine's own gates and CI

Exercises: the gate script, the publishability gate with your deny terms, the CI jobs.

```bash
git clone https://github.com/Cynergis/oto && cd oto
python -m venv .venv && .venv/bin/pip install -e ".[dev,intake,neo4j]"
PYTHON=.venv/bin/python OTO_DENY_TERMS="<term>,<term>" tools/run_gates.sh
gh secret set OTO_DENY_TERMS --repo Cynergis/oto
```

Pass when the script ends with `RESULT: all gates passed`, and on GitHub every job of the CI
workflow is green, including `publishable` in strict mode and `neo4j target and store (live)`.

---

Keep a short log as you go: the stage, the date, what surprised you. A surprise that is not a
bug is a documentation gap, and an `oto feedback record` or an issue on the engine repository is
the place for it.

## 24. The ontology explorer: the vocabulary as a thing to browse

Phase 6 of the roadmap (Epic D) shows the ontology itself, not the instances it types. The first cut
is the class model (D1): a class with its parents, children, relations with cardinality and attributes.

```bash
oto init --ontology architecture --project arch && oto build --project arch
oto serve --project arch --http 8765 --view workbench &
curl -s localhost:8765/api/ontology | python3 -c "import json,sys; m=json.load(sys.stdin); print(m['counts'])"
curl -s "localhost:8765/api/ontology?class=NFR" | python3 -c "import json,sys; c=json.load(sys.stdin); print(c['parents'], [r['name'] for r in c['relations_out'] if r['inherited_from']])"
curl -s "localhost:8765/api/ontology?class=Nothing"                                             # 404, the classes it does declare
curl -s "localhost:8765/api/graph?passages=0" | python3 -c "import json,sys; print(json.load(sys.stdin)['ontology']['counts'])"
# in the browser: http://localhost:8765/#/ontology/Component  -> a kind of Asset; part_of 0..1 to a System, inverse contains;
#   the attributes with their types; "n current things" opens the Knowledge page filtered to the class
oto build --project arch --view workbench                                                        # the exported data.json carries the same model
```

Pass when `/api/ontology` lists every class once in name order with parents, children, relations in
and out and attributes; an NFR carries what Requirement declares, marked inherited; `part_of` reads
`0..1` with its inverse; a controlled attribute lists its values and a decision attribute says a person
decides it; an unknown class is a 404 that names the classes; the payload and the exported site carry
the same model; and the workbench's Ontology tab walks from any class to its parents, children and
relationships by links alone.

## 25. Rules by class and the lexicon in every language

The second cut of the ontology explorer (D2, D3): the rules read by the class they apply to, and the
vocabulary searched by any word in any declared language, each hit landing on the element it names.

```bash
oto init --ontology architecture --project arch && oto build --project arch
oto serve --project arch --http 8765 --view workbench &
curl -s localhost:8765/api/rules | python3 -c "import json,sys; m=json.load(sys.stdin); print(m['counts'], m['by_class']['Component'])"
curl -s "localhost:8765/api/rules?class=Component" | python3 -c "import json,sys; [print(r['id'], r['via'], r['when'], '->', r['then']) for r in json.load(sys.stdin)['rules']]"
curl -s "localhost:8765/api/rules?class=Nothing"                                                # 404, the classes it does declare
curl -s localhost:8765/api/lexicon | python3 -c "import json,sys; m=json.load(sys.stdin); print(m['languages'], m['counts'])"
curl -s "localhost:8765/api/lexicon?q=NFR" | python3 -c "import json,sys; [print(h['kind'], h['name'], h['match'], h['target']) for h in json.load(sys.stdin)['hits']]"
# a project that declares "languages": ["en", "fr"] and writes {"en": "component", "fr": "composant"} as a label:
curl -s "localhost:8765/api/lexicon?q=composant"                                                # the class Component, matched on its fr label
# in the browser: http://localhost:8765/#/ontology/rules/Component  -> the rules that apply, "through Asset" when inherited;
#   http://localhost:8765/#/ontology/lexicon/NFR -> the class and the phrase, a click lands on the class page or the entity
oto build --project arch --view workbench                                                        # the exported data.json carries both
```

Pass when `/api/rules` lists every rule once in declaration order with its `when` lines in words, its
`then`, the classes it names or implies and who confirmed it; `?class=` returns the rules that apply to
that class including those declared on an ancestor, each saying through which one; an unknown class
is a 404; `/api/lexicon` lists every term with its labels in every declared language and the words
people use with the entity each one means; `?q=` ranks an exact label first, then a prefix, then a
substring, in any language, and every hit says where it lands; the payload and the exported site carry
both; and on the workbench a class page says how many rules apply to it, the Rules page reads them by
class, and the Lexicon page's search lands on the element by a click.

## 26. Dependencies read from the descriptors, and from a thing to everything that bears on it

The third cut of the ontology explorer (D4, D5): the graph descriptors as a page, near-duplicates
flagged, and cross-artifact navigation from any entity.

```bash
oto init --ontology architecture --project arch && oto build --project arch
oto init --name "Claims policy" --slug policy --ontology auto-claims --project policy
oto init --name "Claims policy, the copy" --slug policy-2 --ontology auto-claims --project policy-2
oto graph describe --reach https://kg.example.org/policy --project policy > policy.descriptor.json
oto graph describe --reach https://kg.example.org/policy-2 --project policy-2 > policy-2.descriptor.json
oto graph depend --on policy.descriptor.json --by "<you>" --at 2026-10-27 --project arch
oto graph depend --on policy-2.descriptor.json --by "<you>" --at 2026-10-27 --project arch       # warns: a near-duplicate
oto build --project arch && oto serve --project arch --http 8765 --view workbench &
curl -s localhost:8765/api/graphs | python3 -c "import json,sys; m=json.load(sys.stdin); print(m['own'], m['counts'], [(g['id'], g['depends_on'], [n['other'] for n in g['near_duplicates']]) for g in m['graphs']])"
curl -s "localhost:8765/api/graphs?graph=graph.policy" | python3 -c "import json,sys; g=json.load(sys.stdin); print(g['near_duplicates'][0]['told_apart'])"
curl -s "localhost:8765/api/links?entity=component.invoice-intake" | python3 -c "import json,sys; l=json.load(sys.stdin); print(l['counts']); [print(k, [x.get('id') or x.get('phrase') or x.get('name') for x in l[k]]) for k in ('rules','terms','graphs','decisions','files')]"
curl -s "localhost:8765/api/links?entity=nothing"                                               # 404
# in the browser: http://localhost:8765/#/ontology/dependencies -> this graph first, the two policies flagged "hard to tell apart",
#   told apart only by (nothing) / copy; http://localhost:8765/#/knowledge/component.invoice-intake -> Related: the rules that apply,
#   the class term and the words people use, the graph that covers a Component, the decision that governs it, the repository and the
#   code module behind it; every one a click away
oto build --project arch --view workbench                                                        # the exported data.json carries the descriptors; the site computes the links itself
```

Pass when `/api/graphs` names this graph as `own` and lists it first, each dependency with its
subject, reach and classes and who depends on whom; the two policies carry each other as a
near-duplicate with the words that tell them apart (nothing on one side, "copy" on the other); an
unknown graph is a 404; `/api/links` for a component lists the rules that apply to it (the one
declared on Asset saying "through Asset"), the class term and any phrase that names it, the graphs
whose descriptor covers a Component, the decision that governs it with its status, and the
repository (with its URL), code module and document behind it, plus the document its evidence
cites; a superseded decision or edge is history and not listed; and on the workbench the Dependencies
page flags the pair and the entity page's Related section lands on each artifact by a click.

## 27. Versions: the vocabulary at a git ref against the working tree

The fourth cut of the ontology explorer (D6): what changed between two versions of the vocabulary,
from the command line, from the served route, on the workbench, and on every pull request.

```bash
oto init --ontology software-architecture --project estate && (cd estate && git init -q -b main && git add -A && git commit -q -m first)
oto build --project estate
# edit estate/ontology.config.json: remove the class Runbook, add a relation, reword a definition
oto ontology diff --from HEAD --project estate                   # 3 change(s) from HEAD to the working tree: [breaking ] class removed Runbook ...
oto ontology diff --from HEAD --project estate --format markdown  # the table the workflow posts
oto ontology diff --from HEAD --project estate --strict; echo $?  # 1: a breaking change with no version bump
oto ontology diff --from HEAD --to HEAD --project estate          # no change from HEAD to HEAD
(cd estate && oto ontology diff --from HEAD --file ontology.config.json)   # any ontology.config.json in a repository, no project needed
oto serve --project estate --http 8765 --view workbench &
curl -s "localhost:8765/api/ontology/diff?from=HEAD" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['labels'], d['counts'], d['bump_needed'])"
curl -s "localhost:8765/api/ontology/diff?from=nowhere"          # 400, git's own words
curl -s "localhost:8765/api/graph?passages=0" | python3 -c "import json,sys; print(json.load(sys.stdin)['ontology']['versions'])"
# in the browser: http://localhost:8765/#/ontology/versions -> current and accepted versions, what changed since acceptance,
#   and the form "Compare with a git ref": HEAD against the working tree lists the three changes with the breaking one first
# on GitHub: open a pull request that touches an ontology.config.json; the ontology-diff job posts "## Ontology changes" once and refreshes it on every push
```

Pass when the command prints every change most severe first with how many things a breaking one
touches, says when a breaking change has no version bump (and fails `--strict` then), compares two
refs or a file outside a project, and names the ref in git's words when it does not exist; the route
answers the same JSON and refuses a missing `from` or an unknown ref with a 400; the payload says the
current and accepted versions and what changed since; the workbench's Versions page shows them and
compares a ref when served live; and the pull request carries one sticky comment with the markdown
table, refreshed rather than repeated.

## 28. The policy pack: rules as facts, compiled into a signed Cedar bundle

Epic E opens (E1, E2): access policy as facts on the data layer, and the active rules compiled into
a bundle the deploy pipeline carries. ADR-0004 records the choice of Cedar.

```bash
oto init --ontology policy --project ledger && oto build --project ledger      # "policy: 3 rule(s) compiled into build/policy (cedar + json), unsigned"
ls ledger/build/policy                                                          # manifest.json policies.cedar policies.json
oto policy list --project ledger                                                # every rule: status, effect, priority, who may do what on which resources, why
oto query --project ledger ask PL1 ROLE=role.r-compliance                       # what compliance may do: read Table where pii=false
oto query --project ledger ask PL2                                              # where the personal data is: ledger.customers (derived from its email column), the column itself
oto query --project ledger ask PL3                                              # the drafts: the owner-administers-the-ledger rule
sed -n 1,12p ledger/build/policy/policies.cedar                                 # @id("policyrule.reports-never-write-postings") forbid ( principal in Team::"team.reports", action == Action::"write", resource in [Table::"table.ledger-postings"] );
oto policy verify --project ledger                                              # build/policy holds: 3 rule(s), hash ..., unsigned
oto decide policyrule.owner-admin status=active --by "<you>" --at 2026-10-27 --project ledger
export OTO_POLICY_KEY=change-me && python3 - <<'PY'
import json; p="ledger/project.config.json"; c=json.load(open(p)); c["policy"]={"sign_with":"OTO_POLICY_KEY"}; json.dump(c, open(p,"w"), indent=2)
PY
oto build --project ledger                                                      # "policy: 4 rule(s) ... signed with OTO_POLICY_KEY"
oto policy verify --project ledger                                              # signed with OTO_POLICY_KEY
OTO_POLICY_KEY=wrong oto policy verify --project ledger; echo $?                # 1: the signature does not verify
echo "// edited" >> ledger/build/policy/policies.cedar && oto policy verify --project ledger; echo $?   # 1: policies.cedar is not the file the manifest names
unset OTO_POLICY_KEY && oto build --project ledger; echo $?                    # 1: the key the project names is not set
oto policy compile --project ledger --out /tmp/bundle --at 2026-10-27 --sign-with OTO_POLICY_KEY   # anywhere, the same bundle
oto publish --project ledger --repo <query repository>                          # policy/ lands beside the store; MANIFEST.json says rules, hash, signed
```

Pass when the pack passes its self-check on `data`; the build writes the three files and names the
count and whether it signed; a draft rule and a retired one do not compile and PL3 lists them; the
forbid on the postings is one Cedar policy with `resource in [...]` and no `when`, the compliance
read is `resource is Table` with `when { resource.pii == false }`; a table whose column is personal
data reads `pii=True` derived; `verify` refuses an edited file, a wrong key and a content hash that
is not the manifest's, and reports an unchecked signature when no key is given; a project that says
it signs cannot build without the key; a project without the pack says so and writes no bundle; and
the publication carries the bundle with its hash.

## 29. The policy snapshot: what an agent may do for a principal, and the guards that hold it to that

E3: a `Principal` holds roles, an `Agent` is granted some, and the snapshot an agent runs under is the
signed intersection; two plain-Python guards read it; every refusal becomes an audit record.

```bash
oto init --ontology policy --project ledger && oto build --project ledger
oto query --project ledger ask PL6 PRINCIPAL=principal.factory-runner           # what the runner's service account may do through its roles
oto query --project ledger ask PL7 AGENT=agent.merchant-assistant               # the roles the agent was granted and the rules they bring
mkdir -p code && oto policy snapshot --agent agent.merchant-assistant --principal principal.factory-runner --out code/.factory/policy.json --at 2026-10-27 --project ledger
#   code/.factory/policy.json: agent.merchant-assistant running for principal.factory-runner: 2 permit(s), 1 forbid(s), writes under nothing, denied nothing, unsigned
oto policy verify code/.factory/policy.json --project ledger                     # holds: a snapshot for ... hash ..., unsigned
# on an architecture project with a code map, a permitted write on a component reaches its modules' paths:
#   {"scopes": {"write": ["src/intake", "tests/intake"], "denied": ["src/legacy"]}, ...}
cd code && echo '{"tool_name":"Edit","tool_input":{"file_path":"src/legacy/old.py"},"cwd":"'$PWD'"}' | python3 -I <plugin>/hooks/policy_guard.py; echo $?
#   policy guard: src/legacy/old.py is denied to agent.merchant-assistant running for principal.factory-runner: forbidden by policyrule....   -> 2
cat .factory/events.jsonl                                                        # {"event": "denied", "tool": "Edit", "path": "src/legacy/old.py", "rule": "...", "agent": ..., "principal": ..., "snapshot": "<hash>", "at": ...}
oto policy denials --events .factory/events.jsonl --project ../ledger           # 1 denial(s) recorded as audit records, 0 already there
oto policy denials --events .factory/events.jsonl --project ../ledger           # 0 recorded, 1 already there: each once
oto audit verify --project ../ledger && oto audit --project ../ledger | grep "policy denied"
export OTO_POLICY_KEY=change-me && oto policy snapshot ... --sign-with OTO_POLICY_KEY   # signed; a guard with the wrong key in OTO_POLICY_KEY refuses every write
python3 - <<'PY'                                                                  # edit the snapshot by hand: the guard refuses every write ("hash")
import json; p=".factory/policy.json"; s=json.load(open(p)); s["scopes"]["write"].append("anything"); json.dump(s, open(p,"w"))
PY
```

Pass when the pack composes on `data` and `agent` and passes its self-check; PL6 and PL7 answer from
the sample; the snapshot holds only what both the agent's and the principal's roles are permitted and
nothing either is forbidden, narrows resources to what both reach, lists each forbid with its rule,
and reaches the code map's paths; an agent that is not an Agent or a principal that is not a
Principal is refused by name; both guards allow a write under a permitted path, refuse one under a
denied path naming the rule, refuse one under no permitted path naming what is permitted, refuse a
shell command that writes under a denied path, let reads through, block every write on a snapshot
edited by hand or signed with another key, allow everything with no snapshot, and record each refusal
as an event; the factory guard keeps the run's read-only paths and lets the policy be the write
scope; and `oto policy denials` and `oto factory run sync` record each denial once as an audit record
that the chain verifies.

## 30. The snapshot's time to live, the re-check before a write, and the served read held to a principal

E6 and E5: a snapshot expires; the gates re-check it before `curate apply`, `decide` and `promote`;
the served `kg_read` answers only a principal the policy permits.

```bash
oto init --ontology policy --project ledger && oto build --project ledger
oto policy snapshot --agent agent.merchant-assistant --principal principal.factory-runner --out code/.factory/policy.json --ttl 2 --project ledger   # expires in two hours
oto policy verify code/.factory/policy.json --project ledger                                         # ... expires 2026-10-27T18:04:11Z, unsigned
python3 - <<'PY'                                                                                     # the engine would have written it with this expiry: the hash follows
import json; from oto import policy; p="code/.factory/policy.json"; s=json.load(open(p)); s["expires_at"]="2026-01-01T00:00:00Z"; s["hash"]=policy.snapshot_hash(s); json.dump(s, open(p,"w"))
PY
oto policy verify code/.factory/policy.json --project ledger; echo $?                                # 1: expired
(cd code && echo '{"tool_name":"Edit","tool_input":{"file_path":"src/x.py"},"cwd":"'$PWD'"}' | python3 -I <plugin>/hooks/policy_guard.py); echo $?   # 2: expired, every write refused
python3 - <<'PY'
import json; p="ledger/project.config.json"; c=json.load(open(p)); c["policy"]={"require_snapshot": True}; json.dump(c, open(p,"w"), indent=2)
PY
oto decide policyrule.owner-admin status=active --by "<you>" --at 2026-10-27 --project ledger; echo $?   # 1: needs a policy snapshot; an audit record says so
oto policy snapshot --agent agent.merchant-assistant --principal principal.factory-runner --out code/.factory/policy.json --project ledger
export OTO_POLICY_SNAPSHOT=code/.factory/policy.json
oto decide policyrule.owner-admin status=active --by "<you>" --at 2026-10-27 --project ledger        # applied; its audit record says "under snapshot <hash> for ... as ..."
oto decide policyrule.compliance-reads-ledger status=retired --by "<you>" --at 2026-10-27 --project ledger   # applied: the snapshot held when it was checked
oto decide policyrule.owner-admin status=retired --by "<you>" --at 2026-10-27 --project ledger; echo $?      # 1: the policy changed since the snapshot was written; write it again
oto audit --project ledger | grep "policy denied"
# the served read, held to a principal (an overlay on a SQLite file, native_read on in oto.deploy.json):
oto serve --project ledger --http 8765 &
curl -s "localhost:8765/api/read?sql=SELECT+account_id+FROM+postings"                               # error: needs to know who asks: X-Oto-Principal
curl -s -H "X-Oto-Principal: principal.factory-runner" "localhost:8765/api/read?sql=SELECT+account_id+FROM+postings"   # 2 row(s): compliance reads a table with no personal data
curl -s -H "X-Oto-Principal: principal.factory-runner" "localhost:8765/api/read?sql=SELECT+email+FROM+customers"       # refused: no rule permits ... (pii, derived from the column)
curl -s -H "X-Oto-Principal: principal.ops-clerk" "localhost:8765/api/read?sql=SELECT+account_id+FROM+postings"        # refused: the clerk's team exports, never reads
OTO_PRINCIPAL=principal.factory-runner oto query --project ledger read "SELECT account_id FROM postings"               # stdio and the CLI read the environment
```

Pass when a snapshot carries `expires_at` from `--ttl`, the project's `ttl_hours` or a day, and
`--ttl 0` is refused; `verify`, both guards and the gates refuse an expired one; a project that
requires a snapshot refuses `decide`, `curate apply` and `promote` without one and records the
refusal; a fresh, intact snapshot whose policy is unchanged lets the write through and the record
names it; a snapshot edited by hand, expired, unsigned where the project signs, signed with another
key, or written before the policy changed is refused with the reason; and the served `kg_read`
refuses an anonymous caller, an unknown principal, a table the graph does not describe and a table
no permit admits or a forbid covers, answers the permitted ones (the agent's grants intersected when
named), takes the principal from `X-Oto-Principal` over HTTP and `OTO_PRINCIPAL` on stdio, records a
refused read and not a permitted one, and reads as before on a graph without the policy pack.

## 31. Phase 6 closes: the inbox under a principal, reminders on a schedule, the milestone reached

N2 and N5 end the phase (Epics D and E, PRs 91 to 100): a user sees only the messages addressed to
them, an unanswered blocker gets a reminder on its due date and every day after, a scheduled job
nudges people who are not in a session, and the phase 6 milestone is reached by a named person.

```bash
oto init --ontology communication --project comms
OTO_PRINCIPAL="Mina Okafor" oto work inbox --project comms                     # 1 pending for Mina Okafor
OTO_PRINCIPAL="Mina Okafor" oto work inbox --as "Payments team" --project comms; echo $?   # 1: a user sees only the messages addressed to them
oto work notify workitem.t-ledger-replica --by "<you>" --at 2026-10-26 --due 2026-10-30 --body "Can you decide the budget this week?" --project comms
oto work remind --at 2026-10-29 --project comms                                 # nothing overdue
oto work remind --at 2026-10-30 --dry-run --project comms                       # would send: message.t-ledger-replica-2 -> Mina Okafor
oto work remind --at 2026-10-30 --project comms                                 # 1 reminder(s) sent: message.t-ledger-replica-3, reminder_of -2, never in_reply_to
oto work remind --at 2026-10-30 --project comms                                 # 0 sent, 1 already reminded today
oto build --project comms && oto query --project comms ask CM4 MESSAGE=message.t-ledger-replica-2   # the reminders it had
oto query --project comms ask CM3                                               # the original is still overdue; the reminders are not
# the scheduled job: .github/workflows/oto-remind.yml runs `oto work remind` every weekday for the roadmap and opens a pull request with the reminders
oto decide milestone.phase-6 state=reached --by "<you>" --at 2026-10-27 --project roadmap && oto build --project roadmap && oto audit verify --project roadmap
oto query --project roadmap ask WK12                                            # Epics D and E deployed by their first pull requests; phase 6 reached
```

Pass when the inbox under a principal is theirs alone and `--as` someone else is refused (silently
in the hook); a pending message past its due date gets one reminder a day and none once answered;
a reminder is a message of its own, `reminder_of` the original, never a reply, so CM3 still lists
the original and CM4 lists the reminders; a dry run writes nothing; the workflow runs on a schedule
and opens a pull request; and the phase 6 milestone reads `reached` with the assertion of the
person who decided it, the audit chain intact.

Phase 6 delivered the ontology explorer (D1 to D6: classes, rules by class, the lexicon in every
language, dependencies with near-duplicates flagged, cross-artifact navigation, versions and the
diff against a git ref posted on every pull request) and policy in the graph (E1 to E6: the policy
pack, the Cedar bundle hashed and signed, the snapshot an agent runs under for a principal with two
plain-Python guards and denials in the audit log, the snapshot's time to live and re-check before a
write, the served read held to its principal), then closed the communication pack with the inbox
under a principal and reminders on a schedule. E7, the generated system's IAM, came after the release.

## 32. The generated system's IAM: bindings derived from the policy, shipped with the system, never enforced by OTO

E7 (after 0.12.0, ADR-0005): a component runs as a service account, a permission names the platform
role it maps to, a table says where it is on the platform, and the same active rules that compile
to Cedar give the platform's bindings, written beside the policy bundle and back into the graph as
generated controls.

```bash
oto init --ontology policy --project ledger && oto build --project ledger      # "policy: 4 rule(s) ..." then "iam: 4 binding(s) on 3 resource(s) for 3 member(s) into build/iam (gcp), 3 binding node(s) proposed, unsigned"
#                                                                               #   not bound: table.ledger-accounts has no resource_uri: no binding on it (policyrule.compliance-reads-ledger)
ls ledger/build/iam                                                             # bindings.json bindings.proposal.json gcp.json iam-bindings.md manifest.json
cat ledger/build/iam/gcp.json                                                   # one policy per resource: {"resource": "//bigquery.googleapis.com/.../tables/invoices", "policy": {"bindings": [{"role": "roles/bigquery.dataEditor", "members": ["serviceAccount:invoice-intake@acme.iam"]}, ...]}}
oto policy verify ledger/build/iam --project ledger                             # holds: 4 binding(s) on 3 resource(s) for 3 member(s), 3 binding node(s) proposed, 0 withheld, hash ..., unsigned
oto query --project ledger ask PL8 PRINCIPAL=principal.invoice-intake           # component.invoice-intake runs as it; iambinding.table-invoices grants it, derived from policyrule.intake-writes-invoices, roles/bigquery.dataEditor
oto query --project ledger ask PL8 PRINCIPAL=principal.ops-clerk                # nothing runs as this principal: a person's account
oto policy iam --project ledger --out /tmp/iam --at 2026-10-27                  # anywhere, the same bundle; the document lands in build/documents/iam-bindings.md; next: curate add --from ..., or --apply
oto policy iam --project ledger --apply --by "<you>" --at 2026-10-27            # applied by <you>: 3 binding node(s) in the graph, built
oto query --project ledger ask PL9 RESOURCE=table.ledger-postings               # the binding node on the postings table: provider, address, bindings, withheld, the rules behind it
# with the calm pack composed too (oto init --ontology policy,calm), the adapter exports a binding node as a control on the component that runs as the granted principal:
oto arch export --framework calm --out /tmp/ledger.calm.json --project ledger && python3 -c "import json; n=[n for n in json.load(open('/tmp/ledger.calm.json'))['nodes'] if n['unique-id']=='invoice-intake'][0]; print(list(n['controls']))"   # ['iam-table-invoices']
oto policy iam --project ledger --apply --at 2026-10-27; echo $?               # 1: --apply takes --by
python3 - <<'PY'
import json; p="ledger/project.config.json"; c=json.load(open(p)); c["policy"]={"provider":"aws"}; json.dump(c, open(p,"w"), indent=2)
PY
oto build --project ledger; echo $?                                             # 1: provider 'aws': this release writes gcp
oto publish --project ledger --repo <query repository>                          # iam/ lands beside policy/; MANIFEST.json says provider, bindings, controls, hash, signed
```

Pass when the build writes the five files and names the counts, the provider and whether it
signed; the accounts table, admitted by the selector and placed nowhere, is named and not bound,
and the customers table, whose column is personal data, is kept out by the derived `pii`; the
clerk's account and the runner's are GCP members (`user:`, `serviceAccount:`); a forbid on a
member's write withholds the editor binding and keeps the viewer one (the unit test holds it with a
graph of its own); `verify` reads the bindings bundle as it reads the policy bundle; the controls
are proposed with the architecture's `external_id`, `requirement_url` and `generated_by`, enter the
graph only through `--apply` with a named `--by`, safeguard the table and the component that runs
as the member, derive from the rules, and come out in the CALM export under the component's
controls; PL8 and AR12 answer; a provider this release does not write is refused by name; and the
publication carries the bindings with their hash.

## 33. The pack seams: what a pack provides, loaded only where it is composed

ADR-0006, step 2: a pack's manifest declares what it provides beyond its vocabulary, and the engine
loads it only for a project that composes the pack. The core names no pack.

```bash
python3 -c "import json; print(json.dumps(json.load(open('oto/ontologies/policy/manifest.json'))['provides'], indent=1))"   # stages policy and iam, the command, the write hook
oto --help                                                                      # core commands, then each pack command under its pack, from the manifests
oto init --ontology data --project plain && oto build --project plain           # no "policy:" or "iam:" line: the stages belong to a pack the project does not compose
oto init --ontology policy --project ledger && oto build --project ledger       # "policy: 4 rule(s) ..." then "iam: 4 binding(s) ...": the pack's stages, before the site
oto arch export --framework calm --project <an architecture project>            # the adapter the calm pack provides
oto arch export --framework c4 --project <an architecture project>; echo $?     # 1: no adapter for framework 'c4': the packs on this machine provide calm
oto arch migrate --framework calm --by "<you>" --project <a project built before architecture release 5>   # calm_* become external_id, external_type, external_payload, framework, in the graph and in the project's vocabulary and questions; then oto build
# a pack of your own: a directory under $OTO_ONTOLOGIES with a manifest whose `provides` names your modules, which live in its code/ folder (carries: ["code", ...]); nothing to install
#   {"provides": {"stages": [{"name": "mine", "module": "mine_ext", "owns": []}], "commands": [{"name": "mine", "module": "mine_ext", "label": "mine"}],
#                 "endpoints": ["mine_ext"], "write_hooks": ["mine_ext:before_write"], "adapters": [{"framework": "mine", "module": "mine_ext", "import": "read_model", "export": "write_model"}]}}
oto ontology check --project <a project on it>                                  # the manifest checker holds the shapes of `provides`
```

Pass when a project without a pack never runs its stages, sees its routes or calls its write hook;
a project with the pack runs its stages after the core's targets and before the site, with their
outputs stashed by a partial build; the pack's command is in `oto --help` under its pack; an
endpoint the pack provides answers under `/api/` and is listed by `/api/tools`; the write hook's note
lands in the audit record of `curate apply`; an unknown framework is refused by name with the known
ones listed; and a manifest whose `provides` is the wrong shape is named by the checker.
