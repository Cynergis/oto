# Changelog

What each engine release changed for the people who write ontologies, run projects, or read the
exports. Ontologies and packs carry their own `release` and changelog in their manifests; this
file is the engine's.

## 0.14.5 — 2026-10-30

**A graph served in the sandbox opens in the computer's browser.** One pull request (126).

- **Inside the kit, `oto serve` binds all interfaces and needs no token.** The engine knows it runs inside a
  sandbox made from OTO's kit (the kit sets `OTO_SANDBOX`; its files are under `~/.oto`). There, `oto serve
  --http 8798` listens on all interfaces, the start-up message says to open `http://localhost:8798/` on the
  computer, and no token is asked for: the sandbox tool publishes a port to the computer's loopback only, so
  all interfaces inside is the computer and nothing beyond it. Everywhere else the rule is unchanged: a bind
  beyond loopback needs `OTO_SERVE_TOKEN`. A server on the sandbox's own loopback is unreachable from the
  computer, which is what made the served graph invisible before.
- **`oto sandbox up` publishes ports 8798 and 8799** to the computer's localhost when it creates a sandbox
  (`--publish <port>` chooses others, `--publish 0` none); on an existing sandbox it publishes what is missing
  and says that a port added to a running sandbox forwards from its next start. `oto sandbox status` lists the
  published ports; `up` says what to run inside and what to open.

**Migration.** A sandbox made from an earlier kit publishes no port: `oto sandbox up` on it publishes both,
then `sbx stop <name>` and the next connection starts it with the forward in place. The engine inside such a
sandbox detects the kit from its files, so serving works as soon as the ports are there.

## 0.14.4 — 2026-10-30

**A sandbox starts with the engine alone, and two skills look after it.** Two pull requests (123 and 124).

- **The engine alone.** A new sandbox installs the engine plugin (`oto@cynergis-engine`) and adds the
  registry as a marketplace, and installs none of its packs. The packs a project needs are chosen from
  the session Claude works in, in Claude Desktop over SSH or in a terminal, with the **packs skill**
  (`/oto:packs`): a checklist of what the registry offers (the question tool with several answers, grouped
  by category, what is already on left out), or advice from what the project composes, then
  `claude plugin install <pack>@cynergis --scope project` and `oto lock --use`, so the choice lands in the
  project's settings and its lock. The one step left, `/reload-plugins`, is the person's.
