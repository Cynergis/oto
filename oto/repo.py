# -*- coding: utf-8 -*-
"""A project that lives in a git repository on GitHub, and runs its pipeline there.

`oto init --repo` adds to a project what it needs to be pushed and operated as a repository:

    .mcp.json                        Claude Code opens the repo and has the kg_* tools, installed on demand
    CLAUDE.md                        what an agent must know about this repository
    .github/workflows/oto-ingest.yml on a push to inbox/: claim, extract, commit the run, open an issue on errors
    .github/workflows/oto-author.yml after an ingest: an agent drafts, applies, evaluates, and a PR is opened
    .github/workflows/oto-review.yml @claude on that PR: the agent revises on its branch
    .github/workflows/oto-checks.yml on a pull request: the gates, as status checks
    .github/workflows/oto-deploy.yml on a merge to main: build the store and publish it
    .github/workflows/oto-tools.yml   on a schedule: invoke the due read-only tools through the
                                      script under .github/scripts/, record, curate, open a PR
    .github/workflows/oto-route.yml  on a pull request and on every review: the route gate (session,
                                      guardrailed, reviewed) as a required check, docs/plans/graph-journeys.md
    .github/workflows/oto-preview.yml on a pull request: the store at its head, kept as an artifact of the run
                                      and linked in a comment; it holds no store token
    .github/oto-rules.json           the branch rules on main: pull requests required, the two checks,
                                      no approvals at the branch level but a code owner's for what the gate
                                      runs on; past them only main's deploy key and an
                                      administrator by a pull request; `oto repo rules --apply`, which also
                                      writes .github/CODEOWNERS and puts main's key in the environment oto-main
    .gitignore                       generated files ignored, EXCEPT the corpus, which is an input

The engine on a person's machine is the `oto` command installed there (ADR-0014), which the
project's server runs; in a workflow, `pip` installs it at the ref the lock records. Where the engine
lives is one string, `ENGINE`, overridable with `--engine` and, in the workflows, a repository variable.

The authoring and review workflows run Claude through the Claude Code Action with this engine's own
plugin loaded from its repository, so the pipeline agent follows the same skills a person's Claude
Code does; they need the repository secret ANTHROPIC_API_KEY. The deploy job keeps the store as a
workflow artifact, loads the self-hosted Neo4j when NEO4J_URI is set, publishes the store to the
query repository when OTO_QUERY_REPO is set, and the static site beside it when OTO_SITE_VIEW names
a view.
"""
import json
import os

ENGINE = "https://github.com/Cynergis/oto"
PIP = 'python -m pip install "oto-kg[intake] @ git+{engine}${{ENGINE_REF}}"'      # ENGINE_REF: "@<ref>" from the lock, set by PIN; empty without a lock

#: Before every install: the ref the lock records, so the same checks give the same verdicts and an
#: engine upgrade is a pull request that moves the lock (docs/plans/graph-journeys.md, phase 4). The
#: engine is not installed yet when this runs, so plain python reads the lock. Written into every
#: workflow by `files()`, right before the install step.
PIN = """      - name: Pin the engine to the lock
        run: |
          ref=$(python3 -c 'import json; e = (json.load(open("oto.lock.json")).get("engine") or {}); print(e.get("commit") or e.get("tag") or "")' 2>/dev/null || true)
          echo "ENGINE_REF=${ref:+@$ref}" >> "$GITHUB_ENV"
          echo "engine ref from oto.lock.json: ${ref:-none, the default branch}"
"""
INSTALL = "      - name: Install the engine from its repository\n"

GITIGNORE = """# build/ is generated and rebuilt by `oto build`, so it is not tracked: EXCEPT the corpus.
# build/documents/ is what ingest extracted from inbox/. It is an input to the build and to every
# review, so in a repository it is committed with the run that produced it.
build/*
!build/documents/
*.db
*.db.new
__pycache__/
# What `oto curate undo` restores. It changes on every apply, so tracking it conflicts on every merge.
graph.previous.json
"""

MCP = {"mcpServers": {"{slug}-kg": {"command": "oto", "args": ["serve", "--project", "."]}}}

CLAUDE_MD = """# {name}: an OTO knowledge project

This repository holds a knowledge graph's data and nothing else: the vocabulary, the curated graph,
the ledger, the raw documents at their stations, and the corpus extracted from them. The engine is
the `oto` command installed on the machine, once, at the release `oto.lock.json` records:
`uv tool install "oto-kg[intake,neo4j] @ git+{engine}@<that tag>"` (`oto lock --script` prints it). The OTO
plugin and this repository's server run that one. The engine repository is private: on a machine,
`gh auth login` then `gh auth setup-git` once, so `uv` and `pip` can clone it; in this repository's
workflows the secret `OTO_ENGINE_TOKEN` does the same.
The OTO plugin's skills (build-knowledge-base, curate, ontology-interview, vet-provenance,
query-knowledge, evaluate, capture, spec) are the playbooks for working here; `spec` drafts a
product spec or decision record from the graph and records its decisions back into it.

## How a change reaches main

Every pull request takes a route decided by what it carries, and one required check, `oto route`,
enforces the route's rule (docs/plans/graph-journeys.md in the engine). A change a person confirmed in
their Claude session (`oto curate apply --confirm`, one ledger entry whose fingerprint is the diff) is
the `session` route: it merges on its own once the confirmer is the author and the commits are verified.
A change drafted from documents is `reviewed`: one approving review of its head commit, by someone who
may write here and didn't write it, given in the preview that
`oto-preview.yml` builds for every pull request (the store at its head, kept as an artifact of the run). A change
drafted from the transcripts folder the project names is `guardrailed`. The branch rules that make the
check required are in `.github/oto-rules.json`; `oto repo rules --apply` sets them. A change to what the
gate runs on (`.github/`, `oto.lock.json`) needs the approval of a code owner `.github/CODEOWNERS` names,
which GitHub holds; the ingest and architecture workflows push to main with the deploy key kept in the
environment `oto-main`, which only main deploys from, and nothing else gets past the rules but an
administrator, by a pull request. Every workflow
installs the engine at the ref `oto.lock.json` records, and `oto checks` fails when the lock drifts;
an engine upgrade is `oto lock` on a branch and a pull request. A pull request that fell behind main
re-applies its facts with `oto route rebase --onto origin/main`, then commits and pushes.

## Where things are

| Path | Meaning |
|---|---|
| `inbox/` | documents nobody has claimed yet; pushing here triggers the ingest workflow |
| `processing/` | claimed by a run and extracted; the graph does not hold their facts yet |
| `errors/<run>/` | files a run could not extract, with a `.error.json` beside each |
| `archive/` | the graph holds them; only `oto ingest complete` moves files here |
| `runs/` | one manifest per ingest run, with content hashes |
| `build/documents/` | the corpus, committed because it is an input to the build and to review |
| `proposals/` | one file of proposed facts per document, the unit of drafting and review |
| `graph.json`, `ontology.config.json`, `ontology.rationale.json`, `lexicon.json` | the authored inputs |
| `changelog.jsonl` | the ledger: what the graph came to believe, when, and why |
| `rules.json` | rules over the graph: derived facts are marked and explained, never asserted |

## The rule

Nothing reaches `graph.json` on `main` except through a pull request. A push to `inbox/` runs the
ingest; the author workflow then drafts the run's proposals on a branch `oto/run-<id>`, applies them
through the curate gates, evaluates, and opens a pull request whose description is
`runs/<id>.report.md`: the recap, what changed, what is now answerable, what needs a person. The
gates run as status checks on it. A curator reads it and merges, or comments `@claude <what to
change>` and the agent revises on the branch. A merge to `main` builds and publishes the store.

Do not edit `build/` by hand except to inspect it. Do not edit `graph.json` directly; edit a candidate
through `oto curate` and let the pull request carry it.

## Serving

`oto serve` answers from the store named by `serve.backend` in `project.config.json`: `sqlite`,
the local `build/` of this checkout, or `neo4j`, the shared self-hosted database the deploy
workflow loads on every merge (repository variable `NEO4J_URI`, and `gh secret set NEO4J_PASSWORD --env oto-main`,
which only `main` deploys from). With
`neo4j`, a reader needs `NEO4J_PASSWORD` (and `NEO4J_USER`) in the environment and no local build;
the engine checks the connection at startup and says so, and never falls back on its own.
`oto serve --backend sqlite` serves the local build meanwhile. `oto status` reports which store
serves and whether Neo4j holds a load of this project.
"""

INGEST = """name: oto ingest

# A push that touches inbox/ claims the inbox into a run, extracts it, and commits the outcome:
# successes in processing/ with their corpus text, failures in errors/<run>/ with the reason beside
# each, and the run manifest. Serial by design: one run at a time.
#
# When this run succeeds, the "oto author" workflow follows: an agent drafts the proposals on a
# branch and opens the pull request that is the human gate.

on:
  push:
    branches: [ main ]
    paths: [ "inbox/**" ]
  workflow_dispatch:

concurrency:
  group: oto-ingest
  cancel-in-progress: false

permissions:
  contents: write
  issues: write

jobs:
  ingest:
    runs-on: ubuntu-latest
    # The run's commit is pushed to main with the deploy key kept in this environment, which only main
    # may deploy from, so a workflow on another branch or a pull request cannot read it; the branch rules
    # let that key past them, and no workflow's own token (oto repo rules --apply sets the three up).
    environment: oto-main
    steps:
      - uses: actions/checkout@v4
        with:
          ssh-key: ${{{{ secrets.OTO_MAIN_DEPLOY_KEY }}}}
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Reach the engine repository when it is private
        run: if [ -n "$OTO_ENGINE_TOKEN" ]; then git config --global url."https://x-access-token:${{OTO_ENGINE_TOKEN}}@github.com/".insteadOf "https://github.com/"; fi
        env:
          OTO_ENGINE_TOKEN: ${{{{ secrets.OTO_ENGINE_TOKEN }}}}
      - name: Install the engine from its repository
        run: {pip}
        env:
          ENGINE: ${{{{ vars.OTO_ENGINE || '{engine}' }}}}
      - name: Claim and extract
        id: ingest
        run: |
          set +e
          oto ingest --project . | tee ingest.log
          echo "exit=$?" >> "$GITHUB_OUTPUT"
      - name: Commit the run
        run: |
          git config user.name "oto ingest"
          git config user.email "oto-ingest@users.noreply.github.com"
          git add -A inbox processing errors runs build/documents
          git diff --cached --quiet || git commit -m "oto ingest: $(ls -t runs/*.json | head -1 | xargs -n1 basename | sed 's/.json$//') [skip ci]"
          git push
      - name: Open an issue for anything the run could not extract
        if: steps.ingest.outputs.exit != '0'
        env:
          GH_TOKEN: ${{{{ github.token }}}}
        run: |
          run_id=$(ls -t runs/*.json | head -1 | xargs -n1 basename | sed 's/.json$//')
          body=$(printf 'Run `%s` could not extract every file. Each is in `errors/%s/` with a `.error.json` beside it.\\n\\n```\\n%s\\n```\\n\\nFix the file and drop it back in `inbox/`.' "$run_id" "$run_id" "$(grep -E 'BLOCKED|UNSUPPORTED|SKIPPED|FAILED' ingest.log)")
          gh issue create --title "oto ingest $run_id: files need a person" --body "$body" --label oto-ingest || true
"""

