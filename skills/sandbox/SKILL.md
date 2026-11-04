---
name: sandbox
description: >-
  Set up a Docker sandbox with Claude Code and OTO inside, made from OTO's ready-made kit, and
  connect Claude Desktop's Code tab (or a terminal) to it: a sandbox for an ontology to make (a
  workspace, released as a pack), for a graph on one (a knowledge project on the pack), or for reading
  graphs live from Neo4j. Checks
  what the computer has, asks the person for the few answers only they can give, runs the setup and
  says the one step left in Claude Desktop. Use when someone says "set up the sandbox", "run OTO in
  a sandbox", "a sandbox for the ontology", "a sandbox for our graph", "read our graphs from a
  sandbox", "I want to use OTO from
  Claude Desktop", "connect Desktop to the sandbox", or asks whether their sandbox is ready. Runs
  on the person's own computer, not inside a sandbox.
---

# Sandbox

A sandbox is a small virtual machine on the person's computer, made by Docker Sandboxes (`sbx`)
from OTO's kit. It holds Claude Code, the engine plugin, the OTO registry as a marketplace (its packs turned on
per project with the packs skill), the engine, the Google Cloud tools, LibreOffice and Chromium, and
may reach only what the kit allows. It works on two folders
of the computer, `project` and `code`, so the person opens the files it writes as usual. Claude
Desktop's Code tab drives it over SSH; a terminal drives it with `sbx run`.

`oto sandbox` does the work; this skill decides with the person what it may do.

## Talking with the person

- **Plain, natural language, in the person's words.** Never say flags, file names, commands or what
  a command printed, unless they ask. Say "the sandbox tool", "your Docker account", "your Claude
  sign-in", "your Google Cloud project".
- **Technical details only when the person asks for them.** Never offer them, not even as a choice.
- **The same clear shape every time:** say what we are about to do, ask a few questions at a time,
  read back what you understood in plain sentences, confirm, then say what is next.
- **Their computer, their choices.** Nothing that changes their computer's settings or their
  approvals is done without their yes in this conversation.

## Running the engine

On the person's computer the engine is the `oto` command installed there, the one the plugin
runs (ADR-0014): `oto sandbox ...`. When it is not installed, the session start says so with the
command that installs it, at the plugin's release:

```bash
uv tool install --force "oto-kg[intake,neo4j] @ git+https://github.com/Cynergis/oto@v<the plugin's version>"
```

Without `uv`, say that one small tool is needed first and give its installer: on a Mac or Linux
`curl -LsSf https://astral.sh/uv/install.sh | sh`, on Windows in PowerShell
`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`; then a new terminal.

If `/home/agent/.oto/init.sh` exists, this session is already inside an OTO sandbox: say so, and
that `oto sandbox` is run from the computer, not from here. Stop.

## Two sandboxes, in order

An ontology is made once and used many times, so it has a sandbox of its own and the graphs on it
have theirs (ADR-0012):

1. **The workspace sandbox**, kind *ontology*: its project folder is an ontology workspace, a pack
   in the making, which the ontology-interview skill fills and `oto pack publish` releases to a
   registry. The sandbox's name is the pack's name: the word knowledge projects will start from.
2. **A knowledge sandbox**, kind *knowledge*: its project folder is a knowledge project on that
   pack, its vocabulary derived from the pack and not edited there; the build-knowledge-base skill
   fills the graph. One ontology, a sandbox of its own for each team or client that builds a graph
   on it, so the teams never share a folder or a graph.

The workspace sandbox comes first, and the knowledge sandboxes once the pack is released. The
project is laid out on their computer before the sandbox exists, so the pack a knowledge sandbox
starts from must be on their computer first: a registry that lists it (`oto registry list`), then
`oto pack add <name>`. A pack still in the making is not released yet: say so, and offer the
workspace sandbox first, or a knowledge project with no pack, which grows a vocabulary of its own
the way every project was made before this decision.

## A sandbox from a repository that exists

The first person's sandbox makes the repository. Everyone after them starts from it, because `--repo`
would lay a new project over theirs. `oto sandbox up --name <name> --clone <owner/name>
--github-token-env <VAR>` clones it into an empty project folder, installs the plugins it declares and
stores their token as that sandbox's own, and it never commits, pushes or touches the rules. It refuses
a folder that already holds something else: say what's there, and ask them for another name.

