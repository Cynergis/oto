# OTO Roadmap

Oct 22, 2026 · @chiheb dkhil

## Overview

OTO's roadmap is 14 epics in six phases. Each phase builds on graphs and pipelines the previous one put in place, starting with deployment and store connectors, because nothing else ships without a place to publish to.

Three rules hold across every epic:

- **The repo is the source of truth.** Graphs are compiled from it on merge. Nobody edits a graph directly, and agents never push to one.
- **Only promoted facts enter the main graph.** That means merged work that passed its evals. Run state lives in a separate run graph.
- **Deterministic gates decide; agents remediate.** Hooks and server-side checks enforce policy. Prompts never do.

| Phase | Epics | Why this order |
| --- | --- | --- |
| 1. Foundation | B Deploy, K Connectors (interface, publish, Neo4j), L Plugin quick wins | A deploy needs a target store; L depends on nothing |
| 2. Packs v1 | M Work pack v1 (M1–M3, M5, M6), N Communication pack v1 (N1, N3, N4) | Dogfood on this roadmap; status set by command or git events, identity from git; internal use only |
| 3. Navigation and trust | A Federated graphs, F Observability and audit, G Decision records | Every later epic relies on stable IDs and provenance; F2 and F4 harden M and N (N6 lands here) |
| 4. Data | C Data semantic layer, K overlay connectors (BigQuery graph, Postgres) | Overlay connectors are how OTO reads client data in place |
| 5. Implementation | H Architecture graph, I Domain graphs, J Factory plugin | Share one architecture ontology; J1, J2 and J7 can start now with files; M4 automatic status lands as factory events exist |
| 6. Experience and control | D Ontology explorer UI, E IAM | D6 (diff view) can come forward to support B approvals; E3 replaces git identity in N2; N5 reminders |

&#91;embedded content: OTO roadmap · 6 phases, 14 epics\]

Each phase depends on the one above it; Epic L, J1, J2, J7 and the D6 diff view can start earlier, as noted.

## Epic B — OTO Deploy (GitOps publishing)

The agent never pushes a graph. Export commits the graph JSON to the repo, and a workflow publishes it to each environment under a deploy config.

| # | Item | Done when |
| --- | --- | --- |
| B1 | **Deploy config schema** next to the export: repo, target graph, connection (auth method and a secret reference, never the secret itself) | The config validates before any publish |
| B2 | **Git is the only path to a graph**: export commits graph JSON and metadata; the agent has no write credentials on the target | A direct push from the agent is impossible by design |
| B3 | **Publish workflow** (GitHub Actions), with or without a PR depending on config | Both modes work from the same repo |
| B4 | **Environments and promotion**: the same commit is promoted through each environment, approvers set per environment | The prod graph version traces to a commit and an approver |

```yaml
# oto.deploy.yaml
repo: cynergis/client-kg
graph: product-kg
connector: neo4j                 # Epic K
connection:
  endpoint: https://graph.dev.client.internal
  auth: workload-identity        # secret ref, no credentials in repo
publish:
  require_pr: true
environments:
  - name: dev
    approvers: []
  - name: test
    approvers: [kg-owners]
  - name: prod
    approvers: [kg-owners, data-governance]
promotion: same-commit           # no rebuild between environments
```

## Epic K — Graph store connectors

OTO's model stays store-neutral; connectors translate it into each store. They work in one of two modes:

- **Materialize**: OTO pushes nodes and edges into a store it owns. Neo4j (Cypher), Postgres with AGE (openCypher).
- **Overlay**: OTO defines a graph over tables that already exist, without copying data. BigQuery graph (GQL), Postgres SQL/PGQ. This is how the data semantic layer (Epic C) reads client data in place.

OTO doesn't define a universal query language. Each connector implements OTO's own tools (dependencies, architecture context, competency questions); native queries are read-only passthrough.

