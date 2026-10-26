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

Exercises: the `architecture` ontology on `software-architecture`, aligned with CALM 1.0, its shapes, AR1 to AR9.

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
oto arch import --calm tests/fixtures/calm/trading-system.architecture.json --at 2026-10-27 --environment environment.production --project trading
oto curate start --project trading && oto curate add --from proposals/calm-trading-system.json --project trading
oto curate check --project trading && oto curate apply --by "<you>" --note "the CALM model" --project trading
oto build --project trading
oto query --project trading ask AR1 NODE=component.web-gui                 # five connections over HTTPS
oto query --project trading ask SA1 SYSTEM=system.trading-system           # the estate's question, from the derived part_of and runs_in
oto arch export --calm --out trading.exported.json --project trading       # equals the input, up to empty containers
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