## Who may do what on a graph

Making a graph also makes its private store repository beside it and names the person its steward in
`.github/oto-access.json`, which stewards own. Tell them what is left: `gh secret set
OTO_QUERY_REPO_TOKEN --env oto-main`, with a token that can write to the store alone. To add or remove
someone, they change that file in a pull request, and `oto repo access --apply` sets GitHub to match
(`--check` says where it has drifted). Only people it names as reviewers or stewards can approve a
change on the reviewed route. `oto registry fleet` shows every graph's versions and drift in one view,
for whoever looks after the platform, and `oto repo retire` archives a graph when it's done. Check that the organisation's base permission is `none`: otherwise every
member can read every repository, whatever the file says.

## A sandbox that reads graphs live

Someone who only asks questions of graphs already in Neo4j needs neither of those. Their project
folder holds connections, with no documents and no copy, and every answer comes from Neo4j at that
moment. For each graph, its steward gives them its address, its database, the slug it was loaded under
and its login. The login comes through a password manager, never in this conversation: if they paste
one here, say so and ask them to change it.

Say what this accepts, once: the login sits inside the sandbox, so Claude there could read it, and could
do whatever that login may do. A read-only login is better where their Aura tier offers one. With a
yes, on their computer, one per graph:

```bash
oto graphs add <name> --uri neo4j+s://<id>.databases.neo4j.io --database <database> --slug <slug> --subject "<what it holds>" --project ~/<sandbox>/project
```

Then they set each login in their own terminal, and make the sandbox from that same terminal, because it
reads the logins from there. Hand these over rather than running them: `oto graphs list` names the
variables, and `read -rs` keeps a password out of the shell's history.

```bash
export <NAME>_NEO4J_USER=<user>
read -rs "<NAME>_NEO4J_PASSWORD?Password: " && export <NAME>_NEO4J_PASSWORD
oto sandbox up --name <sandbox>
```

A login is set when the sandbox is made. A graph with a new login means making the sandbox again
(`--recreate`, after their yes): its folders stay, and what is only inside it goes.

## 1. Where things stand

Run `oto sandbox status --name <name> --json` (`oto-sandbox` unless the person named one). Read it
and say in a sentence or two what is there and what is missing:

| It says | Then |
|---|---|
| `sbx` null | the sandbox tool is not installed: give the command for their system (a Mac: `brew trust docker/tap && brew install docker/tap/sbx`; Windows 11: turn on Windows Hypervisor Platform in an administrator PowerShell, `Enable-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform -All`, restart, then `winget install -h Docker.sbx`). They run it; you wait, then status again. |
| `sbx_supported` false | the sandbox tool is older than OTO's kit needs (0.51.0 or later): give the upgrade for their system (a Mac: `brew upgrade docker/tap/sbx`; Windows: `winget upgrade Docker.sbx`; Linux: `sudo apt-get install --only-upgrade docker-sbx`). They run it; you wait, then status again. A sandbox they already have keeps running; made again later (`up --recreate`, with their yes), it gets the current kit. |
| `signed_in` false | they sign in to Docker once: `sbx login` in a terminal opens the browser. Wait, then status again. |
| `policy` false | no network policy is chosen yet: ask (§2). |
| `anthropic_approved` false | the kit needs their approval to use their Claude sign-in: ask (§2). |
| `sandbox` set, `from_kit` true, `oto` says ready, `ssh` true | it is ready: go to §4. |
| `sandbox` set, `from_kit` false | a sandbox of that name exists but is not OTO's: ask for another name, or whether to replace it (what is only inside it is lost). |
| `outside_plugins_summary` does not start with "blocked" or "allowed" | things from outside would load in the sandbox (§5): say what, in its words, and what it says fixes it. |

## 2. Ask, a few at a time

One answer decides most of it: **what the sandbox is for**, in a word or two (a client, a domain, an
ontology to make). From it, propose the rest and let the person change any of it, as a select:

- **The sandbox's name**: the answer, lowercased, letters, digits and hyphens (`kanban-test`).
  SSH reaches it as `<name>.sbx`.
- **Where its folders go**: a folder named after it in their home folder (`~/<name>`, holding
  `project` and `code`).