| # | Item | Done when |
| --- | --- | --- |
| K1 | **Connector interface and capability manifest** | OTO's core never calls a store directly |
| K2 | **Two modes**, declared in the manifest | One materialize and one overlay connector work end to end |
| K3 | **Schema compiler**: ontology to each store's DDL and constraints (unique IRI at minimum) | Re-applying the same ontology changes nothing |
| K4 | **Plan and publish**: dry-run diff on the PR, then idempotent upsert keyed by stable IRI (F4) | Epic B approvers review the plan before publish |
| K5 | **Query surface**: OTO tools per connector, plus read-only native passthrough | A3, H3 and J3 tools work the same against every store |
| K6 | **Auth and policy**: auth from the deploy config; E snapshot mapped to store roles where supported, else enforced by OTO's server (E5) | No store is reachable with broader rights than the policy grants |
| K7 | **Conformance kit**: fixture graph, round-trip, idempotency, IRI stability, manifest claims checked | A connector can't be listed until it passes |
| K8 | **Template and reference connectors**: scaffold, then Neo4j, BigQuery graph, Postgres | A new connector goes from scaffold to passing the kit without changes to OTO's core |

```yaml
# connectors/neo4j/oto-connector.yaml
name: neo4j
version: 0.1.0
modes: [materialize]
query_language: cypher
capabilities:
  named_graphs: true          # needed for the run graph (Epic J)
  schema_constraints: true
  transactions: true
  vector_index: true
auth: [basic, oidc]
conformance: passed@1.2.0
```

```python
class OtoConnector(Protocol):
    def connect(self, cfg: DeployTarget) -> Session: ...
    def apply_schema(self, ontology: Ontology) -> Plan: ...    # ontology to DDL/constraints
    def plan(self, graph: GraphDelta) -> Plan: ...             # dry run, attached to the PR
    def publish(self, plan: Plan) -> Result: ...               # idempotent upsert by IRI
    def tool(self, name: str, args: dict) -> Rows: ...         # OTO tools
    def native_read(self, query: str) -> Rows: ...             # read-only passthrough
```

## Epic A — Federated graphs

Graphs reference other graphs. Each one declares its dependencies in a baseline class, and the querying agent reads what each dependency holds and decides which to call, starting from one concierge root.

| # | Item | Done when |
| --- | --- | --- |
| A1 | **Baseline class** in the core ontology: every graph has one, declaring its dependencies on other graphs | Any graph can list its dependencies without custom modelling |
| A2 | **Dependency descriptor**: a node describing what data the target graph holds (subject, main classes, how to reach it) | The agent can pick a graph from the descriptor alone |
| A3 | **Agent dependency discovery**: a query tool returning the descriptors for a graph or node | The agent lists, chooses and queries a dependency in one flow |
| A4 | **Overlap handling**: lint near-duplicate descriptors at authoring; at runtime, send both candidates to the LLM | Lint warns on near-duplicates; ambiguous routing still resolves |
| A5 | **Concierge root graph**: the single entry point that routes to every other graph | Every query starts at the concierge |

```
Concierge
 ├─ Product KG   "products, features, owners"
 ├─ Policy KG    "controls, approvals"
 └─ Data KG      "tables, lineage, consumers"   ← output of Epic C
```

## Epic F — Observability vs auditability

OTel traces cover operations; an append-only, tamper-evident audit log covers accountability. The two link by `trace_id`, and only promoted facts enter the graph.

| # | Item | Done when |
| --- | --- | --- |
| F1 | **OTel tracing** for operations, with a redaction policy for prompts and tool payloads | No raw PII appears in spans |
| F2 | **Append-only audit log** keyed to graph node IDs: principal, agent, snapshot version, decision, `trace_id` | Any audit record links to its trace and its node |
| F3 | **Tamper evidence**: hash chain or WORM storage | Altering or deleting a record can be detected |
| F4 | **Stable node IRIs** across environments | A node keeps its ID when promoted from dev to prod |
| F5 | **Promotion rule**: only merged work that passed its evals enters the main graph, linked to spec, ADR, commit and eval | Every artifact in the graph traces back to a spec and an eval |

```
Hook ─▶ PDP (snapshot v42, sha256) ─▶ allow
 │
 ├─ OTel span       trace_id=7f3a…            (ops, short retention)
 └─ Audit record    node=oto:Draft/118, principal, agent,
                    snapshot v42, decision, trace_id   (append-only, chained)
                         │
          merged + eval passed?
                         ▼
 Graph:  Draft/118 ─derivedFrom▶ Spec/S-4, ADR-017 ─commit▶ a91c2e ─eval▶ EV-33
```

## Epic G — Decision records as graph nodes

Decisions become nodes attached to the transformation or column they govern, starting with the medallion layer, where most "why is this number different?" questions come from. ADRs stay markdown in the repo and compile into the graph.

