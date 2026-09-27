---
name: act
description: >-
  Do something about an entity in an OTO knowledge graph: list the actions the graph declares,
  confirm with a person before anything that changes the world, invoke the action through the
  transport it declares using your own tools, then record the response so it enters the graph as
  evidence through the curate gates. Use when someone says "what can I do about X", "create the
  repository", "check that it exists", "run the check", "call the API and record what it says",
  or asks to act on a fact the graph holds as intended. OTO never invokes anything; you do.
---

# Act: the graph's hands, in your hands

An action is a fact the graph holds: what can be done about an entity, described the way an MCP
server describes a tool and bound to the graph. OTO lists actions, says which are ready on which
entities, binds their inputs from the entity, and turns a recorded response into evidence. The
invocation is yours, with the tools you already have. This skill is the protocol.

## The rules that matter most

1. **OTO never invokes.** No command here runs an action. You call the MCP server, the command,
   the endpoint or the script the action declares, and hand the response back.
2. **Nothing that changes the world runs without a named person.** An action whose annotations
   say `readOnlyHint: false` is invoked only after you have shown the bound invocation and the
   person has said yes, and the run is recorded `--by` that person's name, never yours.
3. **A response is evidence, not a fact.** `oto actions record` writes the run and a proposal;
   the fact enters through `oto curate check` and a person's apply, like any other. Never edit
   `graph.json`.
4. **Secrets stay in the environment.** An action names the variables it needs. If one is not
   set, say which and stop; never ask for the value in conversation, never write it anywhere.

## 1. What can be done

```bash
oto actions list --project <root>                       # every action, ready on which entities, why not
oto actions list --project <root> --ready               # only what is ready now
oto query --project <root> actions --on <entity id>     # the actions on one entity, inputs bound (kg_actions)
oto actions show <action.id> --on <entity id> --project <root>   # the invocation you will perform
```

Quote the output. An action that is `not ready` says which precondition fails; do not work around
it. An entity whose status is `intended` is a plan the graph holds, not something that exists:
the action that realises it is the one whose `then` moves it to `current`.

## 2. Confirm

For a read-only action on a read-only schedule, proceed. For anything else, show the person the
`show` output: the transport and target, the bound inputs, what the caller must supply, the
variables it needs, and what a recorded result would assert. Ask for the missing inputs and for a
yes. Record who said yes; that name goes on the run.

## 3. Invoke, with your own tools

| `invoke.transport` | What you do |
|---|---|
| `mcp` | Call the named tool on the named MCP server with the bound inputs (plus what the person supplied). If the server is not connected, say so and stop. |
| `cli` | Run the command ontology with the inputs substituted, in a shell you control. |
| `http` | Make the request: method, URL ontology with `{input}` placeholders substituted, headers; a header value written as an environment variable name is taken from the environment. |
| `script` | Run the script under `actions/` with the inputs as JSON on stdin. |

Keep the raw response. Do not summarise it before recording; the record wants what came back.

## 4. Record

```bash
oto actions record <action.id> --on <entity id> --by "<the person>" --at <YYYY-MM-DD> \
    --response <file or ->  [--note "<why it was run>"] --project <root>
```

OTO writes the run record (`runs/actions/<id>/<stamp>/`), the run as a source document in the
inbox, and, for a `proposal` result, the proposal. It prints the next commands. A `document`
result stops at the inbox: ingest it and author the proposal by reading it, as for any source.

## 5. Through the gates

```bash
oto ingest --project <root>                                            # the run document into the corpus
oto curate start --project <root>
oto curate add --project <root> --from <root>/proposals/<action>.<stamp>.json --dry-run
oto curate add --project <root> --from <root>/proposals/<action>.<stamp>.json
oto curate check --project <root>
oto curate apply --project <root> --by "<the person>" --note "<what the run made true>"
oto build --project <root>
```

A refusal at `add` with `conflict` means the response contradicts what the graph holds (a branch
renamed, an owner changed): that is supersession work for the curate skill, not an overwrite.
After the build, `oto query actions --action <id>` shows the last run, and the entity's card
cites the run document.

## On a schedule

A read-only action may carry a `schedule`. `oto actions list --due --project <root>` lists the
ones whose run is due and that are ready. In repository mode the actions workflow invokes those
it can (http, cli, script) every day and opens a pull request with the runs; an action bound to
an MCP server is skipped there and waits for you: run it through this skill.

## Hand-off

| When | Load |
|---|---|
| The response contradicts a current fact | curate |
| The run's document needs reading into facts (a `document` result) | build-knowledge-base |
| The person asks what the graph says about the entity | query-knowledge |
| The person asks why this action exists or what "intended" means | concierge |
