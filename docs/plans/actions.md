# Plan: actions, the graph's hands

Status: proposed 2026-09-21 on the `actions` branch, rewritten the same day after review.
All five phases delivered by 2026-09-23 on the `actions` branch; merges to `main` by pull request when the user says so.

The ask, in the user's words: add actions to the knowledge graph, as nodes with edges such as
`executed_by`. A component can be `implemented_by` a GitHub repository whose URL is recorded
before the repository exists; a person asks Oto to list the actions in the graph and decides to
execute one; an action can also be an API to connect to, bringing data in from outside. After
review: **Oto does not run anything.** It returns the action, the way an MCP server returns a
tool, and the caller, an agent, a person or a workflow, invokes it. Oto records the result as
evidence, through the gates.

## 1. What the feature is

The value is not execution. An agent driving Oto can already create a repository with its own
tools and curate the fact. What it cannot do today, and what this feature adds:

- **Know what can be done and how.** The binding between an entity, the tool that acts on it,
  its parameters, its credentials by name and its preconditions lives in an agent's prompt. In
  the graph it is durable, versioned in a template, reviewed in a pull request, and shared by
  every agent and person on the project.
- **Tell intent from observation.** Nothing today says "this repository is planned, not real".
  A fourth status, `intended`, does, and the query skill never answers "what is" with it.
- **Prove why the graph changed.** The invocation and its response are the evidence for the
  fact they realised. A run record is a source document like any other.
- **Ask the graph what is ready.** Preconditions written in the rules' pattern language make
  "which actions could run now, on which entities" a query over the live graph.
- **Keep the graph honest without improvising.** A template ships the repository check once;
  every project from it can run the check on a schedule and move `intended` to `current`, or
  flag it as overdue.

So an action is a tool description in MCP shape, bound to the graph. Oto is the catalog.
Invocation is the caller's. Results come back through the inbox or a proposal and the four gates.

## 2. The model

**`Action`** is a class in `oto-core`. An action is authored as a file and becomes a node:

```
actions/<id>.json               the action, authored, versioned, checked (one per file)
runs/actions/<id>/<stamp>/      one directory per recorded invocation: request, response,
                                by, at, and the document or proposal Oto derived from it
```

```json
{
  "id": "action.check-repository",
  "label": "Check that a repository exists",
  "description": "Reads the repository's metadata and records whether it exists, its default branch and its last push.",
  "subject": "Repository",
  "executed_by": "team.payments",
  "annotations": {"readOnlyHint": true, "destructiveHint": false, "idempotentHint": true},
  "inputSchema": {"type": "object", "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}}, "required": ["owner", "repo"]},
  "bind": {"owner": "$attr.owner", "repo": "$attr.name"},
  "when": [{"node": "r", "type": "Repository"}, {"attr": ["r", "status", "intended"]}],
  "invoke": {"transport": "mcp", "server": "github", "tool": "get_repository"},
  "needs": ["GITHUB_TOKEN"],
  "result": {"kind": "proposal",
             "then": {"node": "$subject", "status": "current",
                      "attributes": {"default_branch": "$response.default_branch", "pushed_at": "$response.pushed_at"}}},
  "schedule": "daily"
}
```

| Field | Meaning |
|---|---|
| `label`, `description`, `inputSchema`, `annotations` | the MCP tool shape, returned as is; the annotations are MCP's own (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) |
| `subject` | the class the action acts on; a run names the instance (`acts_on` edge at run time) |
| `executed_by` | the `Team` accountable for it; an edge |
| `bind` | how the inputs are filled from the subject node (`$attr.x`, `$id`, `$label`); what is not bound is asked of the caller |
| `when` | preconditions in the rules' pattern language; `kg_actions` computes readiness from them |
| `invoke` | declared, never performed: `mcp` (server, tool), `cli` (a command template), `http` (method, url template, headers by env name, body template), `script` (a path under `actions/`) |
| `needs` | names of environment variables the caller must hold; values never appear anywhere under the project |
| `result` | how Oto turns the response into knowledge: `document` (Markdown to the inbox) or `proposal` (a `then` clause rendered with `$response.<json path>` into nodes and edges, evidence pointing at the run record) |
| `schedule` | optional; only an action whose `readOnlyHint` is true may carry one |