| # | Item | Done when |
| --- | --- | --- |
| G1 | **ADR source format**: markdown in the repo, frontmatter compiled into the graph | ADRs go through the same PR flow as everything else |
| G2 | **Decision class**: status (proposed, accepted, superseded) and a `supersedes` edge | The graph shows the current decision and its history |
| G3 | **`governs` edges** to the transformation or column, not the table | A gold-layer column shows which decisions shaped it |
| G4 | **Medallion pilot**: bronze to silver to gold decisions, connected to C3 lineage | The "why" for a sample gold metric is answered from the graph alone |
| G5 | **Decisions in the ontology UI** (D5) | A reviewer opens any decision from the element it governs |

```
gold.fund_performance.return_1y
  ◀─governs─ ADR-017 "Returns net of fees, month-end NAV" (accepted)
                └─supersedes─ ADR-009 "Gross returns" (superseded)
  ◀─lineage─ silver.nav_monthly ◀─ bronze.custodian_feed
```

## Epic C — Data semantic layer

An agent reads a database schema and records what the data is about, what each column means, where the data comes from and who uses it. Lineage and usage are the priority, because the schema alone can't tell you either.

| # | Item | Done when |
| --- | --- | --- |
| C1 | **Schema introspection**: tables, columns, types, keys (via an overlay connector, Epic K) | The full schema is in the graph |
| C2 | **Meaning**: what each table is about and what each column means; agent drafts, a human confirms | Every column has a description marked draft or confirmed |
| C3 | **Lineage** *(priority)*: how data is captured and where it comes from, from ETL code and job configs | Each table links to its source and load process |
| C4 | **Usage** *(priority)*: consumers, and transactional vs analytical use, from query logs and app connections | Each table lists its consumers and type of use |
| C5 | **Published as a dependency graph** off the concierge (A5) | The agent reaches the data layer through the concierge |

```
Table: client_holdings
├─ About      → positions held per client account, daily snapshot
├─ Columns    → acct_id (FK accounts), fund_code, units, mkt_value_cad …
├─ Lineage    → loaded nightly from custodian feed → ETL job hold_load
│               (source of truth: custodian, not CRM)
└─ Usage      → Transactional: advisor portal reads by acct_id
                Analytical: AUM reporting, fact-sheet aggregation
```

## Epic H — Architecture graph for implementation

OTO holds a derived copy of the architecture: CALM stays the contract the gates check, and the graph is compiled from spec, ADRs, CALM, code map and evidence on every merge. Agents query it before they edit, so they avoid violations instead of having gates reject them.

| # | Item | Done when |
| --- | --- | --- |
| H1 | **Architecture ontology module** aligned with CALM (Node, Relationship, Control, Flow) plus Requirement, ADR, NFR, Evidence, CodeModule, Commit, ChangeProposal; CALM version pinned | A CALM model maps into the graph with nothing lost |
| H2 | **Compile on merge** through the Epic B pipeline; nobody edits the graph directly | The graph matches `main` after every merge |
| H3 | **`arch_context` MCP tool**: node, requirements, ADRs, NFR budgets and controls for a path or arch ID; used by the deriver and the G6 reviewer | Auto-remediation rate improves against the pilot baseline |
| H4 | **Trace and impact queries**: orphans, untraced modules, what a superseded ADR affects | An impact report is attached to every PR that changes an ADR |
| H5 | **Change proposals as nodes**, linked to the triggering gate failure and evidence | Each CP links to trigger, evidence and decision |
| H6 | **Measured NFRs as promoted facts** | Measured coverage comes straight from the graph |
| H7 | *(Later)* **Author in the graph, compile to CALM** | Only if H1 to H6 show the graph is the better place to edit |

```
arch_context("src/renderer/")
→ node: factsheet-renderer
  REQ-042: p95 ≤ 1000 ms on journey (budget 900 ms, measured 870 ms)
  ADR-007: read only via Fund Data API → no direct DB imports
  controls: none (no PII on this path)
```

## Epic I — Domain graphs for the software factory

The factory's business, component and execution graphs live in OTO. DDD classes sit on top of H1's shared Component and Contract classes, so a factory component and its CALM node are the same node.