- **What they are making**, the kind: a **knowledge project** (a graph on an ontology that exists,
  started from a pack) or an **ontology workspace** (an ontology to make, a pack in the making,
  which the ontology-interview skill fills). Recommend from the answer: an ontology named as the
  thing to make is a workspace; a client, a team or a body of documents is a knowledge project. For
  a workspace the sandbox's name is the pack's name, so propose the ontology's name, lowercased.
- **The pack** the graph is on, for a knowledge project: `oto pack list` on their computer says
  which are installed; propose the one that fits the answer. A pack they name that is not installed
  is fetched with `oto pack add <name>` after their yes, when a registry lists it (`oto registry
  list`; `oto registry add <url>` for one it does not know). A pack no registry lists is not
  released yet: the workspace sandbox comes first (above), or the project starts with no pack.
- **The repository** that backs the project: `<their GitHub login>/<name>`, proposed from
  `gh api user --jq .login` on their computer (or an organisation they name), created private for
  them. Show it with a checkbox **no repository** beside it: ticked, the repository name is cleared
  and the project stays local to the folders.
- **The GitHub token**, only when a repository is made: ask which **environment variable** on their
  computer holds a token with the repo scope (`GITHUB_TOKEN`, say). Name the variable and never the value:
  the engine reads it to create the repository and push once, then stores it as the sandbox tool's own
  GitHub secret for that sandbox, so the agent inside pushes and the token never enters the sandbox or
  a file.
- **Their Google Cloud project's id**, if the work uses Google Cloud: the id, not the name; the
  console shows it under the name. It is given to the sandbox as `PROJECT`. They may have none yet.
- **The network policy**, only when none is set: "balanced" is the usual one (Claude, code hosts and
  package sites allowed, anything else asked about); "deny-all" closes everything the kit does not
  name; "allow-all" opens everything. Recommend balanced.
- **The approval for their Claude sign-in**, only when it is missing. Say what it means: the sandbox
  may use their Claude sign-in, for Anthropic's sites only; the sandbox tool adds it to requests on
  their way out, so the sign-in itself never enters the sandbox. The sandbox tool asks this itself
  when started from a terminal; started from here it cannot ask, and without it Claude in the
  sandbox asks them to sign in at every message. Ask for a plain yes.

Only if the person says they want their own plugins or connectors in the sandbox too, explain §5 and
ask whether to make it that way. Never offer it otherwise.

Read the answers back in a sentence and confirm: the name, the folder, the kind, the repository or
"no repository", and the variable the token is in. For a knowledge project with a repository, add one sentence on how
changes will reach it: every change goes through a pull request, a change they confirm in their own
session merges on its own, and one drafted from documents waits for a second person; on a pack,
the pack's routes come with the project and may narrow that.

## 3. Set it up

With their confirmation, first dry-run, then run:

```bash
oto sandbox up --name <name> [--dir <folder>] --kind knowledge|ontology [--pack <pack>] --repo <login/name> --github-token-env <VAR> [--project-id <id>] [--init-policy balanced] [--approve-anthropic] --check --json
oto sandbox up --name <name> [--dir <folder>] --kind knowledge|ontology [--pack <pack>] --repo <login/name> --github-token-env <VAR> [--project-id <id>] [--init-policy balanced] [--approve-anthropic] --json
```

`--pack <name>` for a knowledge project on a pack, one installed on their computer; without it the
project grows a vocabulary of its own. `--no-repo` in place of `--repo` and the token variable when
they ticked "no repository". Pass
`--init-policy` only with the policy they chose, `--approve-anthropic` only with their yes,
`--allow-outside-plugins` only when they asked for their own plugins in the sandbox (§5), `--recreate`
only when they agreed to replace an existing sandbox. Tell them it takes about a minute the first
time, more on a slow connection; the second run takes seconds.

What `up` does with a kind: it lays the project out in the `project` folder on their computer before
the sandbox is made (a knowledge project with the repository workflows, or an ontology workspace with
its trial project and its check and publish workflows), creates the repository, pushes the first
commit from their computer, and stores the token for the sandbox. A folder that already holds a
project is left as it is. A knowledge project started from a pack has its vocabulary `derived from`
the pack, which `oto status` says inside, and once the sandbox is ready `up` installs inside it, at
project scope, the pack plugins the project declares (the kit brings the engine plugin alone), so the
first session has the pack's skills and views; the report says which. A pack added to the project
later is the packs skill's job, inside.