ARCHITECTURE = """name: oto architecture

# Every merge to main compiles the architecture graph from what the repository holds: the framework
# model(s) and the code map that project.config.json names under `arch`, imported, held to the
# four gates and applied with the merge's sha in the note, then built (roadmap H2). A merge the
# gates refuse fails the job with the findings, and the graph stays as it was; nobody edits it by
# hand. Its own commit never compiles again. A project with no `arch` section does nothing here.

on:
  push:
    branches: [ main ]
  workflow_dispatch:

concurrency:
  group: oto-architecture
  cancel-in-progress: false

permissions:
  contents: write

jobs:
  compile:
    if: github.event.head_commit.author.name != 'oto architecture'
    runs-on: ubuntu-latest
    environment: oto-main             # main's deploy key pushes the compiled graph (see oto-ingest.yml)
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          ssh-key: ${{{{ secrets.OTO_MAIN_DEPLOY_KEY }}}}
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Reach the engine repository when it is private
        run: if [ -n "$OTO_ENGINE_TOKEN" ]; then git config --global url."https://x-access-token:${{OTO_ENGINE_TOKEN}}@github.com/".insteadOf "https://github.com/"; fi
        env:
          OTO_ENGINE_TOKEN: ${{{{ secrets.OTO_ENGINE_TOKEN }}}}
      - name: Install the engine from its repository
        run: {pip}
        env:
          ENGINE: ${{{{ vars.OTO_ENGINE || '{engine}' }}}}
      - name: Install the architecture pack, whose code compiles the graph (ADR-0011)
        run: oto pack add https://github.com/Cynergis/oto-registry.git --path packs/architecture
      - name: Compile the architecture from this merge
        run: |
          if python -c "import json,sys; sys.exit(0 if json.load(open('project.config.json')).get('arch') else 1)"; then
            oto arch compile --project . --at "$(date -u +%F)" --by "oto architecture" --note "compiled from ${{{{ github.sha }}}}"
          else
            echo "project.config.json declares no arch section: nothing to compile"
          fi
      - name: Commit the compiled graph
        run: |
          git config user.name "oto architecture"
          git config user.email "oto-architecture@users.noreply.github.com"
          git add -A graph.json changelog.jsonl audit.jsonl proposals archive build/documents 2>/dev/null || true
          git diff --cached --quiet || git commit -m "oto architecture: compiled from ${{{{ github.sha }}}} [skip ci]"
          git push
"""

CHECKS = """name: oto checks

# The gates, as status checks. A pull request that changes the graph, the vocabulary, the corpus or
# a candidate must pass them before a curator merges it. These are the same commands the playbooks
# run; running them here means the reviewer can trust the numbers in the pull request.

on:
  pull_request:
  workflow_dispatch:

permissions:
  contents: read
  pull-requests: write              # the impact of a changed decision record, as a comment

jobs:
  gates:
    name: oto checks                  # the name the branch rules require (.github/oto-rules.json)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Reach the engine repository when it is private
        run: if [ -n "$OTO_ENGINE_TOKEN" ]; then git config --global url."https://x-access-token:${{OTO_ENGINE_TOKEN}}@github.com/".insteadOf "https://github.com/"; fi
        env:
          OTO_ENGINE_TOKEN: ${{{{ secrets.OTO_ENGINE_TOKEN }}}}
      - name: Install the engine from its repository
        run: {pip}
        env:
          ENGINE: ${{{{ vars.OTO_ENGINE || '{engine}' }}}}
      - name: Where the project stands
        run: oto status --project .
      - name: The engine and the tools the lock records
        run: if [ -f oto.lock.json ]; then oto lock --check --project .; else echo "no lock yet (oto lock writes it)"; fi
      - name: Candidate, if one is open
        run: |
          if [ -f graph.candidate.json ]; then oto curate check --project .; else echo "no candidate open"; fi
      - name: Pre-flight and build
        run: oto build --project .
      - name: Vocabulary
        run: |
          oto ontology check --project . --strict
          oto ontology rationale --project . --strict || echo "::warning::some classes have no recorded reason"
      - name: Gold set, if one exists
        run: |
          if [ -f gold/questions.jsonl ]; then oto bench validate --project .; else echo "no gold set yet"; fi
      - name: Provenance
        run: oto vet --project . || echo "::warning::some facts cite documents the corpus does not hold"
      - name: Impact of the decision records this pull request changes
        # `oto arch` is the architecture pack's command (ADR-0011): on a project that does not compose it the
        # command is unknown, the report is empty and nothing is posted.
        if: github.event_name == 'pull_request'
        env:
          GH_TOKEN: ${{{{ github.token }}}}
        run: |
          changed=$(git diff --name-only "${{{{ github.event.pull_request.base.sha }}}}" "${{{{ github.event.pull_request.head.sha }}}}" -- 'docs/adr/' || true)
          if [ -n "$changed" ]; then
            report=$(oto arch impact --files $changed --format markdown --project . || true)
            if [ -n "$report" ]; then gh pr comment "${{{{ github.event.pull_request.number }}}}" --body "$report"; fi
          fi
"""

DEPLOY = """name: oto deploy

# A merge to main is the graph changing. Build the store from it and publish it. With the
# repository variable NEO4J_URI set (and NEO4J_PASSWORD as a secret), the graph is loaded into
# the self-hosted Neo4j and verified: that is the production store. With OTO_QUERY_REPO set (and
# OTO_QUERY_REPO_TOKEN, a token that can write to it, as a secret), the SQLite store is also
# published to that separate, read-only query repository, so readers need access to the store and
# not to the documents; `oto sync --repo <it>` brings it to a machine, and `oto serve` serves the
# checkout. With OTO_SITE_VIEW also set (a view's name, e.g. `explorer`), the static site
# is built with that app and published beside the store, for a reader with a browser and no
# engine. The store is kept as a workflow artifact either way.
#
# With a deploy config (oto.deploy.json, `oto deploy init`), the config names the query repository
# and the environments, and the build is published to the first it names. A later one is reached by
# a pull request on oto.promote.json, which stewards own (oto-promote.yml), since GitHub's Team plan
# has no required reviewers on an environment on a private repository. With the repository variable
# OTO_PROMOTE_ON_MERGE set to true, on a plan that has them, the promote jobs below copy the same store
# forward instead, one environment at a time, each behind a GitHub Environment of the same name whose
# required reviewers are the approvers. Without those reviewers they would promote every merge unapproved.
# The record on the branch names the commit and who ran the approved job.
#
# Keep these secrets in the environment {main_environment} (gh secret set NEO4J_PASSWORD --env {main_environment}), which
# only main deploys from, and never as repository secrets, which a workflow on any branch can read. A
# promote job reads from its own environment instead, so give that one its own token, and let only main
# deploy from it too (the repository's settings, Environments, Deployment branches).
#
# ENGINE is set once for each job, since the Neo4j load and the publish steps install or name the
# engine too. No job pushes to this repository, so the checkout keeps no credential: git would send
# it to the query repository in place of OTO_QUERY_REPO_TOKEN, and it can only see this repository.

on:
  push:
    branches: [ main ]
    paths:
      - "graph.json"
      - "ontology.config.json"
      - "lexicon.json"
      - "notes/**"
      - "build/documents/**"
  workflow_dispatch:

permissions:
  contents: read

jobs:
  build-and-publish:
    runs-on: ubuntu-latest
    environment: {main_environment}                # the deploy secrets are there: no other branch's workflow reads them
    env:
      ENGINE: ${{{{ vars.OTO_ENGINE || '{engine}' }}}}
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Reach the engine repository when it is private
        run: if [ -n "$OTO_ENGINE_TOKEN" ]; then git config --global url."https://x-access-token:${{OTO_ENGINE_TOKEN}}@github.com/".insteadOf "https://github.com/"; fi
        env:
          OTO_ENGINE_TOKEN: ${{{{ secrets.OTO_ENGINE_TOKEN }}}}
      - name: Install the engine from its repository
        run: {pip}
      - name: Build every layer
        run: oto build --project .
      - name: Check the deploy config, when the project has one, and name its environments
        id: has-config
        run: |
          if [ ! -f oto.deploy.json ]; then echo "deploy=false" >> "$GITHUB_OUTPUT"; exit 0; fi
          oto deploy check --project .
          python - <<'PY'
          import json, os
          names = [e["name"] for e in json.load(open("oto.deploy.json"))["environments"]]
          with open(os.environ["GITHUB_OUTPUT"], "a") as out:
              print("deploy=true", file=out)
              for key, name in zip(("first", "second", "third"), names):
                  print("%s=%s" % (key, name), file=out)
          if names[3:]:
              print("::warning::this workflow promotes through three environments; %s needs a promote job of its own" % ", ".join(names[3:]))
          PY
        env:
          HAS_CONFIG: ${{{{ hashFiles('oto.deploy.json') }}}}
      - name: Load the self-hosted Neo4j, when one is configured
        if: vars.NEO4J_URI != ''
        env:
          NEO4J_USER: ${{{{ vars.NEO4J_USER || 'neo4j' }}}}
          NEO4J_PASSWORD: ${{{{ secrets.NEO4J_PASSWORD }}}}
        run: |
          python -m pip install "oto-kg[neo4j] @ git+${{ENGINE}}"
          python - <<'PY'
          import json; c = json.load(open("project.config.json")); c.setdefault("neo4j", {{}})["uri"] = "${{{{ vars.NEO4J_URI }}}}"
          c["neo4j"].setdefault("database", "${{{{ vars.NEO4J_DATABASE || 'neo4j' }}}}"); json.dump(c, open("project.config.json", "w"), indent=2)
          PY
          oto build --project . --only neo4j --target neo4j --verify
      - name: Keep the store
        uses: actions/upload-artifact@v4
        with:
          name: knowledge-store
          path: build/{slug}.db
          if-no-files-found: error
      - name: Build the static site, when an app is named
        if: vars.OTO_QUERY_REPO != '' && vars.OTO_SITE_VIEW != ''
        run: oto build --project . --only site --target site --view "${{{{ vars.OTO_SITE_VIEW }}}}"
      - name: Publish the store to the query repository, when one is configured
        if: vars.OTO_QUERY_REPO != ''
        env:
          OTO_QUERY_REPO_TOKEN: ${{{{ secrets.OTO_QUERY_REPO_TOKEN }}}}
        run: oto publish --project . --repo "${{{{ vars.OTO_QUERY_REPO }}}}" --source "${{{{ github.repository }}}}@${{{{ github.sha }}}}" --engine "${{ENGINE}}" ${{{{ vars.OTO_SITE_VIEW != '' && '--site' || '' }}}}
      - name: Publish the build to the first environment, when the project has a deploy config
        if: steps.has-config.outputs.deploy == 'true'
        env:
          OTO_QUERY_REPO_TOKEN: ${{{{ secrets.OTO_QUERY_REPO_TOKEN }}}}
        run: oto publish --project . --to "${{{{ steps.has-config.outputs.first }}}}" --source "${{{{ github.repository }}}}@${{{{ github.sha }}}}" --engine "${{ENGINE}}"
    outputs:
      second: ${{{{ steps.has-config.outputs.second }}}}
      third: ${{{{ steps.has-config.outputs.third }}}}

  promote-second:
    needs: build-and-publish
    if: needs.build-and-publish.outputs.second != '' && vars.OTO_PROMOTE_ON_MERGE == 'true'
    runs-on: ubuntu-latest
    environment: ${{{{ needs.build-and-publish.outputs.second }}}}   # its required reviewers are the approvers named in oto.deploy.json
    env:
      ENGINE: ${{{{ vars.OTO_ENGINE || '{engine}' }}}}
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Reach the engine repository when it is private
        run: if [ -n "$OTO_ENGINE_TOKEN" ]; then git config --global url."https://x-access-token:${{OTO_ENGINE_TOKEN}}@github.com/".insteadOf "https://github.com/"; fi
        env:
          OTO_ENGINE_TOKEN: ${{{{ secrets.OTO_ENGINE_TOKEN }}}}
      - name: Install the engine from its repository
        run: {pip}
      - name: Promote the same store from the first environment
        env:
          OTO_QUERY_REPO_TOKEN: ${{{{ secrets.OTO_QUERY_REPO_TOKEN }}}}
        run: oto publish --project . --to "${{{{ needs.build-and-publish.outputs.second }}}}" --promote "${{{{ github.sha }}}}" --by "${{{{ github.actor }}}}" --approver github

  promote-third:
    needs: [ build-and-publish, promote-second ]
    if: needs.build-and-publish.outputs.third != '' && vars.OTO_PROMOTE_ON_MERGE == 'true'
    runs-on: ubuntu-latest
    environment: ${{{{ needs.build-and-publish.outputs.third }}}}
    env:
      ENGINE: ${{{{ vars.OTO_ENGINE || '{engine}' }}}}
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Reach the engine repository when it is private
        run: if [ -n "$OTO_ENGINE_TOKEN" ]; then git config --global url."https://x-access-token:${{OTO_ENGINE_TOKEN}}@github.com/".insteadOf "https://github.com/"; fi
        env:
          OTO_ENGINE_TOKEN: ${{{{ secrets.OTO_ENGINE_TOKEN }}}}
      - name: Install the engine from its repository
        run: {pip}
      - name: Promote the same store from the second environment
        env:
          OTO_QUERY_REPO_TOKEN: ${{{{ secrets.OTO_QUERY_REPO_TOKEN }}}}
        run: oto publish --project . --to "${{{{ needs.build-and-publish.outputs.third }}}}" --promote "${{{{ github.sha }}}}" --by "${{{{ github.actor }}}}" --approver github
"""


