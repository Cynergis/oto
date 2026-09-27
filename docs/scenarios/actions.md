# Scenario: the graph's hands

A hands-on walk through the actions feature on the `actions` branch, on one machine, with no
token: a repository the graph holds as a plan, a check that says it does not exist, the decision
to create it, the check again, and a probe of an interface. Every step names the command, what
to look for, and where the gates hold. About thirty minutes.

Two paths run side by side: **offline**, against a stand-in server this repository ships, and
**real**, against GitHub with your own account. Do the offline path first; it needs nothing.

## 0. Set up

From a checkout of the branch:

```bash
git clone -b actions https://github.com/Cynergis/oto && cd oto
python3 -m venv .venv && .venv/bin/pip install -e .          # or: uvx --from "oto-kg @ git+https://github.com/Cynergis/oto@actions" oto
export PATH="$PWD/.venv/bin:$PATH"
python tools/actions-scenario.py setup ~/oto-actions-demo --owner <your GitHub user or org>
```

The last command initialises a software-architecture project, writes the plan as a note in the
inbox and ingests it (a plan is a source like any other), then takes one proposal citing it
through the curate gates: a `Repository` the payment API is `implemented_by`, status `intended`,
that does not exist, and a second `Interface` whose URL points at the stand-in server. Read what
it prints: the gate commands run in order, and `apply` records who and why in the ledger.

In a second terminal, leave the stand-in running:

```bash
python tools/actions-scenario.py serve
```

## 1. What the graph declares

```bash
oto actions list --project ~/oto-actions-demo
```

Look for three actions the template shipped, each with its kind, subject and accountable team:

- `action.check-repository`, read-only, daily: **ready on 2** repositories, the sample's real
  one and your intended one, and **DUE (never run)**.
- `action.create-repository`, changes: **ready on 1**, the intended one only. Its `when` says
  `status "intended"`; the sample repository does not qualify.
- `action.probe-interface`, read-only, weekly: **ready on 2** interfaces.

Then the entity itself:

```bash
oto query --project ~/oto-actions-demo entity repo.oto-actions-demo
oto query --project ~/oto-actions-demo actions --on repo.oto-actions-demo
```

The card says `status=intended` and, in its own line, that this is a plan, not the current state.
The second command is the `kg_actions` tool: both actions on the repository, inputs bound from
the node (`owner`, `repo`), `create-repository` asking the caller for `private`, the declared
invocation (`mcp github get_repository`), and the variable the caller needs by name.

Open the explorer and find the repository drawn dotted with an `intended` badge:

```bash
oto serve --project ~/oto-actions-demo --http 8765      # http://127.0.0.1:8765/
```

## 2. The check says the repository does not exist

The check is bound to the GitHub MCP server. You are the caller; the stand-in answers like
GitHub's API. Ask it, then hand the answer to OTO:

```bash
curl -s http://127.0.0.1:8799/repos/<owner>/oto-actions-demo | tee /tmp/check-1.json
oto actions record action.check-repository --on repo.oto-actions-demo --by "<your name>" \
    --response /tmp/check-1.json --project ~/oto-actions-demo
```

Look for `no proposal: the response does not confirm the fact: $response.html_url not present`.
The run is recorded and the run document is in the inbox, but nothing moves: a "not found"
answer must never realise an intended fact. Confirm:

```bash
oto actions runs --project ~/oto-actions-demo
oto query --project ~/oto-actions-demo entity repo.oto-actions-demo        # still intended
```

## 3. Create it, as a person

`create-repository` changes the world, so the act skill asks a person by name before invoking.
Here you are that person. Show what would be invoked, then invoke it against the stand-in:

```bash
oto actions show action.create-repository --on repo.oto-actions-demo --project ~/oto-actions-demo
curl -s -X POST http://127.0.0.1:8799/orgs/<owner>/repos \
    -H 'Content-Type: application/json' -d '{"name": "oto-actions-demo", "private": true}' | tee /tmp/create.json
oto actions record action.create-repository --on repo.oto-actions-demo --by "<your name>" \
    --response /tmp/create.json --note "created after review" --project ~/oto-actions-demo
```

This time look for `proposal: proposals/action.create-repository.<date>.json`. Open it: the
subject becomes `current` with `url` and `default_branch` from the response, `valid_from` is
today because the plan became real today, and the evidence points at the run document.

## 4. Through the gates

```bash
oto ingest --project ~/oto-actions-demo                                     # the run documents into the corpus
oto curate start --project ~/oto-actions-demo
oto curate add --project ~/oto-actions-demo --from ~/oto-actions-demo/proposals/action.create-repository.*.json --dry-run
oto curate add --project ~/oto-actions-demo --from ~/oto-actions-demo/proposals/action.create-repository.*.json
oto curate check --project ~/oto-actions-demo
oto curate apply --project ~/oto-actions-demo --by "<your name>" --note "the repository exists now"
oto build --project ~/oto-actions-demo
oto ingest complete --project ~/oto-actions-demo                            # the run documents: processing/ -> archive/
```

