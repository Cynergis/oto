# The core, end to end: an ontology created, deployed, queried, and made into a pack

This is the test drive of the engine alone. No pack is installed and no vocabulary but `oto-core` is in
reach: everything the test uses, it creates. One vocabulary is written by hand, facts enter through
ingest and the four gates, the graph is built, queried and served, deployed through three environments,
exported as an ontology, made into a pack, published to a registry, installed from it, and a second
project starts from the pack. Every step says what passes. It takes about ten minutes by hand, a minute
as a script.

[`tools/e2e_core.sh`](../tools/e2e_core.sh) is the same test as a script, stopping at the first miss, and
`tests/test_e2e_core.py` runs it in the engine's suite, so what this document promises is what the suite
holds. The wider guide, [E2E-TESTING.md](E2E-TESTING.md), covers the packs, Neo4j, repository mode and
the rest; this one is what remains when every pack is taken away ([ADR-0011](adr/0011-a-domain-vocabulary-is-a-pack-of-the-registry.md)).

## Where to run it

On any machine with the engine (`oto version` says 0.15.1 or later), or inside a sandbox made from the
kit, where the engine is already there. Keep the test away from your own ontologies, packs and
registries by pointing the engine at empty folders for the duration:

```bash
export WORK=$(mktemp -d)                                  # everything below lands here
mkdir -p "$WORK/user" "$WORK/packs" "$WORK/claude"
export OTO_ONTOLOGIES="$WORK/user" OTO_PACKS="$WORK/packs" CLAUDE_CONFIG_DIR="$WORK/claude" OTO_REGISTRIES="$WORK/registries.json"
export P="$WORK/garage"                                   # the knowledge project
oto version                                               # oto 0.15.1
oto ontology list                                         # oto-core, and nothing else: the engine ships its own vocabulary and no other
```

Pass when `oto ontology list` shows one vocabulary, `oto-core`, the engine's own.

## 1. A project, and a vocabulary written by hand

A vocabulary is three files, not one: the terms (`ontology.config.json`), why each exists and who
confirmed it (`ontology.rationale.json`), and what the graph must answer (`questions.json`). The
ontology-interview skill writes all three in conversation; here they are written by hand so every rule
is seen. The domain is a bus garage: buses, the garage each is based at, the mechanic who keeps it
on the road.

```bash
oto init --name "Northwind Garage" --slug garage --project "$P"    # on oto-core alone: "declare your classes and properties in ontology.config.json"
mkdir -p "$P/proposals"
```

Add to `ontology.config.json` (keep what `oto init` wrote: the temporal fields, `Document`, `Tool`, `Graph`):

```json
"classes": { "Bus": {"definition": "A vehicle of the fleet, identified by its plate."},
             "Garage": {"definition": "A depot where buses are parked and maintained."},
             "Mechanic": {"definition": "A person who maintains buses at a garage."} },
"properties": { "parked_at": {"domain": "Bus", "range": "Garage", "inverse": "parks", "definition": "Where this bus is based."},
                "maintained_by": {"domain": "Bus", "range": "Mechanic", "inverse": "maintains", "definition": "Who keeps this bus on the road."},
                "works_at": {"domain": "Mechanic", "range": "Garage", "inverse": "employs", "definition": "The garage a mechanic works at."} },
"attributes": { "Bus": {"plate": {"type": "string", "required": true, "definition": "The registration plate."},
                        "capacity": {"type": "integer", "definition": "Seats."}} }
```