| # | Item | Done when |
| --- | --- | --- |
| I1 | **DDD ontology module** (Event, Command, Policy, Aggregate, BoundedContext, ContextMap, Journey) on H1's Component and Contract | One node per component across factory and CALM |
| I2 | **Business graph**: event-storming output in the graph, validated by analysts in the Epic D UI | Analysts sign off on the graph itself |
| I3 | **Component spec as a projection**: spec JSON generated from the graph and schema-checked before a runner starts | Nobody edits a spec by hand |
| I4 | **Contracts as versioned nodes** with a frozen status; freeze and `write_scope` are Epic E policies | Contracts, write scopes and IAM share one enforcement path |
| I5 | **Planner**: contract dependencies produce the execution plan (parallel groups and order) | The invoice example's plan comes out with three parallel builds, unwritten |
| I6 | **Acceptance criteria from the graph**: policies and journeys generate `criteria.md` and test skeletons, reviewed by a human | Criteria trace to the policies and journeys they came from |
| I7 | **Spec deviations become change proposals** (H5), sibling impact found through contract edges (H4) | A deviation flags affected siblings before the build continues |
| I8 | **Run state in the run graph, results promoted**: one partition per run, kept in full; final verdict and commit promoted to the main graph | Each built component links to its spec, verdict and commit |

```
Query: InvoiceSubmitted v1 → v2. What must be rebuilt?
  producer   invoice-intake     ─emits─▶    InvoiceSubmitted   → rebuild
  consumer   approval-policy    ◀─trigger─  InvoiceSubmitted   → rebuild
  downstream payment-scheduler  ◀─InvoiceApproved (unchanged)  → no rebuild
```

## Epic J — Factory execution (Claude Code plugin)

The factory plugin runs the build: isolated runner and evaluator agents, hooks that enforce scope and the loop, and a run graph that records every iteration. J1, J2 and J7 can start now with files; graph integration follows I3 and I5.

| # | Item | Done when |
| --- | --- | --- |
| J1 | **Agent definitions**: runner, aggregator, and an evaluator that never receives the generator's reasoning | The invoice-approval example builds one component end to end |
| J2 | **Guard hooks**: PreToolUse enforces `write_scope` and read-only `contracts/` from the Epic E snapshot; Stop hook runs the loop with an iteration cap | Out-of-scope edits are blocked; the loop can't be skipped or run forever |
| J3 | **Spec-context skill**: the agent answers the context's competency questions from the domain graph and gets its spec from I3 | The runner starts from graph context, not loose files |
| J4 | **Graph-driven loop**: hooks read the plan (I5) and write status to the run graph instead of `verdict.json` and `state.json` | A full run can be replayed from the run graph |
| J5 | **Execution environment**: local Claude Code and GitHub Actions with the Claude Code Action, same hooks | Both paths run the same plan; Actions leaves a CI audit trail (F2) |
| J6 | **Factory metrics**: iterations to pass, escalation rate, evaluator-vs-test disagreement, cost per component | Metrics come from run-graph queries |
| J7 | **Plugin packaging**, released once a single context passes with the hook-driven loop | The plugin installs on a clean repo and runs the invoice example |

```
OTO
 ├─ main graph      promoted facts only: specs, contracts, final verdict, commit, eval
 └─ run graph       one partition per run: plan instance, node status, iterations, gap lists
                    (kept, never pruned, queryable: "which components needed >3 loops?")
        promotion ──▶ final verdict + commit copied to the main graph
```

## Epic D — Ontology explorer UI

The UI shows the ontology itself (classes, relationships, rules, lexicon, dependencies), not the instance graph's nodes and edges. Its diff view (D6) doubles as the review tool for Epic B approvals.

| # | Item | Done when |
| --- | --- | --- |
| D1 | **Class model view**: hierarchy, relationship types, properties with cardinality | A user browses from any class to its parents, children and relationships |
| D2 | **Rules view**: each rule with the classes and properties it applies to | Selecting a class shows every rule that touches it |
| D3 | **Lexicon view**: business terms, synonyms, EN and FR labels mapped to classes and properties | Searching a business term lands on its ontology element |
| D4 | **Dependencies view**: the Epic A federation map with descriptors | Routing topology is visible; near-duplicate descriptors are flagged |
| D5 | **Cross-artifact navigation**: from any element to its rules, terms, dependencies, decisions and repo files | Each element is one click from everything that references it |
| D6 | **Version and diff view** between commits or environments | A reviewer sees what a PR changes in the ontology before approving |