PROMOTE = """name: oto promote

# Promotion is a pull request (docs/plans/people-and-graphs.md): oto.promote.json names the commit each environment should
# hold, stewards own it, and merging it copies the same store forward, never a rebuild. Who approved the pull request is
# recorded as the approver, in PROMOTIONS.jsonl on the environment's branch.

on:
  push:
    branches: [ main ]
    paths: [ "oto.promote.json" ]

permissions:
  contents: read
  pull-requests: read

jobs:
  promote:
    runs-on: ubuntu-latest
    environment: {main_environment}                # the query repository's token is there: no other branch's workflow reads it
    env:
      ENGINE: ${{{{ vars.OTO_ENGINE || '{engine}' }}}}
      OTO_ENGINE_TOKEN: ${{{{ secrets.OTO_ENGINE_TOKEN }}}}
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Reach the engine repository when it is private
        run: if [ -n "$OTO_ENGINE_TOKEN" ]; then git config --global url."https://x-access-token:${{OTO_ENGINE_TOKEN}}@github.com/".insteadOf "https://github.com/"; fi
      - name: Install the engine from its repository
        run: {pip}
      - name: Who approved the pull request that merged this
        id: approver
        env:
          GH_TOKEN: ${{{{ github.token }}}}
        run: |
          pr=$(gh api "repos/${{{{ github.repository }}}}/commits/${{{{ github.sha }}}}/pulls" --jq '.[0].number')
          by=$(gh api "repos/${{{{ github.repository }}}}/pulls/$pr/reviews?per_page=100" --jq '[.[] | select(.state == "APPROVED")] | last | .user.login')
          echo "by=$by" >> "$GITHUB_OUTPUT"
      - name: Move each environment to the commit the file names
        env:
          OTO_QUERY_REPO_TOKEN: ${{{{ secrets.OTO_QUERY_REPO_TOKEN }}}}
        run: oto deploy promote --project . --by "${{{{ steps.approver.outputs.by }}}}"
"""

PACK_UPDATE = """name: oto pack update

# A new release of the pack this graph starts from reaches it as a pull request (docs/plans/people-and-graphs.md): the vocabulary re-derived, and
# what changed and which facts it touches in the description. It takes the reviewed route: nobody confirmed it. It needs the repository variable
# OTO_REGISTRY, the registry's git URL, and OTO_REGISTRY_TOKEN when that is private. In the repository's settings, under Actions, GitHub Actions
# must be allowed to create pull requests.

on:
  schedule:
    - cron: "41 4 * * 1"
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  update:
    if: vars.OTO_REGISTRY != ''
    runs-on: ubuntu-latest
    env:
      ENGINE: ${{{{ vars.OTO_ENGINE || '{engine}' }}}}
      OTO_ENGINE_TOKEN: ${{{{ secrets.OTO_ENGINE_TOKEN }}}}
      OTO_REGISTRY_TOKEN: ${{{{ secrets.OTO_REGISTRY_TOKEN }}}}
      GH_TOKEN: ${{{{ github.token }}}}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Reach the engine repository when it is private
        run: if [ -n "$OTO_ENGINE_TOKEN" ]; then git config --global url."https://x-access-token:${{OTO_ENGINE_TOKEN}}@github.com/".insteadOf "https://github.com/"; fi
      - name: Install the engine from its repository
        run: {pip}
      - name: Take the newest release, and open a pull request when anything moved
        run: |
          oto registry add "${{{{ vars.OTO_REGISTRY }}}}"
          pack=$(python -c 'import json; print(((json.load(open("project.config.json")).get("ontology") or {{}}).get("pack") or {{}}).get("name") or "")')
          if [ -z "$pack" ]; then echo "this graph starts from no pack: nothing to update"; exit 0; fi
          oto pack add "$pack" --force
          oto ontology diff --project . > update.md
          oto ontology update --project .
          if [ -z "$(git status --porcelain -- ontology.config.json project.config.json)" ]; then echo "already on the newest release of $pack"; exit 0; fi
          git config user.name "oto pack update"
          git config user.email "oto-pack-update@users.noreply.github.com"
          git checkout -b oto/pack-update
          git add ontology.config.json project.config.json
          git commit -m "A new release of the pack $pack"
          git push --force -u origin oto/pack-update
          gh pr view oto/pack-update --json number > /dev/null 2>&1 || gh pr create --head oto/pack-update --title "A new release of the pack $pack" --body-file update.md
"""

ACCESS = """name: oto access

# Permissions are a file, reviewed like code (.github/oto-access.json). When it changes on main, this sets GitHub to match;
# every day, it says whether GitHub has drifted from it. Both need OTO_ACCESS_TOKEN, a secret of the environment
# {main_environment} with admin on this repository and its store, which GITHUB_TOKEN isn't. Without it, this says so and does nothing.

on:
  push:
    branches: [ main ]
    paths: [ ".github/oto-access.json" ]
  schedule:
    - cron: "17 6 * * *"
  workflow_dispatch:

permissions:
  contents: read

jobs:
  access:
    runs-on: ubuntu-latest
    environment: {main_environment}
    env:
      ENGINE: ${{{{ vars.OTO_ENGINE || '{engine}' }}}}
      OTO_ENGINE_TOKEN: ${{{{ secrets.OTO_ENGINE_TOKEN }}}}
      GH_TOKEN: ${{{{ secrets.OTO_ACCESS_TOKEN }}}}
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Reach the engine repository when it is private
        run: if [ -n "$OTO_ENGINE_TOKEN" ]; then git config --global url."https://x-access-token:${{OTO_ENGINE_TOKEN}}@github.com/".insteadOf "https://github.com/"; fi
      - name: Install the engine from its repository
        run: {pip}
      - name: Set GitHub to match the file, when it changed
        if: github.event_name == 'push'
        run: if [ -n "$GH_TOKEN" ]; then oto repo access --apply --project . --repo "${{{{ github.repository }}}}"; else echo "no OTO_ACCESS_TOKEN in {main_environment}: the file is not applied"; fi
      - name: Say whether GitHub has drifted from it
        run: if [ -n "$GH_TOKEN" ]; then oto repo access --check --project . --repo "${{{{ github.repository }}}}"; else echo "no OTO_ACCESS_TOKEN in {main_environment}: nothing checked"; fi
"""

