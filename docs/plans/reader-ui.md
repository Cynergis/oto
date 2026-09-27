# Plan: web app templates fed by the graph, and the engine work under them

Status: phases 1 (the engine), 2 (the app contract) and 3 (the generic reader) delivered on 2026-09-19; on 2026-09-21 the graph explorer from the Ascent prototype was ported as the generic default app for every template, the reader staying as `--app reader`. Phase 4 was built as an architecture document for the software-architecture template and withdrawn on 2026-09-21 at the user's request; a generic view that applies to every template will replace it. Phases 5 (the pending lane, the preview and watch mode) and 6 (hardening) delivered on 2026-09-21. Proposed and revised
the same day. An example site (`references/prd-site 3`, a
self-contained PRD and Architecture site whose only per-project input is `data.js`) explained
the intent; it is an illustration, not the implementation reference. Real app templates will
differ from it in files, code and data shape, and the contract below is written so they can.
Nothing built yet.

A knowledge graph is read by people as well as queried by agents, and people read it through a
web app shaped like the document they know: a PRD, an architecture document, a claims file. The
app is not Oto's to design. **The user passes a web app template; Oto fills its data contract
from the graph**, live or as a static site, and the app renders. Oto ships one small generic
reader as the default and the fallback. Any static web app can be an app template: a hand-written
page, a framework build's output, one data file or several, JavaScript globals or JSON, or no
data file at all and calls to the engine's HTTP routes instead.

The order of work follows what depends on what: the engine first (a transport the app can call
and an export the app can be shipped with), then the app template contract and its projection
language, then the generic reader as the first app that uses the contract, then a first real app,
then the pending lane, then hardening for anything beyond one machine.

## What an app template is

A directory of static files that renders data it does not produce. The example is one shape of
it: three files that are the same for every site and one `data.js` that changes per project.
Another app might be a bundled single-page app reading `data/*.json`, or one that calls
`/api/entity/<id>` as the reader navigates and needs no data file. The contract has to say the
same thing for all of them: what the app is, what data it wants and in which shape, and how that
shape comes from the graph.

```
<app>/
  app.json            the contract: identity, entry file, the data files to produce and the
                      projection of each from the graph, or none if the app calls the engine
  ...                 the app's own files, whatever they are, untouched by Oto
  adapter.js          optional: a function that finishes the projection in the browser, for
                      shapes the projection language cannot say
```

An app template is selected by name or path: `oto serve --app prd-site`, `oto build --target
site --app ./my-app`. It lives in a knowledge template under `views/<app>/` (so a domain template
ships its reader, and `oto templates publish` carries it), in the user template directory, or
anywhere on disk. The generic reader ships inside the engine as `reader` and is used when no app
is named.

## Part 1. The engine: an HTTP transport and a static export

### The transport

`oto serve` speaks JSON-RPC over stdio for MCP hosts. It gains `--http [host:]port`, a second
front end on the same engine and the same store:

```
oto serve --project <root> --http 127.0.0.1:8765               # live, over the local build or Neo4j
oto serve --project <root> --http 8765 --app prd-site          # and the app at /
```

| Route | Answers |
|---|---|
| `POST /rpc` | the same JSON-RPC 2.0 messages as stdio, so a browser or a script uses the twelve tools unchanged |
| `GET /api/tools` | the tool list |
| `GET /api/entity/<id>`, `/api/search?q=`, `/api/type/<Class>`, ... | one GET per tool: the tool's text and, where the store has it, the rows as JSON |
| `GET /api/graph` | the whole graph as data: the vocabulary, every current node with its attributes, every edge, derived facts marked, findings, the lexicon, the ledger tail, the document inventory; the payload every projection starts from |
| `GET /api/status` | build sequence, schema, backend, freshness, the project's stations (inbox, processing, errors, archive counts) |
| `GET /api/changes?since=<build_seq>` | whether anything changed, cheaply; an app polls it |
| `GET /<data file>` | the app's data file, projected from the live store on each request (`data.js` for the example) |
| `GET /` and the app's files | the app template, served as is |

Stdlib only: `http.server` with a threaded server, one handler, JSON in and out, the engine's
existing `ensure_fresh` before each request so a rebuild is served on the next call. Binds to
`127.0.0.1` unless told otherwise; see hardening. The MCP stdio mode is untouched.

### The static export

A seventh build stage, `site`, opt-in like Neo4j (`"targets": [..., "site"]`, `"site": {"app":
"prd-site"}`, or `oto build --target site --app <name>`), writes `build/site/`: the app's files
copied, and its data file(s) generated from the graph. Opening `index.html` from disk, or hosting
the directory anywhere static (GitHub Pages, the query repository, a bucket), gives the app with
no server and no credentials. The example's own `deploy.yml` and `publish.sh` are the app's
business and are copied with it; `oto publish --site` additionally carries `build/site/` into
the query repository so a reader who syncs the store also gets the app.

### Tests