```
┌ Class: Fund ─────────────────────────────────┐
│ subClassOf   InvestmentProduct                │
│ relations    managedBy → PortfolioManager     │
│              holds → Security (1..*)          │
│ rules        R-12 MER must be ≤ 3%            │
│ lexicon      "fonds", "mutual fund", "pool"   │
│ depends on   Data KG › fund_master (lineage)  │
│ changed in   PR #41 (test → prod pending)     │
└───────────────────────────────────────────────┘
```

## Epic E — IAM: policy in the graph, hooks as enforcement

RBAC, ABAC and ReBAC policy is modelled in the graph and compiled to a signed Cedar or OPA snapshot that hooks and the graph server both check. OTO enforces agent and principal access at runtime; the generated system's IAM is a design-time output.

| # | Item | Done when |
| --- | --- | --- |
| E1 | **Policy model in the ontology**: roles, attributes (classification and PII from Epic C), relationships | Every policy rule is a graph node with its own ID |
| E2 | **Policy compiler**: graph to a versioned, signed Cedar or OPA bundle, built through the Epic B pipeline | Each snapshot has a version and a hash |
| E3 | **Agent identity and principal delegation**: effective permission = agent ∩ principal | A run never does more than both are allowed |
| E4 | **Hook enforcement**: every tool call checked against the run's snapshot | Denied calls are blocked and recorded in the audit log (F2) |
| E5 | **Server-side enforcement**: the graph/MCP server checks the same snapshot | A direct API call can't bypass a policy the hooks enforce |
| E6 | **Freshness**: snapshot TTL and re-check before sensitive actions | A revoked permission takes effect within the TTL |
| E7 | *(Later)* **Generated system's IAM**, design-time only: OTO models it and generates its policies and cloud IAM bindings | Generated policies ship with the system; OTO doesn't enforce them |

```
Agent      "fact-sheet-builder"   can: read Fund, write Draft
Principal  analyst@client         can: read Fund, read PII, approve Draft
Effective                         read Fund only (+ write Draft only if the principal also can)
```

## Epic L — Plugin quick wins

Two small changes to the OTO plugin that don't depend on any other epic.

| # | Item | Done when |
| --- | --- | --- |
| L1 | **Selected-text skill**: when the user refers to "the selected text" or "what I copied", read the clipboard and add it to the context | Asking about the selected text works without pasting it |
| L2 | **Rename Actions to Tools** in the ontology, plugin and UI, matching MCP terms; "Action" kept as a deprecated alias in the lexicon (D3) and existing IRIs mapped to the new ones | No "Action" left in the UI, and old references still resolve |

- Clipboard read per OS: `pbpaste` (macOS), `wl-paste` or `xclip` (Linux), `Get-Clipboard` (Windows). On Linux, `xclip -o -selection primary` returns the highlighted text itself, without copying.
- The clipboard can hold secrets. Cap its size and run it through the F1 redaction rules before it enters the context.
- A skill fires on the model's judgment. If it misses, a `UserPromptSubmit` hook matching "selected text" makes it deterministic.

## Epic M — Work pack (tasks and products)

A Jira-like pack in the graph: products decompose into tasks and down to factory components, and each task is Open, Blocked or Deployed to an environment. There is no "in progress"; done means deployed to prod. Status comes from events (factory runs, promotions), not from people updating tickets.

**v1 (phase 2):** M1–M3, M5 and M6, with status set by a command or a git event such as a merged PR. Used internally to track this roadmap. **Later:** M4 automatic status in phase 5, once factory events and B4 promotions exist.

```
        ┌──────── unblocked (reason resolved) ────────┐
        ▼                                             │
      Open ──── blocked (reason, waiting on) ────▶ Blocked
        │
        └─▶ Deployed: QA ──▶ Pre-prod ──▶ Prod  (= done)
             (set by Epic B promotions, never by hand)
```