**`intended`** joins `current`, `superseded` and `proposed` as a status: a fact asserted as a
plan, not observed. It flows through the model, the curate gates, both stores, every tool that
prints a status, the payload, the explorer (dotted, badged) and the reader. Default queries
exclude it from "what is" answers as they exclude `superseded`; `--history` and an explicit
`--state intended` show it. The template rule `intended-fact-overdue` flags intent older than
a configured age.

**Edges.** `acts_on` (Action to subject instance, written by `oto actions record`),
`executed_by` (Action to Team). Domain templates add their subjects: software-architecture adds
`Repository` and `implemented_by` (Component to Repository).

## 3. What the caller sees

```bash
oto actions list --project <root>                      # every action: subject, ready on which entities, last run
oto actions list --project <root> --ready --json       # ready ones as MCP tool definitions, inputs bound
oto actions check --project <root>                     # files valid, `when` over the vocabulary, bindings resolvable
oto actions show action.check-repository --on repo.payment-api    # the bound invocation for one entity
oto actions record action.check-repository --on repo.payment-api --by "Chiheb" \
    --response response.json                            # the caller's result -> run record -> proposal or inbox
oto curate add --from proposals/action.check-repository.<stamp>.json --dry-run      # then the gates
oto actions runs --project <root>                      # the run records
```

`kg_actions` (the fourteenth tool, read-only, both stores, in the equivalence battery) answers
"what can be done here": each action with its MCP shape, whether it is ready and on which
entities, why not when it is not, its last run, and what it would assert. With `--on <entity>`
the inputs come back bound and the `invoke` block says how to call it. The server executes
nothing; the hardening invariants hold without exception.

The agent's protocol, written into an `act` skill: list; for anything not read-only, show the
bound invocation and ask the person by name; invoke through the declared transport with the
agent's own tools; `oto actions record` the response; hand to curate. In a scheduled workflow
only read-only actions are picked up.

The explorer shows `Action` nodes with a last-run badge and `intended` facts dotted; the reader
lists actions and runs. Nothing in the UI invokes.

## 4. The user's example, end to end

1. The architecture graph says `component.payment-api implemented_by repo.payment-api`, and
   `repo.payment-api` is `intended` with `owner: acme`, `name: payment-api`. Authored through
   curate like any fact; `kg_entity` prints it as intended.
