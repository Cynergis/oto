# From a product idea to a running, knowing agent: the implementation plan

Status: draft 2026-10-06, for Chiheb's review. Supersedes the first draft of this file. It covers
the OTO engine, the ontologies as packs, and version 2 of the PRD & Architecture Studio (ours),
and it is organised around the experience we are building, so that every stage is accepted by a
scene a person can live, not by a feature list.

## 1. The experience we are building

One persona, Atlas, carries a person from a product idea to a published knowledge base that
other people query. The person never types an `oto` command unless they want to; the graph is
the source of truth from the first confirmed gate; a reader who installed one pack asks one
question and gets a cited, dated answer without knowing the rest exists.

| # | Scene | The person sees | Under the hood |
|---|---|---|---|
| 1 | **Start** — "Atlas, lead this product." | two questions: which kind of product (the marketplace's product types), what do you have (nothing, notes, a brief); then Atlas has the project ready | `oto init`, `/plugin install` of the packs the type needs, `/oto:start` on the brief if there is one |
| 2 | **Specify** | the spec captured section by section, each section a question someone asks; after each gate, "the graph answers N of M questions a <type> product must answer; these are open" | capture against the pack's schema; every confirmed section becomes proposals through `curate check`; the gate is `kg_questions` |
| 3 | **Derive the domain** — "what must this product know?" | the domain questions, derived from the spec, confirmed by the person; then the vocabulary with its reasons, shapes and questions that run | `/oto:start` on the spec graph, then the interview from its Phase 2 |
| 4 | **Design and plan the flow** | the architecture and the build flow captured the same way; every component traces to a requirement | capture against the design and flow packs; the links are relations |
| 5 | **Build** | an implementing agent that asks before it acts and is BLOCKED by name when a fact is missing; what it builds, tests and deploys lands in the graph | `kg_brief`, actions, evidence |
| 6 | **Publish** — "publish" | the domain pack on the marketplace, the store published for readers, the site regenerated, the install line to send to a colleague | `oto ontology export`, `oto pack new/publish`, `oto publish --repo`, the site view |
| 7 | **Someone else uses it** | `/plugin install report@cynergis`; "which fields of the fund profile are still unmapped?" → the rows with their sources; a correction goes through the gates and comes back to the owning project as a pull request | the pack, `kg_ask`, the curate skill, `oto init --repo` workflows |

Scene 7 is the measure. Everything upstream is in its service.

## 2. The pieces

### 2.1 The levels of knowledge (each an ontology, each a pack)

```
                         portfolio
                              │
product ──satisfied by──► architecture & design ──built and run by──► flow ◄── work
    │                              │                                      │
    └────────── about ────────────►│   domain   ◄──────── produces ───────┘
```

| Pack | Level | Generic / per type | Source |
|---|---|---|---|
| `portfolio` | what we build, who owns it, objectives, releases, lineage between levels | generic | interview (the executive's questions) |
| `product` | what a product must do, for whom, under what rules, why | generic core | interview, pruned from today's `product` |
| `product-report` | what a *report* product's specification must say | per type, extends `product` | interview on the report application |
| `software-architecture`, `ddd` | how the solution is shaped | generic | exist; `ddd` generalised out of `ddd-kyc` |
| `flow`, `flow-report` | how building and running is executed | core + per type | port of `ontology.ttl` (`flow:`, `doctemplate:`, `bindings.ttl`) and the 17 flow questions |
| `work` | what is planned, by whom, blocked by what | generic | interview (the delivery lead's questions) |
| `report` | the domain of a report product | per product | from scratch via scene 3; compared with the port `report-ontology/oto/report` |
| `report-technical` | environments, deployments, credentials, tests | per type | exists |

### 2.2 What a user installs

| Block | Role |
|---|---|
| `oto` plugin | the engine: CLI (uvx), `kg_*` MCP server, 11 skills, session hook |
| the Cynergis marketplace (`oto-registry`) | ontologies at releases, packs as plugins |
| packs | an ontology unit + skills + views, depending on `oto` |
| `prd-architecture-studio` v2 | Atlas, the front door of the arc; depends on `oto`; no vocabulary of its own |
| a project repository (`oto init --repo`) | the team's graph changes by pull request |
| a production store | Neo4j; BigQuery Graph later |

## 3. Workstreams

### WS-A — OTO engine

| # | Deliverable | Purpose | Functioning | Tests | Size |
|---|---|---|---|---|---|
| A1 | **capture schema**: `oto ontology capture --name <pack>` → `capture.json`; also written by the build beside `questions.yaml` | the studio captures against a pack | sections = the pack's questions grouped by asker; items = the classes a question needs; fields = attributes (enum/scheme as choices, `required`); cross-links = relations with "must resolve"; `may_continue` = the question's gate; every field carries `x-term` | unit: the shipped packs render; round trip: a capture filled from the sample converts back to the sample's facts (A2) | S |
| A2 | **proposals from a capture**: `oto curate propose --from <data.json> --capture capture.json --doc <slug>` | the studio's output becomes facts through the gates | each item a node of its term with stable id from the capture id; each cross-link an edge; `source_doc`, `as_of`, evidence = the PRD section; refuses an unknown field | unit on the sample; `curate check` clean on the result; a second capture with a changed value yields a supersession | S |
| A3 | **briefs**: `briefs.json` beside the questions, `kg_brief <task> params`, `oto query brief` | an agent knows what it must know before a task, and is BLOCKED by name | a brief = task type + required and recommended question ids + params; runs them; status READY / BLOCKED with the unanswered required questions and their gaps; carried by packs, locked, diffed | unit; the port of `kgctl brief` on the flow pack gives the same verdicts as `competency_questions.yaml` | M |
| A4 | **value constraints**: `pattern`, `min_value`, `max_value`, `min_length` on an attribute | the report shapes the port could not hold | evaluated in `curate check` and the self-check; rendered as `sh:pattern`, `sh:minInclusive`, `sh:maxInclusive`, `sh:minLength`; read back by the importer | unit; pyshacl equivalence extended | S |
| A5 | **the site as a view**: the studio's site template mounted as an OTO view fed by the graph payload | the site shows what is believed, dated; `data.js` becomes a projection | `oto serve --view studio`; `oto build --target site`; the projection declared in the view's `app.json` | the explorer's view tests, on the studio template | M |
| A6 | **survey cache** | `kg_questions` on a large graph | survey cached per build sequence, invalidated on reload | unit | S |
| A7 | **marketplace from Atlas**: `oto registry types` lists product types (packs tagged `product-type`) | scene 1's first question | a pack manifest field `product_type`; `oto registry list --product-types` | unit | S |
| A8 | **BigQuery Graph store and target** (later; a target state once the graph is filled) | a third backend where the graph lives beside the data | `targets/bigquery.py` loads the rows into a dataset and `CREATE OR REPLACE PROPERTY GRAPH`; `BigQueryStore` answers the `Store` interface, GQL via `GRAPH_TABLE` for the graph-shaped reads; `bigquery` extra; ADC credentials | the store equivalence battery against a GCP project | L; last |

### WS-B — Ontologies and packs

| # | Deliverable | Method | Acceptance |
|---|---|---|---|
| B1 | `product` core | interview with Chiheb as the expert; `product` as the draft to prune | questions run on its sample; `oto ontology check` clean; the capture schema renders; published |
| B2 | `product-report` | interview on the report application; extends `product` | Atlas (v2) captures the report application's PRD against it; the graph answers its questions |
| B3 | `report` from scratch | scene 3 on the spec graph; the interview from Phase 2; the fixture's facts authored through proposals | the 21 questions answer on the fixture; a written comparison with the port: which questions, which classes differ, and whether each difference is OTO's discipline or its limit |
| B4 | `ddd` generalised; `software-architecture` settled | split the KYC-specific classes out of `ddd-kyc`; declare the links to `product` (`satisfies`, `decided_by`, `motivated_by`) | `architecture-build` captures against them; the user's `report-product-builder` composes on them unchanged |
| B5 | `flow`, `flow-report` | port of `ontology.ttl` and `competency_questions.yaml` by the same script pattern as `oto_port.py`; task types become briefs | the 17 flow questions and the briefs give `kgctl brief`'s verdicts on a flow instance (`FLOW_ROOT`) |
| B6 | `portfolio`, `work` | interview; Role and Team declared once in `portfolio`; every other pack extends it | a project composing four packs has one Role and one Team; "which requirements slip if this component is late" runs |
| B7 | the five user ontologies reviewed | the 139 drafted questions' gates and wording confirmed by Chiheb; shapes declared | `validated_by` filled where confirmed |

### WS-C — PRD & Architecture Studio v2 (ours)

| # | Deliverable | Purpose |
|---|---|---|
| C1 | **Atlas owns the arc**: menu = the seven scenes; product type chosen first; the concierge's knowledge of stations folded into Atlas as what it consults, not a second voice | one persona |
| C2 | **capture against a pack**: `prd-build`/`architecture-build` read `capture.json` (A1); the built-in section list and `data-schema.md` retired | one interview per product type, no skill edits |
| C3 | **contribute as you go**: on every [C], the section is written as proposals (A2) and goes through `curate check`; Atlas reports the gate as `kg_questions` | the graph is the source of truth from the first gate |
| C4 | **feature-flow reads the graph**: "validate idea vs goals" and "impact" are `kg_ask` and `kg_neighbors`, not re-reading `data.js` | gates with evidence |
| C5 | **the site is a view** (A5); `prd-site` keeps preview/publish | no drift |
| C6 | **"what must this product know?"** and **"publish"** as Atlas stages: `/oto:start` → interview; export → pack → publish → the install line | scenes 3 and 6 |
| C7 | `knowledge-graph` skill and the mesh ontology retired; plugin depends on `oto`; studio README and GETTING-STARTED rewritten around the arc | one vocabulary |
| C8 | **scene tests**: a scripted run of scenes 1–7 on the report application, in the studio's CI, against a pinned OTO release | the experience is tested, not assumed |

### WS-D — Publishing and readers

| # | Deliverable | Purpose |
|---|---|---|
| D1 | the registry on GitHub with the packs of B1–B6, `oto registry check` in its CI | scene 7's install line works |
| D2 | the report project as a repository (`oto init --repo`), with the author and checks workflows live | a correction from a reader comes back as a pull request |
| D3 | a published query store (`oto publish --repo`) and a static site for the report catalogue | readers without the documents |
| D4 | the plugin installed in Cowork, scene 7 run there | the second host |

## 4. Order, dependencies, and what each stage proves

```
Stage 1  B1 product core ── B2 product-report ── B3 report from scratch            proves: OTO produces an ontology
Stage 2  A1 capture ── A2 propose ── C2 ── C3 ── C1 ── C7 ── C8 (scenes 1-3)  proves: the studio captures against packs, contributes as it goes
Stage 3  B4 design ── B5 flow ── A3 briefs ── C4 (scenes 4-5)                 proves: the agent gets its brief from the graph; kgctl retires
Stage 4  A5 site view ── C5 ── C6 ── D1 ── D2 ── D3 (scenes 6-7)              proves: publish and read, end to end
Stage 5  B6 portfolio+work ── A4 ── A6 ── A7 ── B7 ── D4 Cowork              proves: the levels link; the second host
Later    A8 BigQuery Graph, once the graph is filled                          a target state, not on the path to the first release
```

Stage 1 is running now (the from-scratch test). Stage 2 cannot start before B2 exists to capture
against, but A1 and A2 can be built on the shipped packs in parallel with B1–B3. Stage 3's B4 and
B5 are independent of stage 2. Stage 4 needs C3 (facts in the graph) and B3 (the pack to publish).

Rough sizes, one person: stage 1 three to five sessions with Chiheb as the expert; stage 2 four
to six days; stage 3 five to eight days (the flow port is the bulk); stage 4 three to four days;
stage 5 three days. BigQuery (A8) is a week with a GCP project, when its time comes.

## 5. Testing, at three levels

| Level | What | Where |
|---|---|---|
| unit | every engine addition (A1–A8) with the suite's conventions: the shipped packs as fixtures, the SQLite/Neo4j battery, rdflib/pyshacl equivalence | OTO `tests/` |
| pack | self-check (every term cited, the sample answers what it must, shapes hold); `oto registry check`; a port's acceptance against the original (as `test_oto_port.py`) | each pack's repository and the registry's CI |
| scene | C8: scenes 1–7 scripted on the report application against a pinned OTO release, run in the studio's CI; scene 7 by hand in Claude Code and Cowork before each release | the studio's repository |

A stage is done when its scenes pass, its packs check clean, and the commits are signed.

## 6. Decisions taken (2026-10-06, with Chiheb)

1. The core keeps the name **`product`**; a product type extends it as `product-report`, `product-api`, …; the word "spec" names the stage, never a vocabulary.
2. **One project composes the packs** of one product: the links between levels are ordinary edges under one gate and one store; each pack keeps its namespace, so a level can be split into its own project later without renaming.
3. **Studio v2 in its own repository**, depending on a pinned OTO release; its scene tests pin what they test against.
4. **`data.js` stays as the intermediate projection** for the site until the site view (A5) lands, then retires with C5.
5. **BigQuery Graph is a target state** once the graph is filled; not on the path to the first release.

6. The studio had no source repository; version 2 starts from the installed copy, extracted to `~/Downloads/prd-architecture-studio` (git, first commit `e3386cd`, plugin version 0.7.0, 23 files).

## 7. Risks

- **The interview is the slow path.** Stages 1, 3 and 5 need the domain expert's time; the plan assumes Chiheb for `product`, `product-report`, `portfolio` and `work`. Mitigation: `/oto:start` from the existing material first, confirm rather than elicit.
- **Capture-as-you-go changes the studio's feel.** A gate that says "the graph cannot answer X" is stricter than a checklist; C3 must report it as what is open, never block the conversation.
- **Two tools, one experience** relies on the dependency mechanism working in both hosts; D4 checks Cowork early enough to change course.
- **The flow port** is the largest single piece; B5 follows the proven `oto_port.py` pattern and is bounded by the 17 questions.