| # | Item | Done when |
| --- | --- | --- |
| M1 | **Work ontology pack**: Product and Task, with decomposition edges down to factory components (I1) | Every factory component traces up to a task and a product |
| M2 | **States**: Open, Blocked, Deployed per environment (QA, pre-prod, prod) | Every task has exactly one state |
| M3 | **Blocked context**: reason, waiting on (person or task), since when, raised by whom | A task can't be set Blocked without a reason and a "waiting on" |
| M4 | **Event-driven status**: B4 promotions set the deployed environment; factory verdicts (I8) and runner-raised blocks (J) update the task | A prod promotion moves the task to Deployed (prod) without anyone editing it |
| M5 | **Board views** in the UI (D) and as plugin commands: open, blocked grouped by who it waits on, deployed per environment | "What's blocked, and on whom?" is one query |
| M6 | **Notify command**: from a blocked task, message the person it waits on (Epic N) | The message carries the task and its block reason |

```
Task T-214   Approval rules for blocked suppliers
  product     Invoice approval
  component   approval-policy
  state       Blocked since 2026-10-21
  reason      supplier-registry API v2 contract not published
  waiting on  Integration team (R. Tremblay)
  raised by   runner, factory run 2026-10-21-03
```

## Epic N — Communication pack

Messages are graph nodes tied to the item they're about, so a request about a blocked task arrives with the task's context. Everyone's OTO plugin connects to the communication graph; a SessionStart hook shows what's pending when a Claude Code session opens, and the user replies from there. The first use case is M6: notifying the person a blocked task waits on.

**v1 (phase 2):** N1, N3 and N4, with identity taken from git `user.email` and mapped to a Person node; due items show at session start. Internal use only, since anyone can send as anyone until identity and audit land. **Later:** N6 audit in phase 3 (F2), N2 on real identity (E3) and N5 scheduled reminders in phase 6.

| # | Item | Done when |
| --- | --- | --- |
| N1 | **Message ontology**: from, to, about (any graph item), body, sent, status (pending, read, replied, resolved), due | A message carries its subject's context without retyping it |
| N2 | **Plugin connection** to the communication graph under the user's identity (E3) | A user sees only messages addressed to them |
| N3 | **SessionStart hook**: injects pending and overdue messages into each new session | A new session opens with what's waiting on the user |
| N4 | **Reply and resolve from Claude Code**: a reply that unblocks moves the task back to Open, with the resolution recorded on M3 | Unblocking from a reply needs no second tool |
| N5 | **Scheduled items**: due dates and reminders; overdue items surface at session start; a scheduled job nudges people who aren't in a session | An unanswered blocker gets a reminder on its due date |
| N6 | **Audit**: every message and reply recorded in the F2 log | Who asked whom, when and about what is one query |

```
SessionStart → OTO communication graph (user: chiheb)
  2 pending
  ● from Integration team · re T-214 (Blocked) · due today
    Contract v2 is on the dev registry. Can you confirm the field names?
  ● from factory run 2026-10-22-01 · re T-219 · due Oct 27
    Acceptance criteria missing for policy P3. Decision needed.

  /oto reply <id> "…"     /oto resolve <id>
```

## Decisions and open questions

**Decided**

- The repo is canonical; graphs are compiled from it on merge and never edited directly.
- CALM stays the architecture contract; OTO holds a derived copy (H7 revisits this later).
- The factory machinery (Epic J) ships as a plugin on top of OTO; the graphs it uses belong to OTO (Epic I).
- Run state is kept in full in a separate run graph; only results are promoted to the main graph.
- No universal query language; connectors implement OTO's tools, plus read-only native passthrough.
- M and N ship as a thin v1 in phase 2 and track this roadmap; client use waits for E3 identity and F2 audit.
- The work pack keeps three states (Open, Blocked, Deployed). No "in progress", sprints or estimates.

**Open**

- [ ] Policy engine: Cedar or OPA? (OPA already used in the architecture-as-code gates)
- [ ] First Postgres connector: AGE, or SQL/PGQ if the target Postgres version supports it?
- [ ] Tamper evidence for the audit log: hash chain in OTO, or WORM storage at the client?
- [ ] Factory execution default: local Claude Code or GitHub Actions?
- [ ] Pilot context for H and I: one bounded context with a real SLO and one regulated data flow
- [ ] Who approves ontology changes in prod: one owner, or a board with an SLA?
- [ ] L1 in cloud or remote sessions: there's no local clipboard, so the skill only works where Claude Code runs on the user's machine
- [ ] N5 reminders: who runs the scheduled job (GitHub Actions cron or the OTO server)?
- [ ] People without the plugin: bridge messages to email or Teams, or plugin-only for now?
- [ ] Work pack migration: import existing Jira tickets, or start fresh from the factory's graph?