2. The template ships `action.create-repository` (not read-only, bound to the GitHub MCP
   server's create tool) and `action.check-repository` (read-only, daily).
3. "What actions are available?" The agent calls `kg_actions`: create-repository is ready on
   `repo.payment-api`; check-repository is ready on the same entity.
4. "Create it." The agent shows the bound invocation, asks for the person's name, calls the
   GitHub server's tool with the bound inputs, then runs `oto actions record` with the response.
   Oto writes the run record and a proposal: `repo.payment-api` becomes `current` with the
   response's fields, evidence pointing at the run.
5. `oto curate add`, `check`, `apply`, `build`. The graph now says the repository exists, and
   "why" leads to the run of 2026-09-21 by Chiheb and the API response.
6. Every night the workflow lists ready read-only actions, calls the check, records, and opens a
   pull request with the proposal when something changed.

## 5. Delivery

| Phase | Delivers | Size |
|---|---|---|
| 1. Model | `Action` in `oto-core`; the action file format and its validation (`oto actions check`); `intended` through the model, the curate gates, both stores, the tools, the payload and the apps; the overdue policy rule template; tests | 2 days |
| 2. The catalog | `kg_actions` and `oto actions list/show`: readiness from `when`, bindings from the subject, MCP shape out, `invoke` declared; the equivalence battery; `--json` | 1 day |
| 3. The evidence loop | `oto actions record`: run records, `result` rendering (`document` to the inbox, `proposal` with `then` and `$response` paths), `acts_on` edge, `intended` to `current` through curate with the run as evidence; the explorer and reader badges; tests with recorded responses, no network | 2 days |
| 4. Templates and skill | `actions/` carried by templates and checked by the registry; software-architecture ships `Repository`, `implemented_by`, `check-repository` and `create-repository` bound to the GitHub MCP server, and a generic `http-endpoint` action with a JSON path mapping; the `act` skill; docs | 1.5 days |
| 5. Schedules | `schedule` on read-only actions; `oto actions list --due`; an `oto-actions.yml` workflow on cron in repository mode that lists due actions, invokes them through the declared transport, records, and opens a pull request with the proposals | 1 day |

Each phase ends green on the suite and the gates, committed to the `actions` branch, usable on
its own. The branch merges to `main` by pull request when the user says so.

## 6. Decisions taken in review

1. **Oto returns, the caller invokes.** No runner, no hash lock, no redaction logic: the
   secrets question does not arise inside Oto because Oto never holds a value, only a name.
2. **The action's shape is MCP's.** Tool name, description, input schema and annotations are
   MCP's own, so an agent that speaks MCP needs no translation; `readOnlyHint` is what decides
   whether an action may run unattended or on a schedule.
3. **`oto actions`, a noun.** The command lists, checks, shows and records; it does not execute,
   so it is not called execute.
4. **Read-only actions first.** They keep `intended` facts honest and are safe on a schedule;
   the changing ones share the same shape and follow in phase 4.
5. **GitHub and a generic HTTP endpoint are the first connectors.** GitHub through its MCP
   server, the HTTP endpoint through the `http` transport with a JSON path mapping.
6. **Names.** `Action`, `intended`, `acts_on`, `executed_by`, `oto actions`, `kg_actions`.

## 7. Decided 2026-09-21, after review

- **File only.** An action is authored as a file under `actions/`, never created by a proposal:
  the file is reviewed as code and versioned by the template; a proposal is reviewed as a fact,
  and the fact path must not be able to introduce an invocation. The action still becomes a node
  at build time.
- **Subject only.** `bind` reads the subject's own attributes (`$attr.x`, `$id`, `$label`) and
  nothing else, so an invocation is fully determined by one node and reproducible from the run
  record. A value that lives on a neighbour is copied onto the subject by a derive rule, with
  premises, or supplied by the caller.

## 8. The scenario

[docs/scenarios/actions.md](../scenarios/actions.md) walks the feature on one machine:
`tools/actions-scenario.py setup` builds a project with an intended repository and a demo
interface, `serve` stands in for GitHub and the interface, and the steps run the check (not
found, no proposal), the create (a person's decision), the gates, the check again, a refused
contradiction, a probed interface, the schedules, and the same loop with an agent. Building it
found one gap, closed the same day: a `result.require` guard, so a "not found" answer never
realises a fact; the shipped GitHub actions require `$response.html_url`.

## 9. Hardening review, 2026-09-23

Reviewed at the end of phase 5, against the invariants set in review:

- **Oto never invokes.** No engine command or tool runs an action; the only invoker is the
  script repository mode writes under `.github/scripts/`, which is the caller, and the agent
  through the act skill. `kg_actions` is read-only on both stores and the HTTP front end's
  invariants are untouched.
- **Nothing that changes the world runs unattended.** Only a read-only action may carry a
  schedule (`oto actions check` refuses otherwise), only scheduled read-only actions are ever
  due, and the workflow invokes only what is due. An MCP-bound action is skipped by the workflow
  and waits for an agent, which asks a person by name.
- **Secrets.** An action names variables; values never appear in an action file, a run record,
  a document, a summary or a log. The script takes a header value from the environment only when
  it names a variable that is set, skips an action whose variable is missing and names it, and
  the test asserts the value is nowhere in the output.
- **Bounds.** `timeout` on an action (1 to 3600 seconds, validated) bounds the call; the script
  reads a response up to one megabyte; a run record keeps at most two million characters and
  says so; a `script` path must be relative and under `actions/`; `cli` inputs are shell-quoted
  and `http` inputs URL-encoded.
- **The gates.** A recorded response never writes `graph.json`: it is a proposal through
  `curate add`, `check`, `apply`, and in repository mode the pull request. A changed value is
  refused at merge; an added attribute and a plan becoming real are recorded changes.
- **Provenance.** Every fact a run asserts cites the run document, which `oto ingest` brings
  into the corpus and `oto vet` checks like any source; the Action node carries `acts_on` and
  `last_run` from the records at build.