Every tool over `/rpc` equals the same tool over stdio, byte for byte; each GET route; the data
file over HTTP equals the export's; hot reload after a rebuild; the app served at `/`; a
bound-to-localhost default. The export in the build transaction: restored on failure, listed in
`generated_paths`, absent unless targeted.

## Part 2. The app template contract, and the projection language

`app.json`:

```json
{
  "name": "prd-site",
  "summary": "A PRD and an Architecture document, read as documents, from the graph.",
  "entry": "index.html",
  "engine": ">=0.1",
  "data": [
    {"file": "data.js", "format": "js-globals",
     "globals": {
       "__PRD__":  {"$include": "projections/prd.json"},
       "__ARCH__": {"$include": "projections/arch.json"}
     }}
  ],
  "adapter": "adapter.js",
  "requires": {"classes": ["System", "Component", "DecisionRecord", "Requirement", "Risk"],
               "relations": ["decided_by", "part_of", "depends_on"]}
}
```

`data` is a list, so an app may want several files. `format` is `js-globals` (`window.X = ...;`
per global, the example's shape), `json` (one object per file), or `js-module` (`export const X`
per global, for a bundled app). An app with no `data` entry gets nothing generated and calls the
HTTP routes itself; the site stage then refuses it, since a static site needs its data on disk,
unless the app also declares a `data` entry for that case. `requires` names what the app expects
the vocabulary to declare; `oto serve --app` and the site stage refuse a project whose vocabulary
lacks any of it, with the names, rather than render an empty page.

### The projection language

A projection turns the graph into the shape one global or file expects, whatever that shape is.
It is JSON, evaluated by the engine in Python, so it is inspectable, testable without a browser,
and the same live and static. Its primitives, with a decisions section as the worked case:

```json
{
  "context": {
    "problem":   {"$first": {"$nodes": "System", "$field": "summary"}},
    "systems":   {"$nodes": "System", "$map": {"id": "$id", "name": "$label", "tier": "$attr.tier"}}
  },
  "decisions": {
    "$nodes": "DecisionRecord", "$sort": "-attr.decided_on",
    "$map": {
      "id":        "$id",
      "title":     "$label",
      "status":    "$attr.status",
      "date":      "$attr.decided_on",
      "context":   "$summary",
      "decision":  "$attr.reason",
      "affects":   {"$in": "decided_by", "$select": "$id"},
      "documents": {"$out": "documented_in", "$select": "$label"},
      "evidence":  {"$evidence": true},
      "derived":   "$derived_by"
    }
  },
  "risk": {
    "$nodes": "Risk",
    "$map": {"id": "$id", "title": "$label", "reaches": {"$out": "threatens", "$select": "$label", "$derived": "mark"}}
  },
  "glossary": {"$lexicon": true, "$map": {"term": "$term", "meaning": "$note", "refs": "$targets"}}
}
```

| Primitive | Meaning |
|---|---|
| `$nodes: Class` with `$where`, `$sort`, `$limit` | the current nodes of a class (superseded excluded unless `$history: true`) |
| `$map` | the object built per node; a string starting with `$` is a field path: `$id`, `$label`, `$summary`, `$status`, `$as_of`, `$valid_from`, `$attr.<name>`, `$sources`, `$tags` |
| `$out: rel`, `$in: rel` | the entities across a relation, with `$select` (a field path, or a nested `$map`), `$derived` (`include`, `exclude`, `mark`) |
| `$evidence` | the node's evidence locators as `[{doc, where, quote}]` |
| `$first`, `$count`, `$group: field` | reductions |
| `$lexicon`, `$documents`, `$findings`, `$ledger`, `$pending` | the non-graph parts of the payload |
| `$const`, `$concat`, `$format: "..."` | literals and simple text |
| `$include: path` | a projection kept in its own file |

Anything the language cannot say goes to `adapter.js`: a function `window.__OTO_ADAPT__ =
(data, graph) => data` that receives the projected globals and the full `/api/graph` payload and
returns the globals to install. It runs in the browser before the app's scripts, in both modes.
The language is meant to cover most apps; the adapter exists so no app is blocked by it.

A knowledge template's self-check validates every app under `views/`: the manifest, the
projections against the vocabulary (a class, relation or attribute a projection names must
exist), `requires` satisfied by the template itself. `oto templates show` lists the apps.

### Tests

Each primitive on a fixture graph. Two fixture apps of deliberately different shapes, kept
under `tests/fixtures/apps/`: one in the example's shape (three fixed files, one `data.js` of
globals) and one a single page reading `data/*.json` files, each with an expected output checked
in and compared byte for byte; a third fixture with no data file that only calls the HTTP routes.
Refusal messages for a missing class, relation or attribute; the adapter hook invoked in the
smoke test.

## Part 3. The generic reader, as the first app on the contract