For a knowledge project with a repository on GitHub, `up` also sets the **branch rules** on its `main`: pull requests required, the
checks `oto checks` and `oto route` required, no approvals at the branch level since the gate asks
per route ([ADR-0013](../../docs/adr/0013-three-routes-into-main.md)) but a code owner's for what the
gate runs on. The person whose token made the repository is named its code owner,
in the first commit, and the two workflows that push to `main` get a deploy key of their own, which
only `main` can use. A warning that the rules were not set says why, and `oto repo rules --apply` in
the project folder sets them later.
A knowledge project on a pack that declares routes carries **the pack's routes** in its
configuration, derived like the vocabulary: which routes the project allows, the classes a session
may change without review, the guardrails for transcripts. `oto status` says it inside (`routes
from the pack <pack> @<release>`). Say both to the person, in plain words.

When it is done, read `outside_plugins_summary` back in plain words (§5): it says whether the sandbox
uses only its own plugins. Never say the sandbox is ready without it. Say the repository's address
when one was made.

`ok: false` comes with a `problem` and a `fix`: say both in plain words, and do what the fix says
only if it is theirs to agree to (ask) or theirs to do (wait for them). Never work around it.
`warnings` say an existing sandbox differs from what they asked (other folders, another project):
say so and ask whether to replace it.

## 4. Connect Claude Desktop

Say the steps from `next`, in words, once:

1. In Claude Desktop, the **Code** tab, a **new session**.
2. In the environment menu, **SSH**, then **Add SSH connection**: a name they will recognise, the
   host `<name>.sbx`, the port and the identity file left empty.
3. Choose that connection, then the folder, which is their `project` folder.

In that session Claude runs inside the sandbox, with the engine plugin alone: the packs the work
needs are chosen there, from a checklist or on advice, with the packs skill (`/oto:packs`), which
turns them on for the project. In a workspace sandbox the first thing to ask for is the
ontology-interview skill; in a knowledge sandbox, the build-knowledge-base skill, or the start skill
when the way in is not documents. If it asks to sign in once, they do (`/login`); if it asks at every
message, the approval is missing: §2, then `up --recreate`. From a terminal instead:
`sbx run --name <name>`, or `ssh <name>.sbx`; either shell lands in the project folder (a sandbox
made before 0.16.6 lands in the tool's own folder until `up --recreate`).

To see a served graph from their own browser: in the sandbox session, `oto serve --project . --http 8798`
(it binds all interfaces there and needs no token), and on their computer the address `up` said: usually
`http://localhost:8798/`, 8799 for a second server, a pack's view. Two sandboxes serve on the same ports
inside, and the computer cannot hold one port twice, so the second sandbox gets the next free host ports
(8800 and 8801, say): `up` says which, in `ports` and `next`, and `oto sandbox status` repeats it as
`<host port>-><sandbox port>`. Say the host port to the person as the address to open; the sandbox port
is what `oto serve` inside binds. `--publish <port>` adds others.

Later, `oto sandbox status` says whether it is still ready; `oto sandbox up` starts it again after a
restart of the computer. Every sandbox on the computer, and cleaning up the ones no longer used, is the
sandboxes skill (`/oto:sandboxes`: `oto sandbox ls`, `oto sandbox rm`).

## 5. What the sandbox uses

Say this once, when the sandbox is ready, in a sentence or two: the sandbox uses only the OTO tools
installed inside it. What Claude Desktop brings from their computer, and the plugins, skills and
connectors of their claude.ai account, are switched off there, so the work in the sandbox does not
depend on what happens to be on their computer, and the sandbox cannot reach their mail, files or
calendar through those connectors.

Setting up switches off the plugins Claude Desktop has on their computer before the first session,
so even that one starts with only the sandbox's own. One thing to know: a plugin they add on their
computer later is still there in the first session after that. Claude says so at the start of that
session and switches it off; a new session, or typing `/reload-plugins`, works without it. Running
the setup again before that session switches it off in advance.

If they want their own plugins and connectors in the sandbox, it is made that way from the start
(`--allow-outside-plugins`); an existing sandbox is made again for it (`--recreate`, after their yes).
`status` says which way a sandbox is (`outside_plugins`).
