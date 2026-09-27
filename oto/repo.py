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
    .github/workflows/oto-actions.yml on a schedule: invoke the due read-only actions through the
                                      script under .github/scripts/, record, curate, open a PR
    .gitignore                       generated files ignored, EXCEPT the corpus, which is an input

The engine is installed from its git repository, never assumed to be on a PATH: `uvx` on a person's
machine, `pip` in a workflow. Where the engine lives is one string, `ENGINE`, overridable with
`--engine` and, in the workflows, a repository variable.

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
UVX = 'uvx --from "oto-kg @ git+{engine}" oto'
PIP = 'python -m pip install "oto-kg[intake] @ git+{engine}"'

GITIGNORE = """# build/ is generated and rebuilt by `oto build`, so it is not tracked: EXCEPT the corpus.
# build/documents/ is what ingest extracted from inbox/. It is an input to the build and to every
# review, so in a repository it is committed with the run that produced it.
build/*
!build/documents/
*.db
*.db.new
__pycache__/
"""

MCP = {"mcpServers": {"{slug}-kg": {"command": "uvx",
                                    "args": ["--from", "oto-kg @ git+{engine}", "oto", "serve", "--project", "."]}}}

CLAUDE_MD = """# {name}: an OTO knowledge project

This repository holds a knowledge graph's data and nothing else: the vocabulary, the curated graph,
the ledger, the raw documents at their stations, and the corpus extracted from them. The engine is
the `oto` package, installed on demand from {engine}; run it as `uvx --from "oto-kg @ git+{engine}" oto`.
The engine repository is private: on a machine, `gh auth login` then `gh auth setup-git` once, so
`uvx` and `pip` can clone it; in this repository's workflows the secret `OTO_ENGINE_TOKEN` does the same.
The OTO plugin's skills (build-knowledge-base, curate, ontology-interview, vet-provenance,
query-knowledge, evaluate, capture, spec) are the playbooks for working here; `spec` drafts a
product spec or decision record from the graph and records its decisions back into it.

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
workflow loads on every merge (repository variable `NEO4J_URI`, secret `NEO4J_PASSWORD`). With
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
    steps:
      - uses: actions/checkout@v4
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
          git diff --cached --quiet || git commit -m "oto ingest: $(ls -t runs/*.json | head -1 | xargs -n1 basename | sed 's/.json$//')"
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

CHECKS = """name: oto checks

# The gates, as status checks. A pull request that changes the graph, the vocabulary, the corpus or
# a candidate must pass them before a curator merges it. These are the same commands the playbooks
# run; running them here means the reviewer can trust the numbers in the pull request.