Write `ontology.rationale.json` with an entry per class and per relation, each with a `question`, a
`why` of a sentence or two, `alternatives` and `validated_by` (a named person; the script uses "Test
Driver"). Write `questions.json` with two questions:

```json
{"questions": {
  "GQ1": {"who": "a dispatcher", "question": "Which buses are parked at $GARAGE, with their plate and capacity?", "why": "Dispatch starts from what is at the depot.",
          "validated_by": "Test Driver", "params": {"GARAGE": {"type": "Garage"}},
          "ask": {"when": [{"node": "b", "type": "Bus"}, {"edge": ["b", "parked_at", "$GARAGE"]}], "select": ["b.label", "b.plate", "b.capacity"]},
          "gate": "any", "gaps": {"when": [{"node": "$GARAGE", "type": "Garage"}], "say": "no bus is parked at this garage"}},
  "GQ2": {"who": "a maintenance planner", "question": "Who maintains $BUS, and at which garage do they work?", "why": "One accountable mechanic per bus.",
          "validated_by": "Test Driver", "params": {"BUS": {"type": "Bus"}},
          "ask": {"when": [{"edge": ["$BUS", "maintained_by", "m"]}, {"node": "m", "type": "Mechanic"}, {"edge": ["m", "works_at", "g"]}, {"node": "g", "type": "Garage"}],
                  "select": ["m.label", "g.label"]},
          "gate": "any", "gaps": {"when": [{"node": "$BUS", "type": "Bus"}], "say": "nobody is recorded as maintaining this bus"}}}}
```

The exact files are in the script. Then:

```bash
oto ontology check --project "$P" --strict        # shapes: every node satisfies them; questions: 2 declared; no term uncited
oto ontology rationale --project "$P" --strict    # recorded reasoning: 3 of 3 class(es), 3 relation(s); confirmed by a named person
oto ontology accept --project "$P"                # accepted vocabulary version 1 (3 classes, 3 relations, 0 rules, 2 questions)
```

Pass when all three exit 0. Things to notice: a question cites a class through a node type or a
parameter, a relation through an edge, an attribute through a `select`; a term no question cites is
refused by `accept` ("no question cites Bus.capacity"), and a relation with no question or a reason
under about twenty characters is refused later by `export`. Leave `validated_by` empty and `rationale
--strict` says the model is a draft.

## 2. A document into the corpus

```bash
cat > "$P/inbox/fleet-notes.md" <<'EOF'
# Fleet notes, November 2026

Bus NW-101 (plate NW-101, 48 seats) is parked at the North garage and is maintained by Ada Okafor.
Bus NW-205 (plate NW-205, 32 seats) is parked at the South garage and is maintained by Ben Ruiz.
Ada Okafor works at the North garage. Ben Ruiz works at the South garage.
EOF
oto ingest run --project "$P"                     # run <id>: claimed 1 file(s) into processing/; extracted 1
```

Pass when the run id is printed and `build/documents/fleet-notes.md` exists. Keep the run id: the
file waits in `processing/` until the graph holds its facts.

## 3. A proposal citing the document, through the four gates

Write `proposals/fleet.json`: six nodes (two garages, two mechanics, two buses with `plate` and
`capacity`), each with an `evidence` entry quoting the document, and six edges (`from`, `rel`, `to`).
The script has the file. Then:

```bash
oto curate start --project "$P"                                              # candidate created
oto curate add --from "$P/proposals/fleet.json" --project "$P"               # fleet.json: +6 node(s), +6 edge(s)
oto curate check --project "$P"                                              # the diff, then: ready to apply
oto curate apply --by "Test Driver" --note "the fleet notes" --project "$P"  # applied; the ledger has the entry
```

Pass when `check` says ready to apply and `apply` records who and why. Try a node whose quote is not
in the document, or a bus with no `plate`: `check` refuses and names the finding, and the live graph is
untouched until `apply`.

## 4. Built, the run completed, queried three ways

```bash
oto build --project "$P"                                              # knowledge layer written to graph and entities
oto ingest complete --run <id> --project "$P"                         # the id from step 2, without .json: 1 file(s) archived
oto query --project "$P" entity bus.nw-101                            # maintained by → Ada Okafor; parked at → North garage; the evidence quote
oto query --project "$P" ask GQ1 GARAGE=garage.north                  # status: answered; b.label=Bus NW-101  b.plate=NW-101  b.capacity=48
oto query --project "$P" ask GQ2 BUS=bus.nw-205                       # status: answered; m.label=Ben Ruiz  g.label=South garage
oto query --project "$P" neighbors "Ada Okafor"                       # matched by label; the bus she maintains, the garage she works at
oto ontology check --project "$P"                                     # questions: 2 declared; the live graph answers 2 as required
oto status --project "$P"                                             # vocabulary accepted; graph 6 node(s), 6 edge(s); build up to date; processing 0
```

Pass when both questions answer with the rows above and every answer carries its source and quote.

## 5. Served: the same answers over HTTP

```bash
oto serve --project "$P" --http 8891 &
curl 'http://127.0.0.1:8891/api/entity?term=bus.nw-101'               # the bus as text, with status, dates and evidence
curl 'http://127.0.0.1:8891/api/ask?id=GQ1&GARAGE=garage.north'       # "status: answered" with the same row
curl 'http://127.0.0.1:8891/api/tools'                                # the kg_* tools and their routes; no pack route, since no pack is composed
kill %1
```

Pass when the entity and the question answer over HTTP as they did on the command line. Open
`http://127.0.0.1:8891/` in a browser for the workbench while the server runs.

## 6. Deployed: a store repository, dev, test, prod

The graph is what is deployed: a built store, published into a query repository, promoted by commit
through the environments the deploy config names, never rebuilt on the way.

```bash
git init -q --bare "$WORK/store.git"
oto deploy init --project "$P" --repo garage --to "$WORK/store.git"       # oto.deploy.json: dev -> test -> prod; test and prod name approvers
oto deploy check --project "$P"
( cd "$P" && git init -q -b main . && git add -A && git commit -q -m "the garage graph" )
COMMIT=$(git -C "$P" rev-parse --short HEAD)
oto publish --project "$P" --to dev --source "garage@$COMMIT" --by "Test Driver"     # published build_seq ... to environment dev
oto publish --project "$P" --to test --promote "$COMMIT" --by "kg-owners"           # promoted dev -> test: garage@<commit>
oto publish --project "$P" --to prod --promote "$COMMIT"                            # refused: prod needs an approver
oto publish --project "$P" --to prod --promote "$COMMIT" --by "kg-owners, data-governance"   # promoted test -> prod
oto deploy status --project "$P"                                                     # each environment: the build, its commit, who approved
oto sync --repo "$WORK/store.git" --branch test --dest "$WORK/store-test" && oto status --project "$WORK/store-test"   # a published query store, not a knowledge project
```

Pass when the three environments hold the same build from the same commit, prod refused without an
approver, and the synced store says which environment it is and who approved it. Things to notice:
`--source` names the repository and commit the build came from, which CI passes and you pass by
hand; a store published without it says "from ?" and cannot be promoted, since promotion moves a
commit.

## 7. The vocabulary exported as an ontology, made into a pack

```bash
oto ontology export --project "$P" --name garage-fleet --summary "A bus garage: buses, where they are based, who maintains them"   # wrote ontology 'garage-fleet'; self-check clean; the sample is taken from the graph
oto ontology list                                                              # oto-core, and garage-fleet @1 (yours)
oto pack new garage --ontology garage-fleet --to "$WORK/packs-work" --maintainer "Test Driver"   # embeds garage-fleet@1; a start skill and a README; check clean
oto pack check "$WORK/packs-work/garage"                                       # pack garage @1: ontology garage-fleet@1, 1 skill(s), 0 view(s); check clean
```

Pass when the export is self-check clean and the pack checks clean. Things to notice: `export`
refuses a vocabulary whose rationale is incomplete, and the exported sample is the project's own
graph, with `validated_by` emptied, since confirmation does not carry to a new domain.

## 8. The pack published to a registry, installed, and a second project started from it

```bash
git init -q --bare "$WORK/registry.git"
oto pack publish --from "$WORK/packs-work/garage" --to "$WORK/registry.git" --registry-name test --note "first cut"   # the registry was created: index, marketplace, README and its check workflow; tagged garage--v1.0.0
oto registry add "$WORK/registry.git"                                          # registry test: 0 ontologies, 1 pack
oto pack add garage                                                            # added pack garage @1; embeds garage-fleet@1; from registry test
oto init --name "Second garage" --slug garage2 --pack garage --project "$WORK/garage2"   # the pack's ontology, with where it came from kept
oto build --project "$WORK/garage2" && oto query --project "$WORK/garage2" ask GQ1 GARAGE=garage.north   # the same answer, from the pack's sample
python3 -c 'import json,os; o=json.load(open(os.environ["WORK"]+"/garage2/project.config.json"))["ontology"]; print(o["name"], o["release"], o["origin"], o["pack"]["name"])'   # garage-fleet 1 pack garage
```

Pass when the second project records `origin: pack` and the pack's name, and answers GQ1 from the
sample the pack carries. The registry you made is a real one: `/plugin marketplace add <path>` in
Claude Code lists `garage` as a plugin.

## What this does not cover

Everything a pack brings, which is every domain: the architecture graph and `oto arch`, the domain
model, the data layer, the policy, the plan. Neo4j as the store, repository mode with its workflows,
the ontology explorer and the studio views, federation between graphs, evaluation against a gold
set. Those are sections of [E2E-TESTING.md](E2E-TESTING.md), each installing its pack first.
