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
3. From a file you own: `oto ontology import --project acme --file vocab.ttl` (or `.csv`, `.json`).
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

Pass when the host lists fourteen `kg_*` tools, a proposal dropped into `proposals/` shows in `pending`
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

## 16. Actions: the graph's hands, described and never invoked

Exercises: the action files an ontology ships, the catalog, readiness, the intended status, a
recorded run becoming evidence through the gates, the act skill. (On the `actions` branch until
it merges.) The guided version, with a stand-in for GitHub so it needs no token, is
[scenarios/actions.md](scenarios/actions.md).

The software-architecture ontology ships `Repository`, `implemented_by`, a current sample
repository and three actions (`actions/`): a daily repository check and a create-repository
action bound to the GitHub MCP server, and a weekly read of what an `Interface` answers. Add an
intended repository to `graph.json` (`"status": "intended"`, `owner` and `name` attributes,
`implemented_by` from a component) to see the create action become ready. Or write one of your
own:

```bash
cat > acme/actions/action.check-repository.json <<'EOF'
{"id": "action.check-repository", "label": "Check that a repository exists",
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
oto actions check --project acme
oto actions list --project acme                                  # ready on the intended repository
oto actions show action.check-repository --on repo.payment-api --project acme   # the bound invocation
oto build --project acme && oto query --project acme actions --on repo.payment-api   # the same from the store
# invoke it yourself (gh api repos/<owner>/<name> > response.json), then:
oto actions record action.check-repository --on repo.payment-api --by "<you>" --response response.json --project acme
oto ingest --project acme
oto curate start --project acme && oto curate add --project acme --from acme/proposals/action.check-repository.<date>.json --dry-run
oto curate add --project acme --from acme/proposals/action.check-repository.<date>.json && oto curate check --project acme
oto curate apply --project acme --by "<you>" --note "the repository exists" && oto build --project acme
oto query --project acme entity repo.payment-api && oto query --project acme policy
oto actions list --project acme --due          # the daily check is due until it runs, then not until tomorrow
```

In repository mode (stage 11), `oto init --repo` also writes `.github/workflows/oto-actions.yml`
and `.github/scripts/oto-actions-invoke.py`; run the workflow by hand from the Actions tab once:
it invokes the due read-only actions it can (the interface probe over HTTP; the GitHub check is
bound to an MCP server and is skipped with a note), records them, and opens a pull request
labelled `oto-actions` with the run summary.

Pass when `oto ontology show software-architecture` lists three actions and `oto init` installs
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

## 17. The engine's own gates and CI

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