on:
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
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
    steps:
      - uses: actions/checkout@v4
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
      - name: Build every layer
        run: oto build --project .
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
        run: oto build --project . --only site --target site --app "${{{{ vars.OTO_SITE_VIEW }}}}"
      - name: Publish the store to the query repository, when one is configured
        if: vars.OTO_QUERY_REPO != ''
        env:
          OTO_QUERY_REPO_TOKEN: ${{{{ secrets.OTO_QUERY_REPO_TOKEN }}}}
        run: oto publish --project . --repo "${{{{ vars.OTO_QUERY_REPO }}}}" --source "${{{{ github.repository }}}}@${{{{ github.sha }}}}" --engine "${{ENGINE}}" ${{{{ vars.OTO_SITE_VIEW != '' && '--site' || '' }}}}
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
            oto@oto
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
"""Invoke the due actions of an OTO project and record their responses. Written by `oto init --repo`.

This script is the caller. OTO lists what is due (`oto actions list --due --json`), binds the
inputs (`oto actions show <id> --on <entity> --json`), and records what came back (`oto actions
record`); the invocation itself happens here, over the transport each action declares:

    http    the request, with `{input}` placeholders substituted (URL-encoded) in the URL and the
            body, and a header value that names an environment variable taken from the environment
    cli     the command ontology with each input substituted, shell-quoted
    script  the file under actions/ run with the inputs as JSON on stdin
    mcp     skipped: an MCP tool needs an agent (the act skill), not a cron job

Only read-only scheduled actions are ever due, so nothing here changes the world. Environment
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
    path = os.path.join(project, "actions", invoke["path"])
    out = subprocess.run([path], input=json.dumps(inputs), capture_output=True, text=True, timeout=timeout, cwd=project)
    if out.returncode != 0:
        raise RuntimeError("exit %d: %s" % (out.returncode, out.stderr.strip()[-400:]))
    return out.stdout[:READ_LIMIT]


def main(argv=None):
    parser = argparse.ArgumentParser(description="invoke the due actions of an OTO project and record their responses")
    parser.add_argument("--project", default=".")
    parser.add_argument("--oto", default="oto", help="the engine command (default: oto)")
    parser.add_argument("--by", default="oto actions workflow", help="who the runs are recorded by")
    parser.add_argument("--at", default=None, help="the run date (default: today)")
    parser.add_argument("--only", default=None, help="one action id")
    parser.add_argument("--summary", default=None, help="write the summary JSON here as well")
    args = parser.parse_args(argv)
    base = shlex.split(args.oto)
    project = os.path.abspath(args.project)
    due = json.loads(oto(["actions", "list", "--due", "--json", "--project", project], base) or "[]")
    summary = {"invoked": [], "skipped": [], "failed": []}
    for definition in due:
        aid = definition["name"]
        if args.only and aid != args.only:
            continue
        m = definition["oto"]
        for entity in m.get("ready_on") or []:
            bound = json.loads(oto(["actions", "show", aid, "--on", entity, "--json", "--project", project], base))["oto"]
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
                record_args = ["actions", "record", aid, "--on", entity, "--by", args.by, "--response", path,
                               "--note", "invoked by the actions workflow", "--project", project]
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

ACTIONS = r'''name: oto actions

# The graph's hands, on a schedule. Every day this lists the read-only actions the project declares
# that are due (`oto actions list --due`), invokes each through the transport it declares with the
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
  group: oto-actions
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
          python .github/scripts/oto-actions-invoke.py --project . --summary runs/actions/last-workflow.json ${{ inputs.only && format('--only {0}', inputs.only) || '' }}
          echo "invoked=$(python -c 'import json; print(len(json.load(open("runs/actions/last-workflow.json"))["invoked"]))')" >> "$GITHUB_OUTPUT"
      - name: Take the proposals through the gates
        if: steps.invoke.outputs.invoked != '0'
        run: |
          oto ingest --project .
          oto curate start --project .
          python - <<'PY'
          import json, subprocess
          s = json.load(open("runs/actions/last-workflow.json"))
          for item in s["invoked"]:
              if item.get("proposal"):
                  subprocess.run(["oto", "curate", "add", "--project", ".", "--from", item["proposal"]], check=False)
          PY
          if oto curate check --project .; then
            oto curate apply --project . --by "oto actions workflow" --note "recorded runs of the due actions; see runs/actions/last-workflow.json"
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
          git config user.name "oto actions"
          git config user.email "oto-actions@users.noreply.github.com"
          git checkout -b "oto/actions-${stamp}"
          git add -A
          git diff --cached --quiet && { echo "nothing changed"; exit 0; }
          git commit -m "oto actions: recorded runs of the due actions (${stamp})"
          git push -u origin "oto/actions-${stamp}"
          {
            echo "## Recorded runs of the due actions"
            echo
            echo "Invoked by the actions workflow; each response is a run record and a source document, and a proposal went through the gates."
            echo
            echo '```json'; cat runs/actions/last-workflow.json; echo '```'
            echo
            if [ -f graph.candidate.json ]; then echo "**The candidate is still open**: \`oto curate check\` was not clean. A person decides."; fi
          } > /tmp/pr-body.md
          gh label create oto-actions --description "opened by the OTO actions workflow" --color 0E8A16 2>/dev/null || true
          gh pr create --base main --head "oto/actions-${stamp}" --title "oto actions: recorded runs (${stamp})" --body-file /tmp/pr-body.md --label oto-actions
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
            oto@oto
          claude_args: |
            --model "${{ vars.OTO_MODEL || 'claude-opus-5' }}"
            --allowedTools "Bash(oto:*),Bash(ls:*),Bash(cat:*),Bash(head:*),Bash(tail:*),Bash(grep:*),Bash(find:*),Bash(wc:*),Bash(diff:*),Bash(git:*),Edit,Write,Read,Glob,Grep"
            --max-turns 100
'''


def files(slug, name, engine=None):
    """Path -> content for everything `--repo` adds."""
    engine = engine or ENGINE
    pip = PIP.format(engine="${ENGINE}")
    mcp = json.loads(json.dumps(MCP).replace("{slug}", slug).replace("{engine}", engine))

    def fill(ontology):
        return ontology.replace("@PIP@", pip).replace("@ENGINE@", engine)

    return {
        ".gitignore": GITIGNORE,
        ".mcp.json": json.dumps(mcp, indent=2) + "\n",
        "CLAUDE.md": CLAUDE_MD.format(name=name, engine=engine),
        os.path.join(".github", "workflows", "oto-ingest.yml"): INGEST.format(pip=pip, engine=engine),
        os.path.join(".github", "workflows", "oto-checks.yml"): CHECKS.format(pip=pip, engine=engine),
        os.path.join(".github", "workflows", "oto-deploy.yml"): DEPLOY.format(pip=pip, engine=engine, slug=slug),
        os.path.join(".github", "workflows", "oto-author.yml"): fill(AUTHOR),
        os.path.join(".github", "workflows", "oto-review.yml"): fill(REVIEW),
        os.path.join(".github", "workflows", "oto-actions.yml"): fill(ACTIONS),
        os.path.join(".github", "scripts", "oto-actions-invoke.py"): INVOKE_SCRIPT,
    }


def write(root, slug, name, engine=None, force=False, writer=None):
    """Write the repository files. Returns the paths written. `writer(path, text, force, label)`
    is the scaffold's own writer, so the same keep-or-overwrite rule applies."""
    written = []
    for relative, text in files(slug, name, engine).items():
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