AUTHOR = r'''name: oto author

# The authoring step of the pipeline. When an ingest run has left documents in processing/, an
# agent drafts their proposals on a branch, runs them through the curate gates, applies with a
# ledger note, builds, evaluates, and writes runs/<run-id>.report.md. This workflow then commits
# the branch and opens a pull request with that report as its description.
#
# The pull request is the human gate. Every confirmation the playbook would ask a person for is a
# section of the report; a curator reads it and merges, or comments with @claude to revise (see
# oto-review.yml). Nothing reaches main here.
#
# Needs: the repository secret ANTHROPIC_API_KEY. Optional repository variables: OTO_ENGINE (the
# engine repository, also the plugin marketplace), OTO_MODEL (default claude-opus-5). When the
# engine repository is private, the secret OTO_ENGINE_TOKEN (a token that can read it) lets every
# workflow and the plugin marketplace clone it.

on:
  workflow_run:
    workflows: [ "oto ingest" ]
    types: [ completed ]
  workflow_dispatch:
    inputs:
      run_id:
        description: "ingest run to author (default: the latest open one)"
        required: false

concurrency:
  group: oto-author
  cancel-in-progress: false

permissions:
  contents: write
  pull-requests: write
  id-token: write

jobs:
  author:
    if: github.event_name == 'workflow_dispatch' || github.event.workflow_run.conclusion == 'success'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Reach the engine repository when it is private
        run: if [ -n "$OTO_ENGINE_TOKEN" ]; then git config --global url."https://x-access-token:${OTO_ENGINE_TOKEN}@github.com/".insteadOf "https://github.com/"; fi
        env:
          OTO_ENGINE_TOKEN: ${{ secrets.OTO_ENGINE_TOKEN }}
      - name: Install the engine from its repository
        run: @PIP@
        env:
          ENGINE: ${{ vars.OTO_ENGINE || '@ENGINE@' }}
      - name: Find the run to author
        id: run
        run: |
          run_id="${{ github.event.inputs.run_id }}"
          if [ -z "$run_id" ]; then run_id=$(oto ingest runs --project . --open | tail -1); fi
          if [ -z "$run_id" ]; then echo "nothing waits in processing/; nothing to author"; fi
          echo "id=$run_id" >> "$GITHUB_OUTPUT"
      - name: Start the branch
        if: steps.run.outputs.id != ''
        run: |
          git config user.name "oto pipeline"
          git config user.email "oto-pipeline@users.noreply.github.com"
          git checkout -b "oto/run-${{ steps.run.outputs.id }}"
      - name: Author the run
        if: steps.run.outputs.id != ''
        uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
          plugin_marketplaces: |
            ${{ vars.OTO_ENGINE || '@ENGINE@' }}.git
          plugins: |
            oto@cynergis-engine
          claude_args: |
            --model "${{ vars.OTO_MODEL || 'claude-opus-5' }}"
            --allowedTools "Bash(oto:*),Bash(ls:*),Bash(cat:*),Bash(head:*),Bash(tail:*),Bash(grep:*),Bash(find:*),Bash(wc:*),Bash(diff:*),Edit,Write,Read,Glob,Grep"
            --max-turns 200
          prompt: |
            You are the authoring step of the OTO pipeline, running unattended in this project
            repository on the branch oto/run-${{ steps.run.outputs.id }}. Ingest run
            ${{ steps.run.outputs.id }} has extracted documents into build/documents/; its manifest
            is runs/${{ steps.run.outputs.id }}.json.

            Load the build-knowledge-base skill and follow, exactly, its
            references/pipeline-run.md together with references/draft-proposal.md. Read CLAUDE.md
            in this repository first. Use `oto` for every check; never edit graph.json directly.
            When the manifest's `inbox` is the transcripts folder project.config.json names under
            `routes.guardrailed.from`, this is a transcripts run: follow the reference's section
            "A transcripts run" as well. In short: record each speaker's
            statement first (`oto curate assert --by <speaker> --at <date> --text ...`), draft every
            fact as that speaker's assertion (source_type human_assertion, citing the assertion and
            the transcript), add only the classes the settings allow, change or retire nothing, and
            keep within max_facts; `oto curate check` refuses a transcript's fact that is not an
            assertion.
            Do not commit, push, or run `oto ingest complete`: this workflow commits your working
            tree and opens the pull request with runs/${{ steps.run.outputs.id }}.report.md as its
            description. If you must stop, write that report with a first line `BLOCKED: <why>`.
      - name: Commit the branch and open the pull request
        if: steps.run.outputs.id != ''
        env:
          GH_TOKEN: ${{ github.token }}
          RUN_ID: ${{ steps.run.outputs.id }}
        run: |
          report="runs/${RUN_ID}.report.md"
          if [ ! -f "$report" ]; then
            printf 'BLOCKED: the authoring step produced no report.\n\nRead the workflow log for what happened.\n' > "$report"
          fi
          git add -A
          git diff --cached --quiet || git commit -m "oto author: run ${RUN_ID}"
          git push -u origin "oto/run-${RUN_ID}"
          labels="oto-run"
          title="oto run ${RUN_ID}: review and merge"
          if head -1 "$report" | grep -q '^BLOCKED:'; then labels="oto-run,blocked"; title="oto run ${RUN_ID}: BLOCKED, needs a person"; fi
          gh label create oto-run --description "opened by the OTO pipeline" --color 1D76DB 2>/dev/null || true
          gh label create blocked --description "the pipeline stopped and needs a person" --color B60205 2>/dev/null || true
          gh pr create --base main --head "oto/run-${RUN_ID}" --title "$title" --body-file "$report" --label "$labels"
'''

INVOKE_SCRIPT = r'''#!/usr/bin/env python3
"""Invoke the due tools of an OTO project and record their responses. Written by `oto init --repo`.

This script is the caller. OTO lists what is due (`oto tools list --due --json`), binds the
inputs (`oto tools show <id> --on <entity> --json`), and records what came back (`oto tools
record`); the invocation itself happens here, over the transport each action declares:

    http    the request, with `{input}` placeholders substituted (URL-encoded) in the URL and the
            body, and a header value that names an environment variable taken from the environment
    cli     the command ontology with each input substituted, shell-quoted
    script  the file under tools/ run with the inputs as JSON on stdin
    mcp     skipped: an MCP tool needs an agent (the act skill), not a cron job

Only read-only scheduled tools are ever due, so nothing here changes the world. Environment
variable values are never printed; a missing one skips the action and says its name. Responses
are read up to one megabyte. Standard library only.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_-]+)\}")
READ_LIMIT = 1_000_000


def oto(args, base):
    out = subprocess.run(base + args, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("%s failed: %s" % (" ".join(args[:2]), (out.stderr or out.stdout).strip()[-400:]))
    return out.stdout


def substitute(ontology, inputs, quote):
    return PLACEHOLDER.sub(lambda m: quote(str(inputs.get(m.group(1), m.group(0)))), ontology)


def _url_part(value):
    """An input that is itself an absolute URL (an interface's base URL) stands as it is; any other
    input is URL-encoded before it enters the ontology."""
    return value if re.match(r"^https?://", value) else urllib.parse.quote(value, safe="")


def invoke_http(invoke, inputs, timeout):
    url = substitute(invoke["url"], inputs, _url_part)
    headers = {}
    for name, value in (invoke.get("headers") or {}).items():
        if isinstance(value, str) and ENV_NAME.match(value) and value in os.environ:
            value = os.environ[value]
        headers[name] = substitute(str(value), inputs, lambda v: v)
    body = invoke.get("body")
    data = None
    if body is not None:
        text = body if isinstance(body, str) else json.dumps(body)
        data = substitute(text, inputs, lambda v: json.dumps(v)[1:-1]).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=headers, method=(invoke.get("method") or "GET").upper())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(READ_LIMIT).decode("utf-8", "replace")


def invoke_cli(invoke, inputs, timeout):
    command = substitute(invoke["command"], inputs, shlex.quote)
    out = subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError("exit %d: %s" % (out.returncode, out.stderr.strip()[-400:]))
    return out.stdout[:READ_LIMIT]


def invoke_script(invoke, inputs, timeout, project):
    path = os.path.join(project, "tools", invoke["path"])
    if not os.path.exists(path):
        path = os.path.join(project, "actions", invoke["path"])      # a project made before the rename
    out = subprocess.run([path], input=json.dumps(inputs), capture_output=True, text=True, timeout=timeout, cwd=project)
    if out.returncode != 0:
        raise RuntimeError("exit %d: %s" % (out.returncode, out.stderr.strip()[-400:]))
    return out.stdout[:READ_LIMIT]


def main(argv=None):
    parser = argparse.ArgumentParser(description="invoke the due tools of an OTO project and record their responses")
    parser.add_argument("--project", default=".")
    parser.add_argument("--oto", default="oto", help="the engine command (default: oto)")
    parser.add_argument("--by", default="oto tools workflow", help="who the runs are recorded by")
    parser.add_argument("--at", default=None, help="the run date (default: today)")
    parser.add_argument("--only", default=None, help="one action id")
    parser.add_argument("--summary", default=None, help="write the summary JSON here as well")
    args = parser.parse_args(argv)
    base = shlex.split(args.oto)
    project = os.path.abspath(args.project)
    due = json.loads(oto(["tools", "list", "--due", "--json", "--project", project], base) or "[]")
    summary = {"invoked": [], "skipped": [], "failed": []}
    for definition in due:
        aid = definition["name"]
        if args.only and aid != args.only:
            continue
        m = definition["oto"]
        for entity in m.get("ready_on") or []:
            bound = json.loads(oto(["tools", "show", aid, "--on", entity, "--json", "--project", project], base))["oto"]
            item = {"action": aid, "on": entity, "transport": (bound.get("invoke") or {}).get("transport")}
            missing_env = [n for n in bound.get("needs") or [] if n not in os.environ]
            if bound.get("inputs_missing"):
                summary["skipped"].append(dict(item, why="inputs the caller must supply: %s" % ", ".join(bound["inputs_missing"])))
                continue
            if missing_env:
                summary["skipped"].append(dict(item, why="environment variable(s) not set: %s" % ", ".join(missing_env)))
                continue
            invoke = bound.get("invoke") or {}
            timeout = int(bound.get("timeout") or 60)
            try:
                if invoke.get("transport") == "http":
                    response = invoke_http(invoke, bound["inputs"], timeout)
                elif invoke.get("transport") == "cli":
                    response = invoke_cli(invoke, bound["inputs"], timeout)
                elif invoke.get("transport") == "script":
                    response = invoke_script(invoke, bound["inputs"], timeout, project)
                else:
                    summary["skipped"].append(dict(item, why="an MCP tool needs an agent (the act skill), not a schedule"))
                    continue
            except (urllib.error.URLError, subprocess.TimeoutExpired, RuntimeError, OSError, ValueError) as exc:
                summary["failed"].append(dict(item, why=str(exc)[:400]))
                continue
            with tempfile.NamedTemporaryFile("w", suffix=".response", delete=False, encoding="utf-8") as f:
                f.write(response)
                path = f.name
            try:
                record_args = ["tools", "record", aid, "--on", entity, "--by", args.by, "--response", path,
                               "--note", "invoked by the tools workflow", "--project", project]
                if args.at:
                    record_args += ["--at", args.at]
                out = oto(record_args, base)
            except RuntimeError as exc:
                summary["failed"].append(dict(item, why=str(exc)[:400]))
                continue
            finally:
                os.unlink(path)
            proposal = next((line.split("proposal:", 1)[1].strip() for line in out.splitlines() if "proposal:" in line), None)
            summary["invoked"].append(dict(item, proposal=proposal))
    text = json.dumps(summary, indent=2)
    print(text)
    if args.summary:
        with open(args.summary, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

ACTIONS = r'''name: oto tools