Look for: the dry run says `updated repo.oto-actions-demo status, valid_from, attributes:...`,
the check is clean (an intended fact becoming current is a recorded change, not a contradiction),
and after the build:

```bash
oto query --project ~/oto-actions-demo entity repo.oto-actions-demo        # current, cites the run document
oto query --project ~/oto-actions-demo neighbors repo.oto-actions-demo    # acts_on from the two actions
oto query --project ~/oto-actions-demo actions --action action.create-repository   # last run: today, by you
oto vet --project ~/oto-actions-demo --vetted sample                       # every citation resolves (sample is the template's starter data)
oto actions list --project ~/oto-actions-demo                              # create-repository: not ready (nothing intended)
```

Reload the explorer: the repository is solid now, and the action nodes carry a `ran` flag.

## 5. The check again, and a contradiction refused

The stand-in now knows the repository. Check again and take it through:

```bash
curl -s http://127.0.0.1:8799/repos/<owner>/oto-actions-demo > /tmp/check-2.json
oto actions record action.check-repository --on repo.oto-actions-demo --by "<your name>" --response /tmp/check-2.json --project ~/oto-actions-demo
```

A proposal is written; merged, it re-attests the fact (same values, a newer `as_of`). To see the
gate refuse a lie, edit `/tmp/check-2.json` so `default_branch` is `develop`, record it again, and
`oto curate add --dry-run` the new proposal: **would refuse the batch**, `attributes` conflict.
A changed value is supersession work for a person, never an overwrite.

## 6. An interface probed, kept as a document

`probe-interface` returns a document, not a proposal: what the interface answers is read and
curated like any source.

```bash
oto actions show action.probe-interface --on interface.demo-health --project ~/oto-actions-demo
curl -s -H 'Accept: application/json' http://127.0.0.1:8799/payments/v2 > /tmp/probe.json
oto actions record action.probe-interface --on interface.demo-health --by "<your name>" --response /tmp/probe.json --project ~/oto-actions-demo
oto ingest --project ~/oto-actions-demo
ls ~/oto-actions-demo/build/documents/ | grep run-probe
```

Look for the run document in the corpus and no proposal: the next step is the reading step, by a
person or the build-knowledge-base skill.

## 7. Schedules

```bash
oto actions list --project ~/oto-actions-demo --due
```

Before its first run today the check was due; after it, not until tomorrow, and the probe is not
due for a week. `create-repository` is never due: only a read-only action may carry a schedule
(`oto actions check` refuses otherwise). In repository mode this is what the daily workflow asks
before it invokes anything.

## 8. The same, with an agent

Open the project in Claude Code with the branch's plugin, and let the act skill run the loop:

```bash
claude --plugin-dir /path/to/oto        # then, in the project ~/oto-actions-demo
```

Say: *"what can I do about the demo repository?"* The concierge or the act skill quotes
`kg_actions`. Say: *"check that it exists"*: the agent invokes with its own tools (the stand-in,
with curl, or the GitHub MCP server if you have it connected) and records. Say: *"create it"*:
it shows the bound invocation and asks you by name before invoking, and records the run under
your name. Everything it writes goes through `oto curate check` before you apply.

## 9. The real path

With a GitHub token in the environment (`export GITHUB_TOKEN=...`; never in a file) and the
GitHub CLI:

```bash
gh api repos/<owner>/oto-actions-demo > /tmp/real-check.json || true       # 404: recorded, no proposal
oto actions record action.check-repository --on repo.oto-actions-demo --by "<your name>" --response /tmp/real-check.json --project ~/oto-actions-demo
gh repo create <owner>/oto-actions-demo --private                          # you decide; this changes the world
gh api repos/<owner>/oto-actions-demo > /tmp/real-create.json
oto actions record action.create-repository --on repo.oto-actions-demo --by "<your name>" --response /tmp/real-create.json --project ~/oto-actions-demo
```

Then step 4 as before. With the GitHub MCP server connected in Claude Code, step 8 uses it
directly: the action's `invoke` names the server and the tool.

## 10. Clean up

```bash
rm -rf ~/oto-actions-demo; gh repo delete <owner>/oto-actions-demo --yes   # only if you created the real one
```

## What this scenario proves

- OTO never invoked anything; you did, or the agent did, and OTO recorded.
- A plan and an observation are different statuses, and no "what is" answer mixed them.
- A response that does not confirm a fact changes nothing.
- Every fact a run asserted cites the run document, and `vet` can check it.
- A changed value is refused at the gate; a plan becoming real is not.
- The catalog, the readiness, the bound inputs and the last run are the same from the files,
  from the store and from the tool.