One small app, `reader`, shipped inside the engine under `oto/ui/reader/`: plain HTML, CSS and
JavaScript with no build toolchain and no external network call, so the stdlib serves it and a
template can carry a copy. Its `app.json` projects the payload almost unchanged. Pages: home as
the map (counts, lead classes, most connected, recent changes, the corpus frontier), a section
per class, the entity card with provenance, relations, derived chains, history, sources and
evidence quotes, the document page, search over entities and passages, findings and rules, the
ledger. Stable URLs, phone width, both themes. It is the fallback every project gets, and the
proof that the contract carries what a reader needs.

## Part 4. A first real app template

Once the contract exists, the first real app is written against it, and it is allowed to change
phases 1 and 2 where the contract falls short; the generic reader is not. Which app comes first
is your call and does not need deciding now: the example site, adapted; a new architecture
document reader built for the software-architecture template; or a spec reader for a product
template. Whichever it is, it lives under `views/<app>/` of its knowledge template so `oto
templates publish` carries it and `oto init` installs it, and its data projection is the record
of how that document reads from the graph. Sections the graph does not hold stay empty and are
shown as such; every statement the app makes links to its entity and evidence, which is the
reason to feed an app from a graph at all.

## Part 5. The pending lane

Knowledge is visible the moment it is captured, labelled by station:

| Station | Where it lives | In the payload |
|---|---|---|
| inbox | `inbox/` | a count |
| processing | `processing/`, `build/documents/` | documents marked "extracted, not yet in the graph" |
| proposal | `proposals/<slug>.json` | entities and edges marked "proposed", with the dry-run verdicts |
| candidate | `graph.candidate.json` | the same, marked "in review", with the check report's counts |
| pull request | repository mode | the same, with the PR's link and state |
| live | the store | the believed facts |

The engine gains `kg_pending` (a thirteenth tool, on both stores, in the equivalence battery),
`/api/graph` and the export carry a `pending` section, and the projection language's `$pending`
exposes it, so an app template decides how to show it; the generic reader shows a pending fact
beside the live one it would supersede, badged, never mixed. The change signal is
`/api/changes`, polled every few seconds.

## Part 6. Hardening, for anything beyond one machine

- **Bind and token.** `--http` binds to localhost by default; `--http 0.0.0.0:8765` requires
  `OTO_SERVE_TOKEN`, sent as a bearer header, or the server refuses to start. Never in a file.
- **Read-only, always.** No route writes. Neo4j credentials stay in the server process.
- **CORS off** by default; `--cors <origin>` for a hosted app calling a separate server.
- **Publishing.** `oto publish --site` into the query repository; the repository-mode deploy
  workflow gets the step, off by default; an app's own Pages workflow, like the example's, keeps
  working because the app's files are copied as they are.

As delivered (2026-09-21): `OTO_SERVE_TOKEN` from the environment only; `check_bind` refuses any
host outside the loopback set without it; with a token every route answers 401 without a bearer
header, a browser hands the token over once as `/?oto_token=<token>` and gets an HttpOnly,
SameSite=Strict cookie and a redirect to the plain path; constant-time comparison; the token is
replaced in the log. `--cors <origin>` (repeatable, `*` for any) adds the allow-origin header for
a matching origin and answers the preflight with the bearer header allowed; without it a preflight
is refused. `X-Content-Type-Options: nosniff` on every answer. The deploy workflow builds the site
with the app the repository variable `OTO_SITE_APP` names and publishes it beside the store.

## Delivery

| Phase | Delivers | Size |
|---|---|---|
| 1. Engine | `--http` with `/rpc`, the GET routes, `/api/graph`, `/api/status`, `/api/changes`; the `site` stage; `oto publish --site`; tests | 3 days |
| 2. Contract | `app.json`, the projection language and its evaluator, `requires`, the data routes and files, validation in the template self-check, tests on every primitive | 3 days |
| 3. Reader | the generic reader on the contract, static and live, tests on the data functions and an HTML smoke test | 3 days |
| 4. First app | a real app template under `views/<app>/` of a knowledge template, its projections, the adapter if needed, an expected data file under test; the app chosen then | 3 to 5 days |
| 5. Pending | `kg_pending` on both stores, the `pending` section, `$pending`, the lane in the reader, the change signal | 2 days |
| 6. Hardening | token, bind rules, CORS, the workflow step, docs | delivered |

Each phase ends green on the suite and the gates, committed and pushed, usable on its own.

## Decisions to take before phase 1

1. **The projection is declarative JSON evaluated by the engine**, with `adapter.js` as the
   escape hatch. The alternative, an adapter only, would make every app carry JavaScript that
   Oto cannot check against the vocabulary; the language keeps the graph as the data and the
   mapping inspectable.
2. **The contract is tested against apps of different shapes**, not against one example, so
   it does not quietly become that example's shape. The first real app (phase 4) is allowed to
   change phases 1 and 2; the generic reader is not.
3. **The example stays out of the repository.** It explained the intent; the fixtures in the
   tests are the reference shapes, and they carry no client content.
4. **Passages in the static export by default**, with a config switch to drop them; **polling,
   not push**, for the change signal.