# The graph's hands, on a schedule. Every day this lists the read-only tools the project declares
# that are due (`oto tools list --due`), invokes each through the transport it declares with the
# script under .github/scripts/ (OTO itself never invokes), records the responses as run records
# and source documents, takes the proposals through the curate gates, and opens a pull request:
# the merge is the human gate, as for every other change. An action bound to an MCP server is
# skipped here; it needs an agent (the act skill). Nothing that changes the world is ever due.
#
# For every environment variable an action `needs`, add a repository secret of that name and list
# it under `env:` below; GITHUB_TOKEN is provided by GitHub. Values never reach the run records.

on:
  schedule:
    - cron: "17 5 * * *"
  workflow_dispatch:
    inputs:
      only:
        description: "one action id (default: every due action)"
        required: false

concurrency:
  group: oto-tools
  cancel-in-progress: false

permissions:
  contents: write
  pull-requests: write

jobs:
  invoke-and-record:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Reach the engine repository when it is private
        run: if [ -n "$OTO_ENGINE_TOKEN" ]; then git config --global url."https://x-access-token:${OTO_ENGINE_TOKEN}@github.com/".insteadOf "https://github.com/"; fi
        env:
          OTO_ENGINE_TOKEN: ${{ secrets.OTO_ENGINE_TOKEN }}
      - name: Install the engine from its repository
        run: @PIP@
        env:
          ENGINE: ${{ vars.OTO_ENGINE || '@ENGINE@' }}
      - name: Invoke what is due and record it
        id: invoke
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          # OTHER_API_TOKEN: ${{ secrets.OTHER_API_TOKEN }}
        run: |
          python .github/scripts/oto-tools-invoke.py --project . --summary runs/tools/last-workflow.json ${{ inputs.only && format('--only {0}', inputs.only) || '' }}
          echo "invoked=$(python -c 'import json; print(len(json.load(open("runs/tools/last-workflow.json"))["invoked"]))')" >> "$GITHUB_OUTPUT"
      - name: Take the proposals through the gates
        if: steps.invoke.outputs.invoked != '0'
        run: |
          oto ingest --project .
          oto curate start --project .
          python - <<'PY'
          import json, subprocess
          s = json.load(open("runs/tools/last-workflow.json"))
          for item in s["invoked"]:
              if item.get("proposal"):
                  subprocess.run(["oto", "curate", "add", "--project", ".", "--from", item["proposal"]], check=False)
          PY
          if oto curate check --project .; then
            oto curate apply --project . --by "oto tools workflow" --note "recorded runs of the due tools; see runs/tools/last-workflow.json"
            oto build --project .
          else
            echo "the candidate needs a person: left open, the pull request says why"
          fi
      - name: Open the pull request
        if: steps.invoke.outputs.invoked != '0'
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          set -e
          stamp="$(date -u +%Y-%m-%d-%H%M)"
          git config user.name "oto tools"
          git config user.email "oto-tools@users.noreply.github.com"
          git checkout -b "oto/tools-${stamp}"
          git add -A
          git diff --cached --quiet && { echo "nothing changed"; exit 0; }
          git commit -m "oto tools: recorded runs of the due tools (${stamp})"
          git push -u origin "oto/tools-${stamp}"
          {
            echo "## Recorded runs of the due tools"
            echo
            echo "Invoked by the tools workflow; each response is a run record and a source document, and a proposal went through the gates."
            echo
            echo '```json'; cat runs/tools/last-workflow.json; echo '```'
            echo
            if [ -f graph.candidate.json ]; then echo "**The candidate is still open**: \`oto curate check\` was not clean. A person decides."; fi
          } > /tmp/pr-body.md
          gh label create oto-tools --description "opened by the OTO tools workflow" --color 0E8A16 2>/dev/null || true
          gh pr create --base main --head "oto/tools-${stamp}" --title "oto tools: recorded runs (${stamp})" --body-file /tmp/pr-body.md --label oto-tools
'''

REVIEW = r'''name: oto review

# A curator comments on a pipeline pull request with @claude and what to change; the agent revises
# on the pull request's branch with the same skills, and pushes. The gates run again on the push.
# This is the conversation half of the human gate.
#
# Needs: the repository secret ANTHROPIC_API_KEY.

on:
  issue_comment:
    types: [ created ]
  pull_request_review_comment:
    types: [ created ]

permissions:
  contents: write
  pull-requests: write
  issues: write
  id-token: write

jobs:
  revise:
    if: |
      (github.event_name == 'issue_comment' && github.event.issue.pull_request && contains(github.event.comment.body, '@claude')) ||
      (github.event_name == 'pull_request_review_comment' && contains(github.event.comment.body, '@claude'))
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Reach the engine repository when it is private
        run: if [ -n "$OTO_ENGINE_TOKEN" ]; then git config --global url."https://x-access-token:${OTO_ENGINE_TOKEN}@github.com/".insteadOf "https://github.com/"; fi
        env:
          OTO_ENGINE_TOKEN: ${{ secrets.OTO_ENGINE_TOKEN }}
      - name: Install the engine from its repository
        run: @PIP@
        env:
          ENGINE: ${{ vars.OTO_ENGINE || '@ENGINE@' }}
      - name: Revise as asked
        uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
          plugin_marketplaces: |
            ${{ vars.OTO_ENGINE || '@ENGINE@' }}.git
          plugins: |
            oto@cynergis-engine
          claude_args: |
            --model "${{ vars.OTO_MODEL || 'claude-opus-5' }}"
            --allowedTools "Bash(oto:*),Bash(ls:*),Bash(cat:*),Bash(head:*),Bash(tail:*),Bash(grep:*),Bash(find:*),Bash(wc:*),Bash(diff:*),Bash(git:*),Edit,Write,Read,Glob,Grep"
            --max-turns 100