- **Every sandbox, and cleaning up.** `oto sandbox ls [--json]` lists every sandbox on the computer with
  its status, its kit, its folders and whether each still exists, when it was created and last used, days
  idle and whether SSH reaches it, and flags Claude Desktop's saved SSH connections to sandboxes that no
  longer exist (read from the app's own file, never written). `oto sandbox stop <name>...` and
  `oto sandbox rm <name>...` act by name; `rm` removes the containers, the state and the sandbox's secrets
  and keeps the project and code folders. The **sandboxes skill** (`/oto:sandboxes`) proposes what could go
  (stopped and idle, folders gone, not OTO's kit, a stale connection) as a checklist, removes after a yes,
  offers the Desktop sessions for archiving through the app's own tools, and names the connections only
  the person can remove, in Desktop's SSH environment menu.

**Migration.** Nothing changes for a project. A sandbox made from an earlier kit keeps its packs; the
packs skill works there too once its engine plugin is reinstalled from the marketplace (Claude Code
caches a plugin by version, so a skill added between releases needs `claude plugin uninstall` and
`install` once; from this release an ordinary update brings it).

## 0.14.3 — 2026-10-29

**The engine comes from its own marketplace, and CALM is a pack of the registry.** Three pull requests
(119, 120 and 121) and two decisions, [ADR-0008](docs/adr/0008-a-framework-is-a-pack-of-the-registry.md)
and [ADR-0009](docs/adr/0009-the-registry-carries-no-engine.md).

- **The registry carries no engine.** The engine plugin is installed from this repository's own
  marketplace, `cynergis-engine`: `/plugin marketplace add Cynergis/oto`, then `/plugin install
  oto@cynergis-engine`. The registry, Cynergis/oto-registry, lists extensions and packs of the engine and
  never the engine itself; every pack `oto pack new` or `publish` writes depends on `oto@cynergis-engine`,
  which the registry's marketplace allows to cross (`allowCrossMarketplaceDependenciesOn`), and `oto pack
  check` still accepts the bare `oto` of packs written before. The release workflow no longer opens pin
  pull requests for the engine; `oto lock` finds the engine plugin in whichever known marketplace lists
  it; the repository workflows the engine writes install `oto@cynergis-engine` (they named a marketplace
  that never existed under `oto@oto`); the catalog pages and the scaffolded registry README say to add the
  engine's marketplace first.
- **CALM is the registry's `calm` pack**, 1.0.0, with the adapter as the module `oto_calm` in its
  `code/`, its guide and its tests: `/plugin install calm@cynergis` or `oto pack add calm`, and `oto arch
  import --framework calm` finds it from any architecture project. The engine ships no framework adapter:
  on a machine with the engine alone, `oto arch import` and `export` name the framework they lack and say
  which packs provide one. The engine's own tests exercise the core's handling of a framework's model
  through a `plain` adapter they carry.
- **The sandbox kit** adds the engine's marketplace before the registry, installs `oto@cynergis-engine`
  and the `calm` pack with the others, and tells its Claude which plugin list is the sandbox's: Claude
  Desktop's `ListPlugins` and `ListSkills` describe the person's claude.ai account, `claude plugin list`
  describes the sandbox (`files/home/.claude/CLAUDE.md`).

**Migration.** A machine that installed `oto@cynergis` adds the engine's marketplace, installs
`oto@cynergis-engine` and uninstalls `oto@cynergis`; packs installed before are reinstalled once so their
cached manifests name the new dependency. A project's `.claude/settings.json` names `oto@cynergis-engine`
and both marketplaces, then `oto lock`. A project that imports CALM models installs the `calm` pack; a
project that already holds CALM facts changes nothing. An existing sandbox runs the same three plugin
commands; a new one from this kit needs none of it.

## 0.14.2 — 2026-10-28

**A pack carries its own code, and the factory leaves.** Two pull requests (116 and 117) and one
decision, [ADR-0007](docs/adr/0007-a-use-case-lives-outside-the-engine.md): a use case of the graph
lives in a repository of its own.

- **`code/` in a pack.** A pack from outside the engine, in the user's ontologies directory or an
  installed plugin, brings its modules in its own `code/` folder, declared in the manifest's `carries`.
  When the engine loads anything the pack provides (a stage, a command, an endpoint, a hook, an
  adapter), it puts that folder first on the import path, once, so the modules the manifest names
  import from the pack itself and nothing has to be installed on the machine's Python path. The
  engine's own packs carry no `code/`.
- **The factory is in its own repository**, [Cynergis/oto-factory](https://github.com/Cynergis/oto-factory),
  listed in the registry as `oto-factory` 4.0.0 (the plugin version is the pack release from now on).
  Building software from the graph is something one does with a knowledge graph, not a knowledge
  graph: the plugin (agents, hooks, the spec-context skill, the Actions workflow), the `factory-run`
  ontology with the `oto factory` commands in its `code/`, its tests and its E2E section left the
  engine's repository, which lists the engine plugin alone in its marketplace. Install the factory
  with `/plugin install oto-factory@cynergis` or `oto pack add https://github.com/Cynergis/oto-factory`;
  this release is the first that loads it. What a factory needs from the engine stays: `oto work
  event verdict` takes a verdict from any factory, `oto policy snapshot` and `oto policy denials`
  with the reader a guard copies are the policy pack's, and `oto arch measure` is the architecture's.

**Migration.** Nothing changes for a project. A machine that used `oto factory` from the engine
installs the factory pack once; the commands and the run graph are the same. The kit image
`ghcr.io/cynergis/oto-gcp:0.14.2` carries this engine.

## 0.14.1 — 2026-10-28

**The migration carries the project's vocabulary.** One fix (pull request 114), found by migrating
the first real project to 0.14.0: `oto arch migrate --framework calm` renamed the graph's attributes
and left the project's own copy of the vocabulary and its questions at the former names, so the gates
still demanded `calm_id` and `oto arch compile` was refused. The migration now rewrites the project's
`ontology.config.json` too (each former declaration becomes the architecture pack's own declaration of
the neutral attribute, what was required stays required, the two payload attributes become one, a
`Document` gains `framework`) and the questions' cited terms, and reports the three counts. A project
that ran the 0.14.0 migration runs it once more; it changes only what is left.

## 0.14.0 — 2026-10-28

**The core and the packs.** Everything since 0.13.0 (pull requests 105 to 112): the decision that
narrows OTO's core to the knowledge graph, its tools and its deploy, and the refactoring that follows
from it, in five steps. This release renames attributes and moves files, so it carries migration
notes; read them before upgrading a project built on the architecture pack.

### The decision ([ADR-0006](docs/adr/0006-the-core-and-the-packs.md))

OTO's core is the knowledge graph's lifecycle with its tools, the estate and the reified model it
is described in, and the deploy of the graph. An architecture framework is a pack plus an adapter;
a domain feature is a pack plus its tools, loaded only when the pack is composed in the project. No
pack depends on a framework pack. The documents, the README and `oto --help` draw the line between
the core and the packs.

### The seams (step 2)

A pack's manifest declares what it provides beyond its vocabulary, read by `oto/extensions.py`:
build stages (`{name, module, owns}`, after the core's targets and before the site, owning the
build paths a partial build stashes), commands (`{name, module, label}`), served endpoints
(`routes(project)`), write hooks (before `curate apply`, `decide` and `promote`), read hooks (before
the served native read), status hooks (the project's status snapshot) and framework adapters
(`import`, `export`, `migrate`). Stages, endpoints and hooks load only for the packs composed in the
project, a pack being composed when every class it declares itself is in the vocabulary; commands
and adapters are discovered from every pack the machine has. The manifest checker holds the shapes.
The core names no pack: `builder.STAGES` is the seven core stages, the CLI imports the core commands
and discovers the packs', and a pack the engine has never heard of plugs in the same way.

### CALM out (step 3)

The architecture pack is framework-neutral (release 5). A node a framework's model wrote carries
`external_id`, `external_type` and `external_payload`; the model's `Document` carries `framework`
and the header. CALM is the `calm` pack: an adapter (`oto/packs/calm.py`) its manifest provides,
chosen by `oto arch import --framework calm --file <model>` and `oto arch export --framework calm`,
with the mapping from CALM's nine node types in its README. `oto arch migrate --framework calm
--by <who>` rewrites a graph written before release 5. The compile reads `arch.models` as
`[{"framework", "path"}]`; a framework's name as a key (`"calm": [...]`) still reads.

### Policy and IAM out (step 4)

The policy pack stands on `data` and `agent` (release 4). The generated system's bindings are its own
class, `IamBinding` (`provider`, `resource_uri`, `bindings`, `withheld`, `generated_by`), one per bound
resource, which `binds` the resource, `grants` the principals and `derives_from` the rules; `resource_uri`
on `Table`, `DataStore`, `Component` and `Interface` is the policy pack's term, and the architecture pack
(release 6) drops `resource_uri`, `Control.generated_by` and AR12. The calm adapter exports a binding
node as a CALM control on the bound node and on the components that run as the granted principals,
when both packs are composed. The compiler, the snapshot, the IAM derivation, the two build stages,
the command, the write hook and the served read hook live in `oto/packs/policy`. PL8 is reworked; PL9
asks what is bound on a resource. `oto publish` carries every composed pack's stage output with the
store.

### The remaining tools out (step 5)

- **Work and communication:** the engine keeps the write path as `oto/assertion.py` (`commit`,
  `identity`, `gates`, `WriteError`), used by `decide`, the graph descriptors, `publish`, `curate`
  and `ingest`; the work items, the board, messages, the inbox and reminders live in
  `oto/packs/work`, with a status hook that puts the board in the status snapshot. A project without
  the pack has no board.
- **Data:** introspection, lineage, usage and meaning live in `oto/packs/data`; the engine keeps
  `oto/naming.py` (a slug, the graph's ids), which every pack uses.
- **ddd:** the storming importer lives in `oto/packs/ddd`.
- **The factory:** the spec, the plan, the scope, the run graph, criteria and deviations live in
  `oto/packs/factory`; measuring a requirement (`oto arch measure`, H6) is the architecture's and
  moves into `oto/arch.py`.

### Migration notes

- **A project on the architecture pack built before this release** carries `calm_id`, `calm_type`,
  `calm_metadata`, `calm_details`, `calm_header` and `calm_option`. Run once, then build:

      oto arch migrate --framework calm --by "<you>" --project <project>
      oto build --project <project>

  The former names are not read until the graph migrates: an export before it writes a model with no
  nodes. The migration keeps the previous graph as `graph.previous.json`, records an audit record
  naming the nodes, and refuses while a candidate is open.
- **`oto arch import --calm <file>` and `oto arch export --calm` are gone.** Use `--framework calm
  --file <model>` and `--framework calm`; with one adapter on the machine the framework is the default.
- **`project.config.json`'s `arch` section** may now list `models` as `[{"framework", "path"}]`; the
  `calm` key still reads as before.
- **The IAM build output** writes `build/iam/bindings.proposal.json` where it wrote
  `controls.proposal.json`, and its manifest counts `proposed` nodes where it counted `controls`.
  A graph that holds the former generated `Control` nodes keeps them as history; `oto policy iam
  --apply` writes `IamBinding` nodes beside them, and the architecture pack no longer declares
  `Control.generated_by` or `resource_uri`, so `oto ontology check` names those attributes on the old
  nodes until they are retired.
- **Spec files written by `oto factory spec`** name the component by `external_id` and `external_type`.
- **Code that imported the engine's modules directly** (`oto.policy`, `oto.iam`, `oto.work`,
  `oto.data`, `oto.lineage`, `oto.usage`, `oto.meaning`, `oto.ddd`, `oto.factory`) finds them under
  `oto.packs.<pack>`; the write path is `oto.assertion` and the shared helpers `oto.naming`. The
  commands are unchanged.

## 0.13.0 — 2026-10-27

**The generated system's IAM, and the roadmap closed.** Everything since 0.12.0 (pull requests 102
and 103): E7, the one item the roadmap had marked "later" and left for after the release, and the
roadmap graph brought to a consistent end.

### E7: the generated system's IAM, derived from the policy, shipped with the system (ADR-0005)

- **The model, in two packs.** The policy pack (release 3) composes on the architecture pack too: a
  `Component` or a `System` `runs_as` a `Principal`, the service account it runs under; a
  `Permission` names the platform role it maps to (`cloud_role`), a fact the organisation states and
  never a catalogue in the engine; a `Table` says where it is on the platform (`resource_uri`);
  `safeguards` is widened to `Table` and `Column`; a generated `Control` `derives_from` the rules it
  came from. The architecture pack (release 4) lets a `System`, a `Component`, a `DataStore` and an
  `Interface` carry `resource_uri` and marks a `Control` a command derived with `generated_by`. PL8
  asks what runs as a principal and which generated controls bind it; AR12 lists the generated
  controls with what each safeguards and where that is on the platform.
- **The derivation.** Read through the roles each principal holds, the same active rules that compile
  to Cedar give the platform's bindings: a member (`serviceAccount:` for a service, `user:` for a
  person), a role, a resource. A forbid withholds the binding a permit would have made for the same
  member, resource and action, so the bindings and the Cedar never disagree. A permission without a
  platform role, a resource without a place and a principal without an identity are named and not
  bound, never guessed. The built graph is read with its derived attributes, so a table whose column
  is personal data stays out of a `pii=false` selector.
- **The output, beside the policy bundle.** The `iam` build stage and `oto policy iam` write
  `build/iam/`: `bindings.json`, `gcp.json` (one policy per resource in the shape `set-iam-policy`
  takes; GCP first, another provider is a second shape over the same derivation, `policy.provider`),
  `controls.proposal.json`, `iam-bindings.md` and a manifest hashed and signed with `policy.sign_with`;
  `oto policy verify build/iam` checks it and `oto publish` carries it with its hash.
- **The controls.** One generated `Control` per resource, in the architecture vocabulary, that
  safeguards the resource and the components running as its members and derives from the rules;
  they enter the graph only through the gates (`oto policy iam --apply --by <who>`, the loop
  `oto arch compile` uses, now shared as `arch.apply_proposals`) and come out in `oto arch export
  --calm` under the component's controls. OTO never enforces the bindings: they ship with the
  system and the platform enforces them, while the hooks, the snapshot and the served engine keep
  enforcing the policy on OTO's own actions.
- **Also.** The policy sample's invoice intake service runs as its own account and writes the
  invoices table, so the ledger sample compiles four active rules, not three; the cross-pack
  collision test admits a widening from a pack that extends `architecture` and still refuses a
  second meaning; E2E section 32.

### The roadmap

- **ADR-0005 in the graph**, proposed from `docs/adr` through curate as the four before it, governing
  Epic E, decided by a named person, its record ingested into the corpus and the archive.
- **Phases 1 to 4 reached.** Their milestones closed before a milestone could be decided and still read
  `planned` while every epic in them was deployed; each is now recorded as reached by a named
  person on the day its last epic deployed, so all six phases read reached by a person's assertion,
  the audit chain intact. The roadmap as written is complete: fourteen epics deployed, six phases
  reached, five decisions governing the epics they shaped. H7, authoring in the graph and compiling
  to CALM, stays gated on its decision.

## 0.12.0 — 2026-10-27

**The roadmap's six phases, delivered.** Everything since 0.11.31 (pull requests 37 to 100): the
work, communication, data, architecture, ddd, factory-run and policy packs; the audit log, tracing
and decisions as nodes; graphs that know each other; the software factory as a second plugin; the
ontology explorer; policy in the graph with its guards and gates; and the communication pack closed
with reminders. Phases 5 and 6 in full first, then what phases 1 to 4 brought since the last release.

### Phase 6: the ontology explorer, and policy in the graph (Epics D and E; N2, N5)

- **The ontology as a thing to browse (D1 to D6).** The vocabulary is projected into a navigable
  model, carried in the graph payload and served at `/api/ontology`: every class with its parents,
  children, relations with cardinality and inverse, attributes with their values and whether a person
  decides them, and the count of things of that class. The workbench's Ontology tab walks it by links.
  Beside it: the rules as a person reads them, looked up by class with inheritance (`/api/rules`); the
  lexicon in every declared language, searched by any word and landing on the element it names
  (`/api/lexicon`); the graph descriptors as a page with near-duplicates flagged (`/api/graphs`); from
  any entity, the rules, terms, graphs, decisions and files that bear on it (`/api/links`, and the
  entity page's Related section); and versions, `oto ontology diff --from <git ref>` comparing the
  vocabulary at a ref with the working tree or another ref, served at `/api/ontology/diff`, shown on a
  Versions page, and posted by the CI workflow as one sticky comment on every pull request that touches
  an `ontology.config.json`.
- **The policy pack (E1), compiled (E2).** On the data pack: a `PolicyRule` permits or forbids one
  `Permission` (an action on a kind of resource, narrowed by a selector) for the roles and teams it
  names, on every resource the selector admits or only on those it singles out; a `Table` and a
  `Column` carry a classification and whether they hold personal data, derived up from a column to its
  table. A rule is a draft until a named person activates it (`oto decide`). `oto policy compile`, and
  the `policy` build stage, write `build/policy/`: the rules in Cedar (ADR-0004), the same rules as
  JSON for the engine's own evaluator and the hooks, and a manifest with the version, per-file hashes, a
  content hash and an HMAC signature when the project names a key; `oto policy verify` checks it;
  `oto publish` carries it beside the store.
- **The snapshot an agent runs under (E3, E4).** A `Principal` holds roles; an `Agent` is granted some;
  `oto policy snapshot --agent --principal` writes the signed intersection of what the two may do,
  with the paths it reaches through the code map. The engine plugin gains a PreToolUse guard and the
  factory's guard reads the same file through one plain-Python reader: a write under a denied path is
  refused naming the rule, a write under no permitted path naming what is permitted, an untrusted
  snapshot blocks every write, and every refusal is an event that `oto policy denials` and
  `oto factory run sync` turn into audit records. Two packs that each widen the same base relation
  now compose to the union.
- **Freshness and the server (E5, E6).** A snapshot expires (`--ttl`), and before `curate apply`,
  `decide`, every `oto work` write and `promote` the engine re-checks it: intact, signed when the
  project signs, not expired, and still what the graph says now; a project may require one. The
  served `kg_read` is held to the caller's principal (`X-Oto-Principal`, `OTO_PRINCIPAL`), every table
  the query names admitted by a permit and covered by no forbid, with refused reads in the audit log.
- **The inbox under a principal, reminders on a schedule (N2, N5).** `oto work inbox` is read under
  the identity the session runs under and is theirs alone; `oto work remind --at <date>` sends one
  reminder a day for every pending message past its due date, a message of its own that is never a
  reply (communication release 3, `reminder_of`, CM4); a scheduled workflow runs it for the roadmap
  and opens a pull request with the reminders. The phase 6 milestone is reached.

### Phase 5: the architecture graph, the domain, the factory (Epics H, I, J; M4)

- **The architecture pack, aligned with CALM 1.0 (H1 to H6).** The graph agents consult before they
  change code: CALM nodes, relationships, controls and flows as facts; `oto arch import --calm` reads
  a model through the gates and `oto arch export --calm` writes it back; `oto arch map` maps a
  repository's code to components and `oto arch compile` runs on merge through the architecture
  workflow; `arch_context` is what an agent reads before it edits and `oto arch impact` is what a
  decision reaches; measurements of a budget are promoted as facts.
- **The ddd pack (I1 to I8).** Subdomains, bounded contexts, use cases, events, commands, aggregates
  and rules on the architecture pack; `oto ddd storm` reads an event-storming board in; readiness is
  a named person's decision (`oto decide`); contracts are versioned nodes, `oto factory spec`
  projects a component's spec as schema-checked, hashed JSON, `oto factory plan` derives the build
  order from contract dependencies, `oto factory criteria` draws acceptance criteria from the graph,
  `oto factory deviate` records what was impossible as specified, and each run gets a graph of its
  own (factory-run pack) whose results are promoted.
- **The software factory, a second plugin (J1 to J7).** `oto-factory` in the same marketplace:
  runner, evaluator and aggregator agents; a PreToolUse guard that holds a run to its write scope and
  a Stop hook that runs the loop to an iteration cap; the `spec-context` skill a runner loads first;
  the same hooks in GitHub Actions; `oto factory run metrics` from the run graph; released as 0.2.0,
  then 0.3.0 with the policy snapshot. A failed or escalated build blocks the work item on a named
  person (`oto work event verdict`, M4).

### Phases 1 to 4 since 0.11.31 (pull requests 37 to 77)

- **Resolution, survey and the bench (37 to 48).** A name resolves to the current fact; the preview
  carries questions, briefs and actions; the bench scores right, wrong or abstained and a guess costs;
  lexicon entries suggested by embeddings and accepted by a named person; the survey's stages with
  evidence against gold terms and a person's decision per stage; a number, date or code on a fact must
  be stated by its source; near-duplicate entities shown; `oto capture` and `curate check` tightened.
- **The workbench and the end-to-end scenarios (49 to 53).** Northwind, and Northwind with mistakes,
  as scenarios; the workbench, one read-only app over a project snapshot, published beside the static
  site; ingest runs closed; CI checks the committed UI bundles match `ui-src`.
- **The selected text and tools (54, 55).** `oto clipboard`, a skill and a prompt hook bring in the
  selected text (L1); Actions are Tools (L2).
- **Deploy and connectors (56, 57, 73, 74).** One deploy config, environments, the same build promoted
  (B1, B4); connectors behind one interface with a manifest, a schema compiler and a conformance kit
  (K1, K3, K7); overlay connectors and schema introspection; Postgres and BigQuery overlays and
  `kg_read` behind the deploy config (K2, K5, K8).
- **The work pack (58 to 61).** Three states from transitions, blocks with context, `oto work set`,
  the board, the workbench's Work page, `oto work notify`; the inbox at session start, replies that
  resolve, a merged-PR event; the roadmap itself as a work project in the repository.
- **Accountability (62 to 66).** The audit log, one hash-chained record per write, verified and keyed
  to nodes (F2 to F4); tracing with OpenTelemetry spans behind the `otel` extra and the trace id in the
  audit record (F1); decisions as graph nodes compiled from ADRs with frontmatter (G1 to G3).
- **Graphs that know each other (67 to 70).** Every graph holds a descriptor of itself and of the
  graphs it depends on (A1, A2); `kg_dependencies` and `kg_call` over HTTP and the concierge root
  (A3, A5); near-duplicate descriptors linted (A4).
- **The data pack (71, 75 to 77).** Schema, lineage, usage and meaning as facts: tables and columns
  introspected, lineage from a dbt manifest or SQL, usage from the query log with the statement text
  hashed, meaning drafted by an agent and confirmed by a named person, the data graph under a
  concierge (C1 to C5).

Every feature above was delivered as a test-first pull request with its section in
`docs/E2E-TESTING.md` (sections 20 to 31 are new) and its row in `docs/ARCHITECTURE.md`. The
oto-gcp kit, the plugin manifests and the marketplace pin this version.

## 0.11.31 — 2026-10-18

**A sandbox loads only its own plugins.** A Claude Desktop SSH session brought the plugins of the
person's computer into a sandbox made from the oto-gcp kit, and the Claude sign-in brought their
claude.ai account's plugins, skills and connectors. Now the kit switches all of them off, and only the
OTO plugins installed in the sandbox load.

- **What it switches off.** The kit's `lock-plugins` merges these into the sandbox's
  `~/.claude/settings.json`:
  - `"<name>@inline": false` for each plugin Desktop copied in;
  - `syncClaudeAiPlugins: false` and `syncClaudeAiSkills: false`;
  - `disableClaudeAiConnectors: true`.

  Every other key is left as it is, and a second run changes nothing.
- **When it runs:** at every sandbox start, and at every session start through a hook.
- **Before the first session.** `oto sandbox up` reads the plugins Claude Desktop would hand over from
  this computer, and switches them off in the sandbox beforehand: the account's synced plugins, and
  Desktop's bundle of the account's skills. So even a new sandbox's first session has only its own.
- **A plugin added on the computer later** is loaded in the first session that brings it. The hook
  switches it off and tells the person to start a new session or type `/reload-plugins`. Running
  `oto sandbox up` again before that session switches it off in advance.
- **`oto sandbox up --allow-outside-plugins`** creates a sandbox that keeps them
  (`OTO_OUTSIDE_PLUGINS=allowed`).
- **`oto sandbox status`** says whether the lock is in place and what would load. `up` and `status` give it
  as a sentence (`outside_plugins_summary`), which the `sandbox` skill reads back. `up` warns about a
  sandbox made from a kit without the lock.

Tried in a sandbox made from this kit, with Desktop's Claude Code 2.1.299 and its flags. After the lock:
- only the `@cynergis` and `@builtin` plugins loaded, with `plugin:oto:oto` and `mcp-gateway`;
- none of the computer's or the account's skills loaded;
- a forwarded `oto` gave way to the sandbox's own;
- a new sandbox set up by `oto sandbox up` started its first session, with Desktop's 9 plugins handed
  over, with only its own.

## 0.11.30 — 2026-10-17

**A sandbox for Claude Desktop in one command.** `oto sandbox up` starts Claude Code with OTO in a Docker
sandbox, from the published kit `ghcr.io/cynergis/oto-gcp:<engine version>`, ready to drive from Claude
Desktop's Code tab over SSH or from a terminal.

- **What it does, on the person's computer:**
  - checks that `sbx` is installed and signed in to Docker, and that a network policy is set
    (`--init-policy` sets one the person chose);
  - lets `sbx` run kits from OTO's registry (`kit.allowedSources`);
  - records the person's approval for the kit to use their Anthropic sign-in, with
    `--approve-anthropic` only;
  - creates the project and code folders and the sandbox, with the Google Cloud project as `PROJECT`
    (`--project-id`), and waits until OTO is ready inside;
  - sets up SSH, so `<name>.sbx` reaches the sandbox, and says the one step left in Claude Desktop.
- **The approval is why.** `sbx` asks whether a third-party kit may use the person's Anthropic sign-in only
  at a terminal. A sandbox created from a tool got no credential, and Claude Code in it asked to sign in
  at every message. `up` writes the same binding `sbx` writes, next to the ones already there, and only
  when the person said yes.
- **Again, it reuses.** A second `up` starts the sandbox if it is stopped and says when it differs from
  what was asked (other folders, another project); `--recreate` replaces it. It refuses a sandbox of
  that name not made from the kit. `--check` says what it would do and changes nothing; `--json` is for
  a skill.
- **`oto sandbox status`** says where everything stands, without starting anything.
- **The `sandbox` skill** (`/oto:sandbox`) runs both in plain words: it asks for the name, the folder,
  the Google Cloud project and the approvals, then says how to add the SSH connection in Claude Desktop.

The kit is released at 0.11.30 with the engine.

Tried on macOS with sbx 0.48.0: from nothing to OTO ready in about two minutes, most of it downloading the
kit; over SSH, Claude in the sandbox answered without asking to sign in. A second `up` takes two seconds.

## 0.11.29 — 2026-10-15

**A project runs in a Docker sandbox with its locked tools.** `oto lock --sandbox` writes `sbxenv.yaml`
and `.sandbox/setup.sh` from `oto.lock.json`, to commit with the project. In the project folder,
`sbx env run` ([Docker Sandboxes](https://docs.docker.com/ai/sandboxes/)) creates a small virtual
machine running Claude Code on the project folder, sets up the locked marketplace, plugins and engine
inside it, and opens Claude there.

- **What the setup adds to Docker's Claude image:**
  - LibreOffice and fonts, for older Office files at intake;
  - Chromium, for pdf-to-template;
  - a `uvx`, which the engine plugin's server and hook call;
  - git reaching GitHub over HTTPS, since the sandbox closes SSH.

  It ends with `oto lock --check`.
- **The setup runs inside the sandbox.** The one host command runs the script inside the new sandbox
  under the name it was created with.
- **The network and credentials stay under the person's control.** The network is closed except for
  what the person's sbx policy allows. An API key (`sbx secret set anthropic`) is added to requests on
  their way out, never inside the sandbox. A Claude subscription logs in once inside.
- **`oto lock` keeps both files in step with the lock** while they are its own. A hand-written
  `sbxenv.yaml` is left as it is. `oto status` names the sandbox.

Tried on macOS with sbx 0.48.0: a fresh sandbox sets itself up in under a minute; inside it, the lock
check matches, the plugins load, LibreOffice runs and Chromium renders a PDF. The Claude Code panel in
VS Code reaches it over SSH (`sbx setup ssh`).

## 0.11.28 — 2026-10-14

**A release moves its registry pin by itself.** Until now, after the engine or a listed plugin tagged a
version, someone moved the registry's pin by hand, so a fresh install kept getting the previous one
until they did.

- **`oto registry pin <plugin> --to <registry> --repo owner/name --plugin-ref v<version> --version <version>`**
  moves a listed plugin's pin on a branch of its own, `pin/<plugin>-v<version>`, and leaves the registry's
  main untouched: the pull request from that branch is the review. Nothing moves when the registry
  already pins that version or a newer one. `--changelog` quotes the version's section of the plugin's
  changelog in the pull request text, which `--body-file` writes.
- **The release workflow opens the pull request.** `tag-release.yml` calls the new reusable workflow
  `registry-pin.yml` when it pushes a new tag; a plugin's own release workflow calls the same one
  (`Cynergis/oto/.github/workflows/registry-pin.yml@main`). It needs the secret `OTO_REGISTRY_TOKEN`, a
  token that can push a branch to the registry and open a pull request there; without it the release
  still tags, and the run says how to move the pin by hand. It can also be run from the Actions tab.
- **Moving a pin keeps what it does not restate.** `oto registry plugin` given only a new ref and
  version kept nothing else of the entry: its description and category were lost. They stay now; a
  new `--repo` or `--url` replaces the old source.

## 0.11.27 — 2026-10-14

**The studio works opened from disk.** A built site (`oto build --target site`) opened by double-clicking
`build/site/index.html` landed on a folder listing: from disk, a browser does not open a folder's
`index.html` the way a server does. The home page, the navigation and every link between pages now
name `index.html` when the site is opened from disk, and `Studio.page(path)` gives a view the same
address for its own links. Served and published sites are unchanged.

## 0.11.26 — 2026-10-14

**Quotes that hold: every fact cites the sentence that says it, and the sentence is in its document.**
Asked for the source of a fact, an assistant found that its pointer said only "the section Rules":
when a capture gave no quote, the engine wrote the item's own name as the quote (and its id as the
place), so a loose citation looked complete, and nothing checked a quote against its document.

- **Nothing stands in for evidence.** A capture item's evidence is the document, and the place and
  the sentence when the capture gives them; never its id as a place nor its name as a quote.
- **`oto curate check` looks every new quote up in the document it cites,** when the project holds it
  (`build/documents/<doc>.md`): a quote that is not there is blocking ("its quote is not in the
  document it cites"), and so is `apply`. The comparison keeps the words and forgives what extraction
  and typing change: case, spacing, quote marks, dashes, a word broken at a line end, ligatures,
  Markdown emphasis, links and table bars, and the punctuation at a quote's ends; `…` joins parts of
  one passage that must appear in that order.
- **Gaps, one per document, not one per fact:** the facts that say where they come from but quote no
  sentence (a value from a table or a diagram has none), and the facts whose document the project
  does not hold, so their quotes cannot be checked. Only what a change brings is judged; a fact saved
  earlier is tightened by restating it with its exact quote, the new evidence beside the old.
- **The studio** says on each page, in one line, how many of its facts quote no sentence yet (counting
  facts saved before, whose quote was their own name).
- **A recorded action run** quotes the response's lines as its run document prints them.
- **capture-form** asks for each item's own sentence, word for word, and the interview note ingested
  before saving; **query-knowledge** gives the sentence when asked for a source, says plainly when a
  fact quotes none, and for a gap names what is missing and who can answer.

## 0.11.25 — 2026-10-14

**The studio: a product's pages, assembled from the views of the packs it uses.** The old site was one
fixed web app that read like an internal tool (raw ids, method jargon, a coverage meter, empty boxes, a
broken diagram) and could not show the parts a product's other packs bring. Now every pack's view
says where it belongs, and the studio assembles them ([docs/STUDIO.md](docs/STUDIO.md)):

- a view's `app.json` declares its `title` in plain words, its `place` (what the product is, what it
  deals with, how it is designed, where the data comes from, how people work with it, where it runs,
  how it is built, tools, technical), the classes it `shows`, the questions whose gaps are `open` on
  it, and whether it is the product's front page (`portal`); `oto` checks them;
- a kit every view includes (`_studio/`: one look, the navigation, `Studio.link` to open any thing on
  the page that shows it, and the "still open" box: each unanswered question's gaps in words, with
  who can answer), served by `oto serve --http` and written beside the views by `oto build --target
  site`, with the studio's data generated from the knowledge base;
- the home page opens the product's front page, or lists the pages by place when there is none; the
  explorer is listed last, as "Explore the knowledge graph", technical.

**The server's requests take turns on the store.** A page now asks for its own data and the studio's
together; the store has one connection, and two requests reading it at once failed. They are
serialised.


**The platform binding: where a product runs, and who decides.** The design (the architecture and
its patterns) says what the product does and never which platform runs it; nothing recorded where it
runs, so an implementing agent could not deploy or test end to end, and nothing stopped it. The
built-in `platform` ontology, on `software-architecture`, records it as facts:

- where it runs: the platform, its accounts (an AWS account, a GCP project, an Azure subscription),
  and each environment's purpose, region, console, logs and the repository that provisions it;
- what it runs on and is built with: the managed service under each component or store, each
  component's technologies at their versions;
- its secrets by name and where they are kept (the form has no field for a value), and the pipelines
  that deploy each part, to which environments;
- who decides: each choice the design needs is decided by a named person, or left to the builder
  within limits (the options allowed, the constraints and decisions that bound it); the builder's
  pick is a proposed decision a person accepts. Decisions carry their option, alternatives and
  consequences.

Its rules refuse a builder's pick outside its allowed options, a choice left to the builder with no
limits, and a decision accepted with nobody named. Three briefs stop an implementing agent by name on
any missing detail: `implement-component`, `deploy-component` and `test-end-to-end`. The sample binds
the payments platform to Google Cloud.

**A pack may declare itself a binding** (`binding`: `of`, `for`, `skill` in its manifest), like a
pattern: `oto pack check` validates it, `oto status` marks it `(binding of <ontology>)`, `oto pack list
--bindings` lists the ones on the machine and in the registries, and the registry index carries it.
The concierge says what a binding is for.


**A third pattern: the agent.** People increasingly give work to agents through plugins rather than
use screens, so a product's part can now be an agent, beside an application (`ddd`) and a data
pipeline (the `medallion` pack). The built-in `agent` ontology sits on `software-architecture` and
says what the agent does, never how a given platform runs it:

- the jobs people hand it, when each applies, what it produces, how far it may act alone, and the
  requirement it meets;
- its tools, whether each reads, changes or sends something, whether that can be undone, and what
  each reaches in the architecture (the agent's own reach is derived);
- what it draws on before it acts, where that is kept and how current it must be;
- its guardrails: what it must never do, what needs a named person's confirmation, what bounds it
  keeps, and the policy each upholds;
- how it talks (technical details only on request), where it hands work over, and the test
  conversations that prove each job.

Its rules refuse a design that contradicts itself: a job acting alone with a tool that needs a
confirmation, a job using a tool the agent must never use, a job acting alone with a tool that
changes or sends something while nothing protects it, a job marked ready with no requirement, no
test conversation, or a failing one. Twelve questions; the sample is a merchant assistant on the
payments platform the other samples describe. It composes with `ddd`: the shared relations widen.

## 0.11.22 — 2026-10-14

**Every conversation is in plain language, in a clear shape; technical details only when asked.**
The interview had become hard to follow: capture-form showed drafted items as "type, id, label,
fields, links" and reported "the graph answers N of M", and the concierge's first rule was to show
the engine's output. Ids, codes and exact output are needs of the record, not of the conversation.

- **capture-form** is rewritten as a conversation: open with what it will settle; one topic at a
  time, a few plain questions with choices; read back in plain sentences; "Save it and move on",
  "Dig deeper" or "See it from someone else's side"; save behind the scenes and say the outcome in a
  sentence; progress at the end of a topic, in what the questions ask, never their numbers; close
  with a recap. The form, the capture file, the commands and the checks are in "Behind the scenes",
  for the assistant only.
- **The concierge** reads the engine and tells it in plain words; it shows output only when asked,
  and hands over by saying who takes it from here, starting that skill when the person agrees.
- **Every engine skill** and every pack's generated start skill carry the same rule: plain, natural
  language, in the person's words; no question numbers, ids, class or field names, file names,
  commands or pasted output; technical details only when the person asks, never offered; the same
  clear shape every time. `query-knowledge` names the documents behind an answer by title and date,
  the ids only when asked.

## 0.11.21 — 2026-10-14

**A playbook pack says which journey it leads, and the concierge offers it.** A pack manifest may
declare `playbook`: `{"for": "a product, from an idea to a published knowledge base", "skill":
"atlas"}`. `oto pack check` refuses one whose skill the pack does not ship; the start skill says
it; `oto status` marks the project's playbook (`--json` carries it); the registry index records it;
`oto pack list --playbooks` lists them. The concierge offers a playbook when a person starts and one
fits, names the project's playbook when they want to go on with its journey, and never runs its
scenes: it orients, the playbook leads. It names none: a playbook is found, as a pattern is.

## 0.11.20 — 2026-10-14

**capture-form carries the confirmation menu.** At every confirmation the capture-form skill offers
**[A] Advanced elicitation · [P] Perspectives · [C] Continue & contribute**, and contributes a group
only on C. The studio's `elicit` skill existed to add that menu on top; every pack's interview now
has it, and `elicit` is gone from the packs.

## 0.11.19 — 2026-10-14

**Client terms match whole words, and are never printed.** The client-name gate of `oto pack check`
and an ontology's self-check matched a term anywhere in the text, so a term found inside an unrelated
word failed the `product` pack's site, and the finding named the term in a public CI log. Both
gates now match whole words, as `oto publishable` does, and a finding names the file only.

**The marketplaces Claude Code knows are registries too.** `oto pack list`, `--patterns`,
`oto ontology list` and `oto registry list --product-types` also read every Claude Code marketplace
whose copy holds `registry.json`: a machine that added the marketplace in Claude Code sees its packs,
patterns and product types without `oto registry add`, so Atlas finds them on a fresh machine.
`oto registry list` says which.

## 0.11.18 — 2026-10-14

**A retired pack published again goes on after its last release.** A pack removed from a
registry's index keeps its tags (`<name>--v<N>.0.0`); publishing a pack of that name again numbered
it from 1, so the push failed on the existing `--v1.0.0` tag, and Claude Code would have served a
cached copy of a version the old pack once had. `oto pack publish` now continues after the highest
release the registry ever tagged for the name (`software-architecture`, retired at 4, comes back at 5).

## 0.11.17 — 2026-10-14

**A pattern pack says what it is a pattern of.** A pack manifest may declare `pattern`:
`{"of": "software-architecture", "for": "a part designed with domain-driven design", "skill":
"model-domain"}`. `oto pack check` refuses a pattern whose skill the pack does not ship or whose
ontology does not extend `of`; the generated start skill says what the pack is a pattern of and
which skill models such a part; `oto status` marks the project's pattern packs (`--json` carries
the field); the registry index records it, and `oto pack list --patterns` lists only them. An
architecture skill finds the patterns a project composes from this, so adding a pattern no longer
means editing the skill that hands parts to it.

## 0.11.16 — 2026-10-13

**Any repository can refuse client names.** The engine's publishability scanner
(`tools/check_publishable.py`) is now part of the package: `oto publishable [<dir>] [--strict]`
scans what git tracks in a repository (every file outside one) for the client terms of
`OTO_DENY_TERMS` or a gitignored `.oto-denylist`, private repository references and credentials,
and names each finding by file and line, never by its text, since a CI log is public. `--strict`
fails when no term is configured. The registry, the ontology repositories, the packs and the plugins
can run the same scan in CI as the engine does; the engine's wrapper is unchanged.

## 0.11.15 — 2026-10-13

**A refined description is not a clash.** Merging ontologies (`--ontology a,b`, `--pack` with
`--ontology`) reported a class "described differently" whenever two parts disagreed, so every
product project with `flow` warned about `Document`: `product` says more about oto-core's
`Document` and `flow` keeps oto-core's words. When one side keeps the description of a base the
other refined, the merge now keeps the refined one, in either order, with its recorded reason, and
lists it under `class_refinements`; two different refinements of one base are still a clash. The
product composition (studio, `product-report`, `ddd`, `medallion`, `report-medallion`, `flow`) now
merges with none.

## 0.11.14 — 2026-10-13

**A project's views, side by side.** `oto init` installs the views of every pack the project
declares, not only the `--pack`'s, and `oto lock --use` installs those of the tool it declares: a
product project started from the studio with `medallion` gets `prd-site` and `lineage` both. A
project with views of its own is served and built as a home page that lists them, each view under
its own name: `oto serve --http` serves the home page at `/` and each view at `/<name>/` with its
data generated live (a view's relative `data.json` and `api/...` resolve under its prefix), and
`oto build --target site` writes `index.html`, `views.json` and a folder per view, the built-in
explorer among them. This is the view `all`, the default when the project has views; `--view
<name>` serves or builds one view at the root, as before. No view needs to be named by path any more.

## 0.11.13 — 2026-10-13

**The concierge knows the project's packs.** `oto status` gains a `packs` section: each plugin the
project uses (its `.claude/settings.json`, else the OTO plugins installed for it), with its version,
its skills and its views; a declared plugin not installed here says so, with its install line.
`oto status --json` gives each skill's command (`/<pack>:<skill>`) and what it does. The concierge
quotes the section when it orients and routes to a pack's skill first when the need is what the
pack does (model a part with DDD, design a pipeline, define a report); until now its hand-off table
knew only OTO's own skills.

## 0.11.12 — 2026-10-13

**A project declares the plugins it uses.** `oto init` from installed packs writes the project's
`.claude/settings.json` as Claude Code's project scope does (`enabledPlugins`,
`extraKnownMarketplaces`): the `--pack`, the pack of every ontology the project composes, named or
extended (the `ddd` pack for its skills although `ddd` ships with the engine; `report` under
`product-report`), and the engine plugin. Whoever opens the project is offered the same plugins, and
the lock records exactly those. `oto lock --use <name@marketplace>,...` declares a tool no ontology
brings, such as `pdf-to-template`. Other settings in the file are kept.

## 0.11.11 — 2026-10-13

**A project records the tools it is built with.** `oto.lock.json`, written by `oto init` and
`oto lock`, holds the engine's version (and commit when it runs from a checkout), each Claude Code
plugin the project uses with its marketplace, version and commit, each marketplace with its commit,
and the ontology record. The plugins are those the project's `.claude/settings.json` enables, else
the OTO plugins installed for it. `oto lock --check` and a new `tools` line in `oto status` say how a
machine differs; `oto lock --script` prints the script that rebuilds the tools on a fresh machine or
in a container: marketplaces cloned at their commits (Claude Code pins a branch or a tag, not a
commit), plugins installed from them, the engine from its commit or tag, named in `OTO_SOURCE`.
Every version that reaches main is now tagged `v<version>` (a workflow), so the engine of a lock can
be pinned. Auditable, repeatable, shareable: a project says what built it.

## 0.11.10 — 2026-10-13

**A pack can take the place of a plugin.** `oto pack publish` of a pack named like a plugin the
registry lists from its own repository (`oto registry plugin`; a studio that became a pack) replaces
that entry, so the marketplace lists one plugin under the name, and continues its version line: the
studio plugin at 2.0.0 becomes the pack at release 3, 3.0.0. Claude Code caches a plugin by version,
so a pack published at a version the old plugin once had would be served from the stale cached copy.
The publish says what it replaced. `data` is a known domain (a data pipeline's packs).

## 0.11.9 — 2026-10-13

**The shipped `product` ontology names no client.** Its release 1 changelog entry named the project
it was exported from; it now says it came from a client project. Nothing else changes: same release,
same vocabulary. Packs that embed `product` pick it up on `oto pack refresh`.

## 0.11.8 — 2026-10-13

**An installed pack's ontologies resolve by name.** `oto init --ontology <name>` (alone, merged, or
beside `--pack`) finds an ontology embedded in an installed pack: one under `~/.oto/packs`
(`OTO_PACKS`), or a pack Claude Code installed as a plugin, read from its list of installed plugins
(`CLAUDE_CONFIG_DIR`, default `~/.claude`). A machine that installed the `product-report`, `ddd` and
`flow` packs from a marketplace could not name them (`unknown ontology 'product-report'`): only
`~/.oto/ontologies` and the shipped set were searched. Packs come last, after yours and the shipped
ones, so a pack's copy of a base it extends never shadows them; when two packs carry the same
ontology, the higher release wins. An ontology found in a pack composes with the bases that pack
carries, the copies it was checked with, as `--pack` composes. The project records the pack and the
origin the pack recorded on embedding; `oto ontology list` marks these `(in a pack)`.

## 0.11.7 — 2026-10-13

**A rule can say what is absent, with conditions.** `{"not": [patterns]}` in a policy rule or a
question keeps a binding only when the patterns match nothing from it, so the absent node may carry
conditions and reach variables bound outside it: "a step that builds a silver entity and comes after
no gate-1 step". `not_edge` could only say there was no edge at all. The `not_in` operator is the
complement of `in` (an absent value is not outside the list, as SPARQL's `NOT IN`). Both render to
SPARQL (`FILTER NOT EXISTS`, `NOT IN`) and answer the same there; a derivation stays positive. Needed
by the medallion flow validations, which are rules over a declared flow.

## 0.11.6 — 2026-10-12

**A view can carry what a pattern adds.** `{"$optional": expr}` in the projection language marks a
part that may name classes and relations the vocabulary lacks. It is evaluated as is, so in a
project without them it is empty (a collection over a class the graph does not hold already is),
and validation (`oto pack check`, a template's self-check, serving) does not require what only an
optional part names; a class named outside one is still checked. A studio's site can show the DDD
pages of a product that adds `ddd`, or later a pipeline's layers, without its pack embedding them.

## 0.11.5 — 2026-10-12

**A pack and the ontologies a product adds.** `oto init --pack <pack> --ontology <name>,...`
merges the named ontologies with the pack's, as `--ontology a,b` merges, and installs the pack's
views. It was refused ("pass --ontology or --pack, not both"), so a pack could not be the core a
product extends: a studio pack embeds what every product shares, and each product adds its type
(`product-report`) and the flow. `merge` finds a name in the pack's embedded copy first, as
`composed` does; the project records the merge, with the pack on its first part and beside the
record, so `oto status` still says which pack it came from. The generated `start` skill mentions
the option. A pack's manifest may carry a `title`: a pack broader than its ontology (a studio over
`ddd`) is then shown under its own name, not the ontology's.

## 0.11.4 — 2026-10-12

**Skills that sound alike say which is which.** Descriptions only, no behaviour: `start` and
`build-knowledge-base` both answered "build me a knowledge base"; `start` is for choosing the way
in, `build-knowledge-base` for documents already in hand. `spec` writes a spec, an ADR or a brief
*from* the graph, and names capture-form and a studio's prd-build and architecture-build for
capturing one *into* it. `query-knowledge` lets a pack's own question skill (the report pack's
ask-reports) answer its domain first.

## 0.11.3 — 2026-10-12

**A pack's `start` hands over to the pack's own skills.** The generated starter skill told every
pack to run ontology-interview and hand over to build-knowledge-base and query-knowledge, so a pack
that ships `new-report` or `implement-step` sent people away from them. When a pack ships skills
beside `start`, step 2 now names each one (`<pack>:<skill>`, with the first clause of its
description) and step 3 lists the engine's skills for what they do not cover, capture-form among
them. A pack with no skills of its own is generated as before. `packs.frontmatter` reads a
SKILL.md's frontmatter for both the generator and the registry site. Takes effect when a pack is
regenerated: `oto pack refresh` or `oto pack publish`.

## 0.11.2 — 2026-10-12

**The capture form has one playbook.** The skill **capture-form** fills a project's
`capture.json` with a person: the questions group by group, the items drafted and confirmed,
every confirmed group through `oto curate start`, `propose`, `add`, `check` and `apply`. A pack's
or a studio's interview runs it and adds only what its domain needs; the studio's `capture` and
the report pack's `new-report` no longer carry their own copy. The loop now starts a candidate
first: both copies went straight to `oto curate add`, which refuses without one.

## 0.11.1 — 2026-10-09

**Plugins in their own repositories, in the marketplace.** A plugin that depends on `oto` (a
studio, a tool) resolves that dependency inside its own marketplace, so it must be listed beside
the engine: `oto registry plugin <name> --to <registry> --repo owner/name [--plugin-ref, --path,
--version, --description, --category]` lists it in the registry's index and marketplace
(`--remove` delists); named `oto`, it says where the engine comes from, a branch under test
included. **A checkout as the engine**: the plugin's MCP server and session hook run
`OTO_SOURCE` when it is set, the published engine otherwise.

## 0.11.0 — 2026-10-07

**The portfolio and the work** (stage 5, B6; decided and confirmed with Chiheb Dkhil). `portfolio`
@1 is the base of the chain: Product (its stage, domain, value stream, and where its knowledge
lives), Role, Team, Objective and Capability are declared once; `product` @9 sits on it,
`software-architecture` @10 on that, `ddd` unchanged. The executive's questions PF1–PF10: what we
build, what we pursue, what depends on what, which capability has no product, what has no owner,
where a product's store and packs are. `work` @1 on `software-architecture`: work items and
milestones that deliver requirements, features and components, assigned, scheduled, blocked; the
delivery lead's questions WK1–WK10, among them *which requirements slip if this component is
late*, and a derived `blocked` state.

**A row that says nothing is no answer.** A question's row whose selected values are all absent
is dropped, as SPARQL drops it; a question that selects only absent attributes is unanswered.

**Patterns are `sh:pattern`.** An attribute's `pattern` matches anywhere in the value; anchor it
for the whole. The importer reads SHACL decimals as numbers.

## 0.10.0 — 2026-10-07

**Value constraints** (stage 5, A4). An attribute may declare `pattern`, `min_value`, `max_value`
(a number, or an ISO date for a date) and `min_length`; the engine holds every value to them
(`oto curate check`, `oto ontology check`, the self-check on a sample), the Turtle carries them as
`sh:pattern`, `sh:minInclusive`, `sh:maxInclusive`, `sh:minLength`, the importer reads them back,
and pyshacl agrees with the engine. The report shapes the port could not hold can be held now.

**Product types** (A7). An ontology's manifest may declare `product_type` (`product-report`
declares `report`); the pack and the registry index carry it; `oto ontology list --product-types`
and `oto registry list --product-types` list the kinds of product a studio can start, so its first
question is read from the marketplace.

**The survey is cached** (A6): `kg_questions` runs every question once per loaded build.

## 0.9.3 — 2026-10-07

**A relation may be `derived`.** The rules state it and nobody captures it: the capture schema
leaves it out, so a tool never asks a person for what the engine concludes (the flow's
`dependsOn`, `requiresTest`). The capture schema also lists the pack's briefs. The self-check
asks an ontology's questions of its sample as a build would, with what the rules derive.

## 0.9.2 — 2026-10-07

**Briefs** (stage 3, A3). `briefs.json` beside the questions: a task type with its parameters,
the questions it requires and the ones it may also read. `oto query brief <task> NAME=<entity>`
and `kg_brief` are READY with every required question's facts or BLOCKED by name with the gaps;
without the parameters, the table for every candidate. Briefs compose by task, ride in the store
beside the questions, and are carried by an ontology (`carries`: `briefs`). Built for the port
of the flow ontology (report-ontology `oto/flow`), whose five task types give `kgctl brief`'s
verdicts for every step.

**The `no_gaps` gate.** A question whose answer may be empty but whose gaps always run; the
original's `gaps_only`. `may_continue` in the capture schema treats it as required.

## 0.9.1 — 2026-10-07

**A product starts from what its people say.** `oto init --empty` installs the vocabulary and
leaves the graph empty (no sample, no lexicon seed): the studio's Atlas starts every product this
way, so the pack's example never answers a question about the person's product. An empty graph
builds, and `oto query questions` says what is open. Found by scene 4 of the studio: the fund
report product's design was being checked against a payments platform.

**A question reports; a policy refuses.** `oto curate check` lists a required question the
candidate leaves unanswered under gaps, not blocking: facts arrive section by section, and the
question answered later must not refuse the fact that arrives first. A malformed capture item
(`fields` not an object) is refused by name.

## 0.9.0 — 2026-10-07

**The design level** (stage 3 of the programme, B4). Three shipped ontologies now form one chain:
`product` @8 ships with the engine (it was a user pack); `software-architecture` @9 sits on it,
dropping its own Requirement, Risk, Document and DecisionRecord for the product's and widening
`part_of`, `owned_by`, `about`, `threatens`, `mitigated_by` and `documented_in` to the estate
(`supports` is `enables`; SA17 asks which requirements nothing satisfies yet); `ddd` @1,
generalised out of `ddd-kyc`, sits on `software-architecture`: subdomains, bounded contexts and
their map, use cases, events, commands, reactions, read models, external systems, aggregates,
entities, value objects, business rules, domain services, with `deployed_as` from a context to a
component and `satisfies` from a use case to a requirement. The event-storming policy is
`Reaction`, because the product's `Policy` is a rule from outside. Decided with Chiheb Dkhil.

**A merge widens.** Two packs that widen the same relation of a shared base (`product-report` and
`ddd` both widen `part_of`) merge to the union of both signatures, as composition widens, and the
clash is reported; before, the first declaration won and the second pack's facts were refused.

**An export ships the graph.** `oto ontology export` and `publish` take the project's graph as the
sample (privacy-scanned, `--from-graph N` to cap it); `--invented` gives the synthetic one, which
answers the questions but respects no policy. A project started from a pack therefore exports
the pack's sample it still holds.

**Also.** A shipped ontology may carry a confirmation that names the person and the day; the
product's `risk-reaches-product` is typed to the feature and the product, so the estate's
`risk-reaches-system` derives its own hop; the `product` domain is known to the engine.

## 0.8.3 — 2026-10-07

**A capture names its scope.** A document's ids (`FR1`, `P1`) are unique in the document, not in
the graph: a capture may say which product it is about (`"scope": "fund-report"`) and its nodes
are `requirement.fund-report.fr1`, so two products' `FR1` stay apart. Found by the studio's scene
tests, whose fixture collided with the `product` pack's own sample.

**A project composed of several packs keeps their samples.** `oto init --ontology a,b` merges
the parts' samples by node id instead of inventing a synthetic one, and an ontology's self-check
runs its blocking policies on its sample: a pack whose sample breaks its own policy is refused.

## 0.8.2 — 2026-10-07

**The capture schema and proposals from a capture** (stage 2 of the programme). `oto ontology
capture` renders `capture.json` from a pack or a project: the questions by asker with their gates,
the classes with their fields, links and what they require, every field and link carrying `x-term`;
the build writes it beside `questions.yaml`. `oto curate propose --from <capture>` checks what a
tool captured against the schema and writes a proposal cited to the document, for the gates.

**Also.** `oto ontology import --from` carries the ontology's rules and questions; a forced export
is the next release of an ontology that exists; `oto-core` @5's sample carries its date as `as_of`.

## 0.8.1 — 2026-10-06

**The start skill** (`/oto:start`): a new project from whatever the person has (a specification,
a folder of documents, a domain expert, an ontology or pack that is close), to the first
confirmed questions and a hand-off to the interview. Found by starting the report ontology
from scratch: the path from a specification existed inside the interview skill and nobody
looking for it could find it. The concierge, `oto status` and the README point at it.


What porting the report ontology (github.com/Cynergis/report-ontology, `oto/report`) as an OTO
unit needed of the pattern language, so its 21 SPARQL questions could be written once in the
form the engine runs:

- `optional`: a list of patterns that extend a binding when they match and leave their variables
  unbound when they do not (a left join), in questions and policies; rendered as `OPTIONAL { }`,
  with the filters and the selection's reads of its variables placed inside the block.
- `{"exists": false}` on an attribute, and a `where` value that refers to a bound variable:
  `"$REPORT"` is its id, `"$FIELD.fieldId"` one of its attributes, `"fields.$FIELD.fieldId."`
  splices it into text; rendered as the bound variable, a triple, or `CONCAT`.
- `gaps` as a list of `{when, say}`: every cause that holds is reported.
- A declared attribute named like a node's own field (`label`) is the term even when a node
  carries no value for it: the engine no longer answers the node's label for a missing
  `rpt:label`, which the SPARQL rendering had exposed.



Questions that run, and shapes that gate. An ontology without competency questions, or whose
sample cannot answer them, is not usable from this release on; the shipped ontologies and the
registry packs are republished with theirs.

**Competency questions.** `questions.json` beside the vocabulary (`reason/questions.py`): each
question with who asks it, why, an `ask` in the pattern language of the rules (`when` + `select`,
`$NAME` parameters), a `gate` (`non_empty`, `empty`, `any`) and a `gaps` pattern that says why an
answer is empty. They ride in the store (SQLite schema 6, Neo4j `Question` nodes): `kg_questions`
surveys every question over the live graph, `kg_ask` runs one with its parameters bound (ids,
labels or aliases), `oto query questions` / `oto query ask` and `/api/questions` / `/api/ask` are
the other faces. Questions are carried by the ontology unit (`carries`), merged by id through
`extends`, installed by `oto init`, exported with `validated_by` blanked, locked, and diffed
(a changed `ask`, `params` or `gate` is breaking; added is additive; reworded is cosmetic).

**The contract.** Every class, relation and attribute must be cited by a question that runs, and
an ontology's sample must answer every question it must: the self-check refuses otherwise, `oto
ontology check` prints the terms no question cites and the questions the live graph cannot
answer (`--strict` fails), and `oto ontology accept` refuses an uncovered vocabulary.

**Shapes.** A relation's `min` and `max`, an attribute's `required`, a class's `requires`
(`reason/shapes.py`), evaluated over current facts with the hierarchy honoured; a policy rule may
say which question it protects (`answers`). `oto curate check` blocks a candidate that breaks a
shape or leaves a required question unanswered; `oto ontology check` prints the declared shapes
and the live graph's violations; the self-check holds the sample to them. Tightening is breaking
in the lock, loosening additive.

**Rendered for everyone else.** The ontology Turtle carries the shapes as SHACL (`sh:NodeShape`,
`sh:property` with counts; each policy rule as a `sh:SPARQLConstraint`), and `oto ontology import`
reads the property shapes back. `questions.yaml` holds every question rendered as SPARQL over
`graph.ttl` (`compile/sparql.py`); `ontology.md` lists the shapes and the questions. Tests with
rdflib and pyshacl (dev extras) require the SPARQL to return the engine's rows and the SHACL to
find the engine's violations.

**Also.** A declared attribute named like a node's own field (`status`) now wins in rules and
questions when the node carries it; the invented sample of an export exercises every pair of
domain and range, respects `max`, and gives twins their attributes; the skills (ontology-interview
Phase 4d, build-knowledge-base, curate, query-knowledge) know the questions and the gate.

## 0.7.0 — 2026-10-06

The semantic layer. OTO is still before its first announced release, so nothing here keeps an
older form alive: an ontology or pack written for 0.6 is rewritten, or it is not usable.

**Vocabulary form.** Every declaration is an object. A class is `{definition, label, alt_labels,
scope_note, example, subclass_of}`; a relation is `{domain, range, inverse, definition, label,
inverse_label, ..., subproperty_of}`; an attribute or temporal term is `{type, definition, ...}`.
The list and string forms are gone. `tools/convert_ontology.py` rewrites an old directory in
place and keeps the previous files beside it.

**Namespaces.** Each ontology declares `namespace` in its manifest (`https://cynergis.ai/ont/<name>#`
for the shipped ones); it is required. Terms an ontology inherits through `extends` keep the IRI
of the ontology that declared them; a project's own terms live under `<project namespace>ont/`,
its instances under `<project namespace>id/`. The `namespaces` section of a vocabulary records
what is claimed, inherited and renamed.

**RDF export is correct.** `rdf:type` instead of a custom predicate, per-ontology term IRIs,
`owl:unionOf` for union domains and ranges, typed literals, RDF collections for lists, `rdf:JSON`
for structured values, temporal terms as `owl:AnnotationProperty`, and `graph.ttl` beside
`graph.json` on every build. The Turtle and JSON-LD of an ontology carry `rdfs:label`,
`skos:prefLabel`, `skos:altLabel`, `skos:definition`, `rdfs:comment`, `skos:scopeNote`,
`skos:example`, `rdfs:subClassOf`, `rdfs:subPropertyOf` and inverse declarations.

**Labels and languages.** A term is read by its name unless a label is written; `languages`
declares what a vocabulary speaks and English is the default. Stores hold a `terms` table and an
`aliases` table with kind and language (SQLite schema 5; Neo4j `Term` nodes); cards, the explorer
and `kg_entity` show labels; `kg_define` and `oto query define` answer what a term means.

**Reasoning kept.** Rationale travels with the lock and the export as `meta:` annotations
(`https://cynergis.ai/ont/meta#`); a change of superclass or of a concept's place is a breaking
change the lock reports, and RECONFIRM asks a person again.

**Hierarchy.** `subclass_of` and `subproperty_of` are closed over by the vocabulary; stores,
rules (`covers`), action readiness, conformance and inherited attributes honour them, so a query
for a class answers with its subclasses.

**Concept schemes.** `schemes` declares controlled values as SKOS concepts with label, definition
and `broader`; an attribute typed `scheme:<name>` takes one of them, and the auto-claims ontology
uses them for claim and task states. `enum:` remains for a flat list.

**Import.** `oto ontology import` reads Turtle, RDF/XML, JSON-LD and N-Triples through rdflib
(the `rdf` extra), including unions, parents, inverse-only properties, list attributes and
concept-valued attributes; the report ontology is the acceptance fixture. Without rdflib, a
Turtle written by OTO still reads.

**Shipped ontologies and packs** are rewritten in this form and released again; the registry was
recreated from them.

**Skills.** `build-knowledge-base` ships the two references it pointed at: `draft-proposal.md`,
the rules a drafting subagent keeps, and `pipeline-run.md`, the unattended rules of the author
workflow.

## 0.6.1 — 2026-09-27

First published tree: the engine, its skills, its ontologies and its documentation.