'''


ROUTE = """name: oto route

# The route gate (docs/plans/graph-journeys.md). A pull request enters main by the route its content
# decides: session (one ledger entry with a confirmation whose fingerprint is the fact-level diff),
# guardrailed (ingest runs from the transcripts folder the project names), reviewed (anything else).
# This check enforces the route's rule. It hands the engine the facts only GitHub knows, as flags: the
# pull request's author and the commits' authors, whether every commit is verified, whether someone
# qualified approved it. GitHub lets anyone with read access review, so an approval counts when it is of
# this very commit, by someone who didn't write it and who may write here, and whom the base's
# .github/oto-access.json names when it names anyone. The engine never calls GitHub. When a session record does not hold, or a guardrail
# fails, the route moves to reviewed: the pull request is labelled and the reason posted, and a
# person decides. The branch rules in .github/oto-rules.json make this check required.

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
  pull_request_review:
    types: [submitted, dismissed]

permissions:
  contents: read
  pull-requests: write              # the label and the comment when the route moves to reviewed
  issues: write                     # labels are issue labels

jobs:
  route:
    name: oto route                 # the name the branch rules require
    runs-on: ubuntu-latest
    env:
      ENGINE: ${{{{ vars.OTO_ENGINE || '{engine}' }}}}
      OTO_ENGINE_TOKEN: ${{{{ secrets.OTO_ENGINE_TOKEN }}}}
      OTO_TEAMS_TOKEN: ${{{{ secrets.OTO_TEAMS_TOKEN }}}}   # read:org, only when the access file names a team
      GH_TOKEN: ${{{{ github.token }}}}
      PR: ${{{{ github.event.pull_request.number }}}}
      BASE: ${{{{ github.event.pull_request.base.ref }}}}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0            # both trees: the base and the head
          ref: ${{{{ github.event.pull_request.head.sha }}}}
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Reach the engine repository when it is private
        run: if [ -n "$OTO_ENGINE_TOKEN" ]; then git config --global url."https://x-access-token:${{OTO_ENGINE_TOKEN}}@github.com/".insteadOf "https://github.com/"; fi
      - name: Install the engine from its repository
        run: {pip}
      - name: What GitHub knows about the pull request
        id: facts
        run: |
          authors=$(gh pr view "$PR" --json author,commits --jq '[.author.login] + [.commits[].authors[].login, .commits[].authors[].email] | map(select(. != null and . != "")) | unique | .[]')
          flags=""
          for a in $authors; do flags="$flags --author $a"; done
          if [ "$(gh api "repos/${{{{ github.repository }}}}/pulls/$PR/commits" --jq '[.[].commit.verification.verified] | all')" = "true" ]; then flags="$flags --verified"; fi
          gh api "repos/${{{{ github.repository }}}}/pulls/$PR/reviews?per_page=100" > reviews.json
          oto route approvers --project . --reviews reviews.json --base "origin/$BASE" $flags > approvers.txt
          while read -r login teams; do
            case "$(gh api "repos/${{{{ github.repository }}}}/collaborators/$login/permission" --jq .permission 2>/dev/null)" in
              admin|write) ;;
              *) continue ;;
            esac
            counts=""
            if [ -z "$teams" ]; then counts=yes; fi
            for team in $teams; do
              # reading a team needs a token GITHUB_TOKEN isn't: with no OTO_TEAMS_TOKEN the lookup fails, and the approval doesn't count
              if [ "$(GH_TOKEN="${{OTO_TEAMS_TOKEN:-$GH_TOKEN}}" gh api "orgs/${{team%%/*}}/teams/${{team##*/}}/memberships/$login" --jq .state 2>/dev/null)" = "active" ]; then counts=yes; fi
            done
            if [ -n "$counts" ]; then flags="$flags --approved"; break; fi
          done < approvers.txt
          echo "flags=$flags" >> "$GITHUB_OUTPUT"
      - name: The route and its verdict
        id: verdict
        run: |
          set +e
          oto route check --project . --base "origin/$BASE" --head HEAD ${{{{ steps.facts.outputs.flags }}}} --json > route.json
          echo "code=$?" >> "$GITHUB_OUTPUT"
          oto route check --project . --base "origin/$BASE" --head HEAD ${{{{ steps.facts.outputs.flags }}}} || true
      - name: Say so on the pull request when the route moved or the gate does not pass
        if: always() && steps.verdict.outputs.code != ''
        run: |
          route=$(jq -r .route route.json); proposed=$(jq -r .proposed route.json); ok=$(jq -r .ok route.json)
          if [ "$route" != "$proposed" ]; then
            gh label create "oto-route:reviewed" --description "the route moved to reviewed: a person decides" --color B3261E --force
            gh pr edit "$PR" --add-label "oto-route:reviewed"
          fi
          if [ "$ok" != "true" ] || [ "$route" != "$proposed" ]; then
            jq -r '"**oto route**: `\\(.route)`" + (if .proposed != .route then " (the content asked for `\\(.proposed)`)" else "" end) + (if .ok then ": passes" else ": does not pass yet" end) + "\\n\\n" + (.reasons | map("- " + .) | join("\\n"))' route.json > route.md
            gh pr comment "$PR" --body-file route.md
          fi
      - name: The gate
        run: test "${{{{ steps.verdict.outputs.code }}}}" = "0"
"""

PREVIEW = """name: oto preview

# A preview of the graph for every pull request (docs/plans/graph-journeys.md, phase 4). A diff of
# graph.json cannot be reviewed for what it says; the store built from the head can. It is kept as an
# artifact of this run, with the workbench beside it when OTO_SITE_VIEW names an app, and one comment on
# the pull request says how to read it and is edited on every push. This workflow runs from any branch,
# so it holds no store token: a contributor's branch could read one from here.

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

env:
  PR: ${{{{ github.event.pull_request.number }}}}

jobs:
  preview:
    runs-on: ubuntu-latest
    env:
      ENGINE: ${{{{ vars.OTO_ENGINE || '{engine}' }}}}
      OTO_ENGINE_TOKEN: ${{{{ secrets.OTO_ENGINE_TOKEN }}}}
      GH_TOKEN: ${{{{ github.token }}}}
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{{{ github.event.pull_request.head.sha }}}}
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Reach the engine repository when it is private
        run: if [ -n "$OTO_ENGINE_TOKEN" ]; then git config --global url."https://x-access-token:${{OTO_ENGINE_TOKEN}}@github.com/".insteadOf "https://github.com/"; fi
      - name: Install the engine from its repository
        run: {pip}
      - name: Build the store at the head of the pull request
        run: oto build --project .
      - name: Build the workbench when an app is named
        if: vars.OTO_SITE_VIEW != ''
        run: oto build --project . --only site --target site --view "${{{{ vars.OTO_SITE_VIEW }}}}"
      - name: Keep them as an artifact of this run
        uses: actions/upload-artifact@v4
        with:
          name: preview-pr-${{{{ github.event.pull_request.number }}}}
          path: |
            build/{slug}.db
            build/site
          retention-days: 14
      - name: Say where the preview is, in one comment kept up to date
        run: |
          printf '%s\\n\\n%s\\n' "**oto preview**: the store at ${{{{ github.event.pull_request.head.sha }}}} is the artifact preview-pr-${{PR}} of run ${{{{ github.run_id }}}}." \\
            "- read it in a fresh checkout of this branch: gh run download ${{{{ github.run_id }}}} -n preview-pr-${{PR}} -D build, then oto serve --project . --http 8765" > preview.md
          gh pr comment "$PR" --edit-last --body-file preview.md || gh pr comment "$PR" --body-file preview.md
"""

#: The branch rules on main, as a GitHub ruleset. Pull requests required; the two checks required
#: and up to date; no approvals at the branch level, because approvals are the route gate's, per
#: route, except a code owner's for the files the gate itself runs on. Up to date, so graph.json merges
#: one pull request at a time, and whoever is behind runs `oto route rebase`. Past them: main's deploy key, which the ingest and architecture
#: workflows push with from an environment only main deploys from, and an administrator by a pull
#: request. Never GitHub Actions: any workflow on any branch can ask for its token. Keys starting with
#: `_` are for the reader and are stripped before the ruleset is sent.
RULES_NAME = "oto main"
RULES_FILE = os.path.join(".github", "oto-rules.json")
ADMIN_ROLE = 5                                    # the repository role "admin", as rulesets name it
MAINTAIN_ROLE = 2                                 # the repository role "maintain"
TAG_RULES_FILE = os.path.join(".github", "oto-tag-rules.json")
RELEASE_ENVIRONMENT = "oto-release"               # deploys from release tags alone; holds the registry's token
MAIN_ENVIRONMENT = "oto-main"                     # deploys from the default branch alone; holds main's key
DEPLOY_KEY_SECRET = "OTO_MAIN_DEPLOY_KEY"
DEPLOY_KEY_TITLE = "oto main pushes"
CODEOWNERS_FILE = os.path.join(".github", "CODEOWNERS")
OWNED = ("/.github/", "/oto.lock.json", "/oto.promote.json")     # what the gate runs on: its workflows, rules and access file, the engine's pin; and what promotes a build
WORKSPACE_OWNED = ("/.github/", "/ontology/", "/manifest.json")     # on a pack workspace: and what every graph on the pack depends on
RULES = {
    "_about": "The branch rules on main, set by `oto repo rules --apply` (or by `oto sandbox up --repo` when it creates the repository). "
              "Pull requests required; the checks `oto checks` and `oto route` required; zero approvals here, because the route gate "
              "requires them per route (docs/plans/graph-journeys.md), except a code owner's for the files the gate runs on "
              "(.github/CODEOWNERS: the workflows, these rules, the lock), which GitHub holds and no workflow can answer for. The checks "
              "must be up to date, so graph.json merges one pull request at a time and whoever is behind runs `oto route rebase`. Past them: the deploy key the ingest and architecture workflows "
              "push to main with, kept in the environment oto-main that only main deploys from, and an administrator, by a pull request "
              "and visibly. Never GitHub Actions itself: any workflow on any branch can ask for its token.",
    "name": RULES_NAME,
    "target": "branch",
    "enforcement": "active",
    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
    "bypass_actors": [{"actor_id": None, "actor_type": "DeployKey", "bypass_mode": "always"},
                      {"actor_id": ADMIN_ROLE, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}],
    "rules": [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "pull_request", "parameters": {"required_approving_review_count": 0, "dismiss_stale_reviews_on_push": False,
                                                "require_code_owner_review": True, "require_last_push_approval": False,
                                                "required_review_thread_resolution": False}},
        {"type": "required_status_checks", "parameters": {"strict_required_status_checks_policy": True, "do_not_enforce_on_create": False,
                                                          "required_status_checks": [{"context": "oto checks"}, {"context": "oto route"}]}},
    ],
}


def rules_text():
    return json.dumps(RULES, indent=2, ensure_ascii=False) + "\n"


#: A pack workspace's branch rules (docs/plans/people-and-graphs.md, phase 2): a vocabulary is changed the way code is, so a
#: pull request, the check, one approval and a code owner's on what graphs depend on, with nothing past them but an
#: administrator by a pull request. No deploy key: a workspace's workflows never push to its main.
WORKSPACE_RULES = {
    "_about": "The branch rules on a pack workspace's main, set by `oto repo rules --apply`. Pull requests required; the check `pack check` required and up "
              "to date; one approval, and a code owner's for the vocabulary and the manifest, which every graph on the pack depends on (.github/CODEOWNERS). "
              "Past them only an administrator, by a pull request, and visibly.",
    "name": RULES_NAME,
    "target": "branch",
    "enforcement": "active",
    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
    "bypass_actors": [{"actor_id": ADMIN_ROLE, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}],
    "rules": [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "pull_request", "parameters": {"required_approving_review_count": 1, "dismiss_stale_reviews_on_push": True,
                                                "require_code_owner_review": True, "require_last_push_approval": False,
                                                "required_review_thread_resolution": False}},
        {"type": "required_status_checks", "parameters": {"strict_required_status_checks_policy": True, "do_not_enforce_on_create": False,
                                                          "required_status_checks": [{"context": "pack check"}]}},
    ],
}
#: Who may release: a tag v<anything> starts `pack publish`, so only maintainers and administrators may make, move or delete one
TAG_RULES = {
    "_about": "A tag v<anything> on a pack workspace publishes the pack to the registry, so only a maintainer or an administrator may make, move or delete one.",
    "name": "oto release tags",
    "target": "tag",
    "enforcement": "active",
    "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
    "bypass_actors": [{"actor_id": ADMIN_ROLE, "actor_type": "RepositoryRole", "bypass_mode": "always"},
                      {"actor_id": MAINTAIN_ROLE, "actor_type": "RepositoryRole", "bypass_mode": "always"}],
    "rules": [{"type": "creation"}, {"type": "update"}, {"type": "deletion"}],
}


def workspace_rules_text():
    return json.dumps(WORKSPACE_RULES, indent=2, ensure_ascii=False) + "\n"


def tag_rules_text():
    return json.dumps(TAG_RULES, indent=2, ensure_ascii=False) + "\n"


def _owner_name(repo):
    """`owner/name` from that, or from a GitHub URL."""
    value = (repo or "").strip()
    for prefix in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value[:-len(".git")] if value.endswith(".git") else value


def origin_repository(root):
    """`owner/name` of the repository `origin` points at, or None."""
    import subprocess
    done = subprocess.run(["git", "-C", root, "remote", "get-url", "origin"], capture_output=True, text=True)
    if done.returncode != 0 or not done.stdout.strip():
        return None
    name = _owner_name(done.stdout.strip())
    return name if "/" in name and "github.com" not in name else None


def _handle(owner):
    owner = (owner or "").strip()
    return owner if owner.startswith("@") else "@" + owner


def is_workspace(root):
    """A pack workspace rather than a knowledge project: a pack's manifest, and no project config of its own."""
    return os.path.exists(os.path.join(root, "manifest.json")) and not os.path.exists(os.path.join(root, "project.config.json"))


def code_owners_text(owner, owned=OWNED):
    """`.github/CODEOWNERS`: `owner` (a login, or an organisation's team as org/team) owns what the route
    gate runs on, so the branch rules' code-owner review holds a change to it at GitHub, where no workflow
    can answer for it."""
    if owned is WORKSPACE_OWNED:
        head = ["# Written by `oto repo rules --apply`. A pack workspace's code owners: its workflows and rules under .github/, and",
                "# the vocabulary and manifest every graph on the pack depends on. The branch rules require their approval.",
                ""]
        return "\n".join(head + ["%-16s %s" % (path, _handle(owner)) for path in owned]) + "\n"
    head = ["# Written by `oto repo rules --apply`. What the route gate runs on: its workflows and rules under",
            "# .github/, and the lock that pins the engine they install. The branch rules (.github/oto-rules.json)",
            "# require a code owner's approval for a change to these, which GitHub holds: a pull request cannot",
            "# rewrite the gate's workflow, add one that answers to its check's name, or move the engine (ADR-0013).",
            ""]
    return "\n".join(head + ["%-16s %s" % (path, _handle(owner)) for path in OWNED]) + "\n"


def code_owner_of(root):
    """The owner `.github/CODEOWNERS` names for .github/, or None when there is no such file."""
    try:
        with open(os.path.join(root, CODEOWNERS_FILE), encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if parts and parts[0] == OWNED[0] and len(parts) > 1:
                    return parts[1]
    except OSError:
        return None
    return None


def write_code_owners(root, owner):
    """Write `.github/CODEOWNERS` naming `owner`. Returns the handle written."""
    path = os.path.join(root, CODEOWNERS_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(code_owners_text(owner, WORKSPACE_OWNED if is_workspace(root) else OWNED))
    return _handle(owner)


def _github(token=None, gh=None):
    """A runner for the GitHub CLI: run(*args, stdin=None) -> (code, out, err). The token, when given,
    reaches the CLI through its environment and never a file or an argument."""
    import shutil
    import subprocess
    from .project import ProjectError
    gh = gh or os.environ.get("OTO_GH") or shutil.which("gh")
    if not gh or not os.path.exists(gh):
        raise ProjectError("the GitHub CLI (gh) is not on this computer, and setting up the repository needs it")
    env = dict(os.environ, GH_TOKEN=token) if token else dict(os.environ)

    def run(*args, stdin=None, timeout=120):
        done = subprocess.run([gh] + list(args), input=stdin, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, env=env)
        return done.returncode, done.stdout, done.stderr
    return run


def _json(text, default):
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def github_login(token=None, gh=None):
    """The login of whoever the GitHub CLI is signed in as (or the token belongs to), or None."""
    code, out, _err = _github(token, gh)("api", "user")
    return _json(out, {}).get("login") if code == 0 else None


def _main_key(run, owner_name, default_branch):
    """Main's deploy key: a fresh ed25519 pair, the public half a write deploy key of the repository, the
    private half the secret OTO_MAIN_DEPLOY_KEY of the environment oto-main, which deploys from the default
    branch alone; the key it replaces is removed. The private half is made in a private temporary folder
    and reaches the CLI on its stdin, never as an argument, and the folder is removed. Returns the key's id."""
    import shutil
    import subprocess
    import tempfile
    from .project import ProjectError

    def must(step, result):
        code, out, err = result
        if code != 0:
            raise ProjectError("could not %s on %s: %s" % (step, owner_name, (err or out).strip()[-400:]))
        return out

    keygen = os.environ.get("OTO_SSH_KEYGEN") or shutil.which("ssh-keygen")
    if not keygen or not os.path.exists(keygen):
        raise ProjectError("ssh-keygen is not on this computer, and making main's deploy key needs it")
    folder = tempfile.mkdtemp(prefix="oto-main-key-")
    try:
        path = os.path.join(folder, "key")
        done = subprocess.run([keygen, "-t", "ed25519", "-N", "", "-q", "-C", "%s, %s" % (DEPLOY_KEY_TITLE, owner_name), "-f", path],
                              capture_output=True, text=True, timeout=60)
        if done.returncode != 0:
            raise ProjectError("ssh-keygen could not make main's deploy key: %s" % (done.stderr or done.stdout).strip()[-300:])
        with open(path + ".pub", encoding="utf-8") as f:
            public = f.read().strip()
        with open(path, encoding="utf-8") as f:
            private = f.read()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    earlier = _json(must("list the deploy keys", run("api", "repos/%s/keys" % owner_name)), [])
    added = _json(must("add main's deploy key", run("api", "--method", "POST", "repos/%s/keys" % owner_name,
                                                    "-f", "title=" + DEPLOY_KEY_TITLE, "-f", "key=" + public, "-F", "read_only=false")), {})
    # the environment: deployable from the default branch alone, so no other branch's workflow reads the key
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}, f)
        temp = f.name
    try:
        must("set up the environment %s" % MAIN_ENVIRONMENT,
             run("api", "--method", "PUT", "repos/%s/environments/%s" % (owner_name, MAIN_ENVIRONMENT), "--input", temp))
    finally:
        os.unlink(temp)
    policies_path = "repos/%s/environments/%s/deployment-branch-policies" % (owner_name, MAIN_ENVIRONMENT)
    policies = _json(must("read the environment's branches", run("api", policies_path)), {}).get("branch_policies") or []
    for policy in policies:
        if policy.get("name") != default_branch or policy.get("type", "branch") != "branch":
            must("narrow the environment to %s" % default_branch, run("api", "--method", "DELETE", "%s/%s" % (policies_path, policy.get("id"))))
    if not any(p.get("name") == default_branch and p.get("type", "branch") == "branch" for p in policies):
        must("let %s deploy to the environment" % default_branch,
             run("api", "--method", "POST", policies_path, "-f", "name=" + default_branch, "-f", "type=branch"))
    must("store main's deploy key in the environment",
         run("secret", "set", DEPLOY_KEY_SECRET, "--env", MAIN_ENVIRONMENT, "--repo", owner_name, stdin=private))
    for key in earlier:
        if isinstance(key, dict) and key.get("title") == DEPLOY_KEY_TITLE and key.get("id") != added.get("id"):
            must("remove the deploy key it replaces", run("api", "--method", "DELETE", "repos/%s/keys/%s" % (owner_name, key.get("id"))))
    return added.get("id")


def _release_environment(run, owner_name):
    """The environment only a release tag deploys from, which holds the registry's token. Its secret is the person's to set."""
    import tempfile
    from .project import ProjectError

    def must(step, result):
        code, out, err = result
        if code != 0:
            raise ProjectError("could not %s on %s: %s" % (step, owner_name, (err or out).strip()[-400:]))
        return out

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}, f)
        temp = f.name
    try:
        must("set up the environment %s" % RELEASE_ENVIRONMENT,
             run("api", "--method", "PUT", "repos/%s/environments/%s" % (owner_name, RELEASE_ENVIRONMENT), "--input", temp))
    finally:
        os.unlink(temp)
    policies_path = "repos/%s/environments/%s/deployment-branch-policies" % (owner_name, RELEASE_ENVIRONMENT)
    policies = _json(must("read the environment's tags", run("api", policies_path)), {}).get("branch_policies") or []
    if not any(p.get("name") == "v*" and p.get("type") == "tag" for p in policies):
        must("let release tags deploy to the environment", run("api", "--method", "POST", policies_path, "-f", "name=v*", "-f", "type=tag"))


def _put_ruleset(run, owner_name, payload, hint=""):
    """A ruleset of that name replaced, else created. Returns (created, id)."""
    import tempfile
    from .project import ProjectError
    code, out, _err = run("api", "repos/%s/rulesets" % owner_name)
    existing = _json(out, []) if code == 0 else []
    found = [r for r in existing if isinstance(r, dict) and r.get("name") == payload.get("name")]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(payload, f)
        temp = f.name
    try:
        if found:
            code, out, err = run("api", "--method", "PUT", "repos/%s/rulesets/%s" % (owner_name, found[0].get("id")), "--input", temp)
        else:
            code, out, err = run("api", "--method", "POST", "repos/%s/rulesets" % owner_name, "--input", temp)
    finally:
        try:
            os.unlink(temp)
        except OSError:
            pass
    if code != 0:
        raise ProjectError("could not set the rules %r on %s: %s%s" % (payload.get("name"), owner_name, (err or out).strip()[-400:], hint))
    return not found, found[0].get("id") if found else _json(out, {}).get("id")


#: GitHub signs a commit it makes through this mutation, so it shows as verified with no key on the person's computer
CREATE_COMMIT = """mutation($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) { commit { oid url } }
}"""


def verified_commit(root, repo, message, token=None, gh=None):
    """Make the staged change a commit through GitHub, so GitHub signs it: the session route needs verified commits by the confirmer, and this
    works in a sandbox or on any computer, with no signing key. The branch must already be on GitHub at this commit. Afterwards the local branch
    holds the new commit, and the tree is clean. Returns {oid, url, branch}."""
    import base64
    import subprocess
    import tempfile
    from .project import ProjectError

    def git(*args):
        return subprocess.run(["git", "-C", root] + list(args), capture_output=True)

    def text(*args):
        done = git(*args)
        if done.returncode != 0:
            raise ProjectError("git %s failed: %s" % (args[0], done.stderr.decode("utf-8", "replace").strip()[-300:]))
        return done.stdout.decode("utf-8", "replace").strip()

    owner_name = _owner_name(repo)
    if "/" not in owner_name:
        raise ProjectError("the repository must be owner/name (or its GitHub URL): %r" % repo)
    branch, head = text("rev-parse", "--abbrev-ref", "HEAD"), text("rev-parse", "HEAD")
    if branch in ("HEAD", "main", "master"):
        raise ProjectError("this commits to the branch checked out, and that is %s: a change reaches main by a pull request, so make a branch first" % branch)
    additions, deletions = [], []
    for line in text("diff", "--cached", "--name-status", "--no-renames", "HEAD").splitlines():
        status, path = line.split("\t", 1)
        if status == "D":
            deletions.append({"path": path})
        else:
            shown = git("show", ":" + path)
            if shown.returncode != 0:
                raise ProjectError("could not read %s from what is staged" % path)
            additions.append({"path": path, "contents": base64.b64encode(shown.stdout).decode("ascii")})
    if not additions and not deletions:
        raise ProjectError("nothing is staged: git add what this commit holds first")
    remote = text("ls-remote", "origin", "refs/heads/%s" % branch).split()
    if not remote:
        pushed = git("push", "-q", "origin", "HEAD:refs/heads/%s" % branch)
        if pushed.returncode != 0:
            raise ProjectError("could not put the branch %s on GitHub: %s" % (branch, pushed.stderr.decode("utf-8", "replace").strip()[-300:]))
    elif remote[0] != head:
        raise ProjectError("the branch %s moved on GitHub, or this one has commits it doesn't: GitHub holds %s and this is %s. Pull or push, then run this again" % (branch, remote[0][:12], head[:12]))
    lines = message.strip().split("\n", 1)
    payload = {"query": CREATE_COMMIT, "variables": {"input": {
        "branch": {"repositoryNameWithOwner": owner_name, "branchName": branch},
        "message": dict({"headline": lines[0]}, **({"body": lines[1].strip()} if len(lines) > 1 else {})),
        "expectedHeadOid": head, "fileChanges": {"additions": additions, "deletions": deletions}}}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(payload, f)
        temp = f.name
    try:
        code, out, err = _github(token, gh)("api", "graphql", "--input", temp)
    finally:
        os.unlink(temp)
    answer = _json(out, {}) or {}
    commit = ((answer.get("data") or {}).get("createCommitOnBranch") or {}).get("commit") or {}
    if code != 0 or not commit.get("oid"):
        raise ProjectError("GitHub did not make the commit: %s" % (err or out).strip()[-400:])
    text("fetch", "-q", "origin", branch)
    text("reset", "-q", "--soft", commit["oid"])
    return {"oid": commit["oid"], "url": commit.get("url"), "branch": branch}


def apply_workspace_rules(root, repo, token=None, gh=None, code_owner=None):
    """Set up a pack workspace's repository, through the GitHub CLI: the code owners first, which must be on the default branch
    before the rules ask for them; the environment only release tags deploy from; the branch rules; the tag rules. Returns
    {created, id, code_owner, environment, tag_rules, warnings, workspace: True}."""
    from .project import ProjectError
    owner_name = _owner_name(repo)
    if "/" not in owner_name:
        raise ProjectError("the repository must be owner/name (or its GitHub URL): %r" % repo)
    payloads = []
    for relative, default in ((RULES_FILE, WORKSPACE_RULES), (TAG_RULES_FILE, TAG_RULES)):
        try:
            with open(os.path.join(root, relative), encoding="utf-8") as f:
                payloads.append({k: v for k, v in json.load(f).items() if not str(k).startswith("_")})
        except FileNotFoundError:
            payloads.append({k: v for k, v in default.items() if not str(k).startswith("_")})
        except (OSError, ValueError) as exc:
            raise ProjectError("the rules in %s can't be read: %s" % (relative, exc))
    run = _github(token, gh)
    default_branch = _json(run("api", "repos/%s" % owner_name)[1], {}).get("default_branch") or "main"
    owner = code_owner_of(root)
    if code_owner or not owner:
        chosen = code_owner or github_login(token, gh)
        if not chosen:
            raise ProjectError("no code owner for %s: the GitHub CLI says nobody is signed in; pass --code-owner <login or org/team>" % CODEOWNERS_FILE)
        if _handle(chosen) != owner:
            owner = write_code_owners(root, chosen)
    code, _out, _err = run("api", "repos/%s/contents/.github/CODEOWNERS?ref=%s" % (owner_name, default_branch))
    if code != 0:
        raise ProjectError("the code owners are not on %s of %s yet: %s names %s here; commit it to %s and push it, then run `oto repo rules --apply` again: "
                           "the rules ask for a code owner's approval, so the owners come first" % (default_branch, owner_name, CODEOWNERS_FILE, owner, default_branch))
    _release_environment(run, owner_name)
    created, ruleset = _put_ruleset(run, owner_name, payloads[0])
    _put_ruleset(run, owner_name, payloads[1])
    return {"created": created, "id": ruleset, "code_owner": owner, "environment": RELEASE_ENVIRONMENT, "tag_rules": payloads[1].get("name"), "warnings": [], "workspace": True}


def apply_rules(root, repo, token=None, gh=None, code_owner=None):
    """Set up the GitHub repository `owner/name` for the route gate, through the GitHub CLI, in this order:
    the code owners (`.github/CODEOWNERS`, naming `code_owner`, or the signed-in person when the file is
    not there yet), which must be on the default branch before the rules ask for them; main's deploy key,
    in the environment oto-main; then the branch rules of `.github/oto-rules.json`, a ruleset of that name
    replaced, else created. Returns {created, id, code_owner, environment, key, warnings}. A pack workspace
    has rules of its own (apply_workspace_rules)."""
    from .project import ProjectError
    if is_workspace(root):
        return apply_workspace_rules(root, repo, token=token, gh=gh, code_owner=code_owner)
    path = os.path.join(root, RULES_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            rules = json.load(f)
    except (OSError, ValueError) as exc:
        raise ProjectError("no branch rules to apply: %s (%s); `oto init --repo` writes them" % (path, exc))
    payload = {k: v for k, v in rules.items() if not str(k).startswith("_")}
    owner_name = _owner_name(repo)
    if "/" not in owner_name:
        raise ProjectError("the repository must be owner/name (or its GitHub URL): %r" % repo)
    run = _github(token, gh)
    warnings = []

    # 1. the code owners, on the default branch first
    default_branch = _json(run("api", "repos/%s" % owner_name)[1], {}).get("default_branch") or "main"
    owner = code_owner_of(root)
    if code_owner or not owner:
        chosen = code_owner or github_login(token, gh)
        if not chosen:
            raise ProjectError("no code owner for %s: the GitHub CLI says nobody is signed in; pass --code-owner <login or org/team>" % CODEOWNERS_FILE)
        if _handle(chosen) != owner:
            owner = write_code_owners(root, chosen)
    code, out, _err = run("api", "repos/%s/contents/.github/CODEOWNERS?ref=%s" % (owner_name, default_branch))
    if code != 0:
        raise ProjectError("the code owners are not on %s of %s yet: %s names %s here; commit it to %s and push it "
                           "(through a pull request if the rules are already on), then run `oto repo rules --apply` again: "
                           "the rules ask for a code owner's approval, so the owners come first"
                           % (default_branch, owner_name, CODEOWNERS_FILE, owner, default_branch))
    on_main = _json(out, {}).get("content")
    if on_main:
        import base64
        try:
            text = base64.b64decode(on_main).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            text = None
        if text is not None and text != open(os.path.join(root, CODEOWNERS_FILE), encoding="utf-8").read():
            warnings.append("the %s on %s differs from this folder's, and %s's is the one GitHub reads" % (CODEOWNERS_FILE, default_branch, default_branch))
    errors = _json(run("api", "repos/%s/codeowners/errors" % owner_name)[1], {}).get("errors") or []
    for error in errors[:5]:
        warnings.append("GitHub reads %s with an error: %s" % (CODEOWNERS_FILE, error.get("message") or error))

    # 2. main's deploy key, in an environment only the default branch deploys from
    key = _main_key(run, owner_name, default_branch)

    # 3. the rules, last, once main's key is in place
    code, out, _err = run("api", "repos/%s/rulesets" % owner_name)
    existing = _json(out, []) if code == 0 else []
    found = [r for r in existing if isinstance(r, dict) and r.get("name") == payload.get("name")]
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(payload, f)
        temp = f.name
    try:
        if found:
            code, out, err = run("api", "--method", "PUT", "repos/%s/rulesets/%s" % (owner_name, found[0].get("id")), "--input", temp)
        else:
            code, out, err = run("api", "--method", "POST", "repos/%s/rulesets" % owner_name, "--input", temp)
    finally:
        try:
            os.unlink(temp)
        except OSError:
            pass
    if code != 0:
        hint = ""
        if any(isinstance(r, dict) and r.get("type") == "merge_queue" for r in payload.get("rules") or []):
            hint = (". %s still asks for a merge_queue, which GitHub's Team plan refuses on a private repository: take that rule out of the file, "
                    "and whoever is behind main runs `oto route rebase`" % RULES_FILE)
        raise ProjectError("could not set the branch rules on %s: %s%s" % (owner_name, (err or out).strip()[-400:], hint))
    created_id = _json(out, {}).get("id")
    return {"created": not found, "id": found[0].get("id") if found else created_id, "code_owner": owner,
            "environment": MAIN_ENVIRONMENT, "key": key, "warnings": warnings}


def files(slug, name, engine=None, architecture=False):
    """Path -> content for everything `--repo` adds. `architecture`: the project composes the architecture
    pack (its vocabulary declares CodeModule), so the merge workflow that compiles it is written too."""
    from . import access as _access
    engine = engine or ENGINE
    pip = PIP.format(engine="${ENGINE}")
    mcp = json.loads(json.dumps(MCP).replace("{slug}", slug).replace("{engine}", engine))

    def fill(ontology):
        return ontology.replace("@PIP@", pip).replace("@ENGINE@", engine)

    out = {
        ".gitignore": GITIGNORE,
        ".mcp.json": json.dumps(mcp, indent=2) + "\n",
        "CLAUDE.md": CLAUDE_MD.format(name=name, engine=engine),
        os.path.join(".github", "workflows", "oto-ingest.yml"): INGEST.format(pip=pip, engine=engine),
        os.path.join(".github", "workflows", "oto-checks.yml"): CHECKS.format(pip=pip, engine=engine),
        os.path.join(".github", "workflows", "oto-deploy.yml"): DEPLOY.format(pip=pip, engine=engine, slug=slug, main_environment=MAIN_ENVIRONMENT),
        os.path.join(".github", "workflows", "oto-route.yml"): ROUTE.format(pip=pip, engine=engine),
        os.path.join(".github", "workflows", "oto-preview.yml"): PREVIEW.format(pip=pip, engine=engine, slug=slug),
        os.path.join(".github", "workflows", "oto-promote.yml"): PROMOTE.format(pip=pip, engine=engine, main_environment=MAIN_ENVIRONMENT),
        os.path.join(".github", "workflows", "oto-access.yml"): ACCESS.format(pip=pip, engine=engine, main_environment=MAIN_ENVIRONMENT),
        os.path.join(".github", "workflows", "oto-pack-update.yml"): PACK_UPDATE.format(pip=pip, engine=engine),
        RULES_FILE: rules_text(),
        _access.FILE: _access.starter_text(),
        os.path.join(".github", "workflows", "oto-author.yml"): fill(AUTHOR),
        os.path.join(".github", "workflows", "oto-review.yml"): fill(REVIEW),
        os.path.join(".github", "workflows", "oto-tools.yml"): fill(ACTIONS),
        os.path.join(".github", "scripts", "oto-tools-invoke.py"): INVOKE_SCRIPT,
    } | ({os.path.join(".github", "workflows", "oto-architecture.yml"): ARCHITECTURE.format(pip=pip, engine=engine)} if architecture else {})
    # every install of the engine is pinned to the lock, in every workflow
    return {path: text.replace(INSTALL, PIN + INSTALL) if path.endswith(".yml") else text for path, text in out.items()}


def write(root, slug, name, engine=None, force=False, writer=None, architecture=False):
    """Write the repository files. Returns the paths written. `writer(path, text, force, label)`
    is the scaffold's own writer, so the same keep-or-overwrite rule applies."""
    written = []
    for relative, text in files(slug, name, engine, architecture=architecture).items():
        path = os.path.join(root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if writer:
            if writer(path, text, force, relative):
                written.append(relative)
        else:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            written.append(relative)
    return written
