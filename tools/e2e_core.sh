#!/usr/bin/env bash
# The core, end to end, on the engine alone: no pack installed, no vocabulary but oto-core in reach.
# A vocabulary is created by hand, facts enter through ingest and the four gates, the graph is built,
# queried and served, deployed through dev, test and prod, exported as an ontology, made into a pack,
# published to a registry, installed from it, and a second project starts from the pack. Every step
# says what it expects and stops at the first miss. docs/E2E-CORE.md is the same test, read by a person.
#
#   tools/e2e_core.sh [work dir]      # default: a fresh temporary directory, kept for inspection
#   OTO="python3 -m oto.cli" tools/e2e_core.sh      # an engine checkout rather than the installed tool
#   PORT=8891 tools/e2e_core.sh                     # the port the served step uses (default 8891)
set -u
OTO="${OTO:-oto}"
PORT="${PORT:-8891}"
WORK="${1:-$(mktemp -d "${TMPDIR:-/tmp}/oto-e2e-core.XXXXXX")}"
mkdir -p "$WORK/user" "$WORK/packs" "$WORK/claude"
# The engine sees only what this test creates: no user ontologies, no installed packs, no plugins, no registries.
export OTO_ONTOLOGIES="$WORK/user" OTO_PACKS="$WORK/packs" CLAUDE_CONFIG_DIR="$WORK/claude" OTO_REGISTRIES="$WORK/registries.json"
P="$WORK/garage"
OUT="$WORK/last-output.txt"
STEPS=0

say() { printf '\n### %s\n' "$1"; }
fail() { printf '\nFAILED at: %s\n--- output ---\n' "$1"; cat "$OUT"; printf '\nwork dir kept: %s\n' "$WORK"; exit 1; }
# expect "<text the output must contain>" <command...>: run it, show its tail, stop when the text is missing
expect() { local want="$1"; shift; STEPS=$((STEPS + 1)); printf '$ %s\n' "$*"; "$@" >"$OUT" 2>&1; local code=$?
           tail -4 "$OUT" | sed "s|$WORK|\$WORK|g" | cut -c1-160; [ $code -eq 0 ] || fail "$* (exit $code)"
           grep -q -- "$want" "$OUT" || fail "$* (expected: $want)"; }
# expect_refused "<text>" <command...>: the command must fail, and say why in these words
expect_refused() { local want="$1"; shift; STEPS=$((STEPS + 1)); printf '$ %s   # refused on purpose\n' "$*"; "$@" >"$OUT" 2>&1 && fail "$* (should have been refused)"
                   tail -2 "$OUT" | cut -c1-160; grep -q -- "$want" "$OUT" || fail "$* (expected refusal: $want)"; }

say "0. The engine alone"
expect "oto " $OTO version
expect "oto-core" $OTO ontology list

say "1. A project, and a vocabulary written by hand: classes, relations, attributes, why each exists, what it must answer"
expect "declare your classes" $OTO init --name "Northwind Garage" --slug garage --project "$P"
mkdir -p "$P/proposals"
python3 - "$P" <<'EOF'
import json, sys
root = sys.argv[1]
p = root + "/ontology.config.json"; c = json.load(open(p))
c["name"] = "Garage"; c["ontology_version"] = 1
c["classes"].update({"Bus": {"definition": "A vehicle of the fleet, identified by its plate."},
                     "Garage": {"definition": "A depot where buses are parked and maintained."},
                     "Mechanic": {"definition": "A person who maintains buses at a garage."}})
c["properties"].update({"parked_at": {"domain": "Bus", "range": "Garage", "inverse": "parks", "definition": "Where this bus is based."},
                        "maintained_by": {"domain": "Bus", "range": "Mechanic", "inverse": "maintains", "definition": "Who keeps this bus on the road."},
                        "works_at": {"domain": "Mechanic", "range": "Garage", "inverse": "employs", "definition": "The garage a mechanic works at."}})
c.setdefault("attributes", {})["Bus"] = {"plate": {"type": "string", "required": True, "definition": "The registration plate."},
                                         "capacity": {"type": "integer", "definition": "Seats."}}
json.dump(c, open(p, "w"), indent=2, ensure_ascii=False)
rationale = {"_about": "Why each class and relation exists, and who confirmed it.", "classes": {
    "Bus": {"question": "Which buses do we run, and where is each based?", "why": "The fleet is what the garage exists for; a bus is the unit everything else attaches to.", "alternatives": "A spreadsheet of plates. It cannot be linked to a garage or a mechanic.", "validated_by": "Test Driver"},
    "Garage": {"question": "Where is a bus parked and maintained?", "why": "Two depots; where a bus lives decides who sees it and who services it.", "alternatives": "A garage attribute on the bus. It could not be queried from the garage's side.", "validated_by": "Test Driver"},
    "Mechanic": {"question": "Who keeps a given bus on the road?", "why": "One accountable person per bus is the maintenance plan's unit; a list of names nobody can hold to a vehicle is not a plan.", "alternatives": "A free-text note per bus. It cannot be listed per mechanic or checked for gaps.", "validated_by": "Test Driver"}},
  "properties": {
    "parked_at": {"question": "Where is this bus based?", "why": "Dispatch and maintenance both start from the depot a bus returns to each night; the base garage decides who sees it and who services it.", "alternatives": "A garage attribute on the bus. It could not be queried from the garage's side.", "validated_by": "Test Driver"},
    "maintained_by": {"question": "Who is accountable for keeping this bus on the road?", "why": "One named mechanic per bus is the maintenance plan's unit of accountability; without the relation the plan is a list of names nobody can hold to a vehicle.", "alternatives": "A free-text note per bus. It cannot be listed per mechanic or checked for gaps.", "validated_by": "Test Driver"},
    "works_at": {"question": "At which garage does this mechanic work?", "why": "A mechanic services the buses of the garage they work at; the relation lets a planner spot a bus maintained from the wrong depot.", "alternatives": "Inferring it from the buses they maintain. A new mechanic with no bus yet would be nowhere.", "validated_by": "Test Driver"}}}
json.dump(rationale, open(root + "/ontology.rationale.json", "w"), indent=2, ensure_ascii=False)
questions = {"_about": "What the garage graph must answer; a term no question cites has no reason to exist.", "questions": {
  "GQ1": {"who": "a dispatcher", "question": "Which buses are parked at $GARAGE, with their plate and capacity?", "why": "Dispatch starts from what is at the depot.",
          "validated_by": "Test Driver", "params": {"GARAGE": {"type": "Garage"}},
          "ask": {"when": [{"node": "b", "type": "Bus"}, {"edge": ["b", "parked_at", "$GARAGE"]}], "select": ["b.label", "b.plate", "b.capacity"]},
          "gate": "any", "gaps": {"when": [{"node": "$GARAGE", "type": "Garage"}], "say": "no bus is parked at this garage"}},
  "GQ2": {"who": "a maintenance planner", "question": "Who maintains $BUS, and at which garage do they work?", "why": "One accountable mechanic per bus.",
          "validated_by": "Test Driver", "params": {"BUS": {"type": "Bus"}},
          "ask": {"when": [{"edge": ["$BUS", "maintained_by", "m"]}, {"node": "m", "type": "Mechanic"}, {"edge": ["m", "works_at", "g"]}, {"node": "g", "type": "Garage"}],
                  "select": ["m.label", "g.label"]},
          "gate": "any", "gaps": {"when": [{"node": "$BUS", "type": "Bus"}], "say": "nobody is recorded as maintaining this bus"}}}}
json.dump(questions, open(root + "/questions.json", "w"), indent=2, ensure_ascii=False)
print("ontology.config.json, ontology.rationale.json and questions.json written: Bus, Garage, Mechanic; GQ1, GQ2")
EOF
expect "answers 2 as required" $OTO ontology check --project "$P" --strict
expect "confirmed by a named person: 3 class(es), 3 relation(s)" $OTO ontology rationale --project "$P" --strict
expect "accepted vocabulary version 1" $OTO ontology accept --project "$P"

say "2. A document into the corpus"
cat >"$P/inbox/fleet-notes.md" <<'EOF'
# Fleet notes, November 2026

Bus NW-101 (plate NW-101, 48 seats) is parked at the North garage and is maintained by Ada Okafor.
Bus NW-205 (plate NW-205, 32 seats) is parked at the South garage and is maintained by Ben Ruiz.
Ada Okafor works at the North garage. Ben Ruiz works at the South garage.
EOF
expect "extracted 1" $OTO ingest run --project "$P"
RUN=$(sed -n 's/^run \([^:]*\): extracted.*/\1/p' "$OUT" | head -1)
[ -n "$RUN" ] || fail "ingest run: no run id in the output"

say "3. A proposal citing the document, through the four gates"
cat >"$P/proposals/fleet.json" <<'EOF'
{"source_doc": "fleet-notes", "as_of": "2026-11-01",
 "nodes": [
  {"id": "garage.north", "type": "Garage", "label": "North garage", "attributes": {}, "evidence": [{"doc": "fleet-notes", "where": "body", "quote": "parked at the North garage"}]},
  {"id": "garage.south", "type": "Garage", "label": "South garage", "attributes": {}, "evidence": [{"doc": "fleet-notes", "where": "body", "quote": "parked at the South garage"}]},
  {"id": "mechanic.ada-okafor", "type": "Mechanic", "label": "Ada Okafor", "attributes": {}, "evidence": [{"doc": "fleet-notes", "where": "body", "quote": "maintained by Ada Okafor"}]},
  {"id": "mechanic.ben-ruiz", "type": "Mechanic", "label": "Ben Ruiz", "attributes": {}, "evidence": [{"doc": "fleet-notes", "where": "body", "quote": "maintained by Ben Ruiz"}]},
  {"id": "bus.nw-101", "type": "Bus", "label": "Bus NW-101", "attributes": {"plate": "NW-101", "capacity": 48}, "evidence": [{"doc": "fleet-notes", "where": "body", "quote": "Bus NW-101 (plate NW-101, 48 seats)"}]},
  {"id": "bus.nw-205", "type": "Bus", "label": "Bus NW-205", "attributes": {"plate": "NW-205", "capacity": 32}, "evidence": [{"doc": "fleet-notes", "where": "body", "quote": "Bus NW-205 (plate NW-205, 32 seats)"}]}],
 "edges": [
  {"from": "bus.nw-101", "rel": "parked_at", "to": "garage.north"}, {"from": "bus.nw-205", "rel": "parked_at", "to": "garage.south"},
  {"from": "bus.nw-101", "rel": "maintained_by", "to": "mechanic.ada-okafor"}, {"from": "bus.nw-205", "rel": "maintained_by", "to": "mechanic.ben-ruiz"},
  {"from": "mechanic.ada-okafor", "rel": "works_at", "to": "garage.north"}, {"from": "mechanic.ben-ruiz", "rel": "works_at", "to": "garage.south"}]}
EOF
expect "candidate created" $OTO curate start --project "$P"
expect "+6 node(s)" $OTO curate add --from "$P/proposals/fleet.json" --project "$P"
expect "ready to apply" $OTO curate check --project "$P"
expect "applied" $OTO curate apply --by "Test Driver" --note "the fleet notes" --project "$P"

say "4. Built, the run completed, queried three ways"
expect "knowledge layer written" $OTO build --project "$P"
expect "archived" $OTO ingest complete --run "$RUN" --project "$P"
expect "North garage" $OTO query --project "$P" entity bus.nw-101
expect "b.plate=NW-101" $OTO query --project "$P" ask GQ1 GARAGE=garage.north
expect "m.label=Ben Ruiz" $OTO query --project "$P" ask GQ2 BUS=bus.nw-205
expect "maintained by Ada Okafor" $OTO query --project "$P" neighbors "Ada Okafor"
expect "answers 2 as required" $OTO ontology check --project "$P"
expect "6 node(s), 6 edge(s)" $OTO status --project "$P"

say "5. Served: the same answers over HTTP"
$OTO serve --project "$P" --http "$PORT" >"$WORK/serve.log" 2>&1 &
SERVE=$!
for _ in 1 2 3 4 5 6 7 8 9 10; do curl -s -o /dev/null "http://127.0.0.1:$PORT/" && break; sleep 1; done
STEPS=$((STEPS + 1)); curl -s "http://127.0.0.1:$PORT/api/entity?term=bus.nw-101" >"$OUT" 2>&1; grep -q "Bus NW-101" "$OUT" || { kill "$SERVE" 2>/dev/null; fail "GET /api/entity?term=bus.nw-101"; }
echo "GET /api/entity?term=bus.nw-101 -> the bus, its relations and evidence"
STEPS=$((STEPS + 1)); curl -s "http://127.0.0.1:$PORT/api/ask?id=GQ1&GARAGE=garage.north" >"$OUT" 2>&1; grep -q "answered" "$OUT" || { kill "$SERVE" 2>/dev/null; fail "GET /api/ask?id=GQ1"; }
echo "GET /api/ask?id=GQ1&GARAGE=garage.north -> answered"
kill "$SERVE" 2>/dev/null; wait "$SERVE" 2>/dev/null

say "6. Deployed: a store repository, the build published to dev, the same commit promoted to test and prod"
git init -q --bare "$WORK/store.git"
expect "wrote oto.deploy.json" $OTO deploy init --project "$P" --repo garage --to "$WORK/store.git"
expect "dev -> test -> prod" $OTO deploy check --project "$P"
( cd "$P" && git init -q -b main . && git add -A && git -c user.name="Test Driver" -c user.email="test@example.com" commit -q -m "the garage graph" )
COMMIT=$(git -C "$P" rev-parse --short HEAD)
expect "to environment dev" $OTO publish --project "$P" --to dev --source "garage@$COMMIT" --by "Test Driver"
expect "promoted dev -> test" $OTO publish --project "$P" --to test --promote "$COMMIT" --by "kg-owners"
expect_refused "needs an approver" $OTO publish --project "$P" --to prod --promote "$COMMIT"
expect "promoted test -> prod" $OTO publish --project "$P" --to prod --promote "$COMMIT" --by "kg-owners, data-governance"
expect "prod     build" $OTO deploy status --project "$P"
expect "synced" $OTO sync --repo "$WORK/store.git" --branch test --dest "$WORK/store-test"
expect "a published query store" $OTO status --project "$WORK/store-test"

say "7. The vocabulary exported as an ontology, made into a pack"
expect "self-check clean" $OTO ontology export --project "$P" --name garage-fleet --summary "A bus garage: buses, where they are based, who maintains them"
expect "garage-fleet" $OTO ontology list
expect "check clean" $OTO pack new garage --ontology garage-fleet --to "$WORK/packs-work" --maintainer "Test Driver"
expect "check clean" $OTO pack check "$WORK/packs-work/garage"

say "8. The pack published to a registry, installed from it, and a second project started from the pack"
git init -q --bare "$WORK/registry.git"
expect "the registry was created" $OTO pack publish --from "$WORK/packs-work/garage" --to "$WORK/registry.git" --registry-name test --note "first cut"
expect "1 pack" $OTO registry add "$WORK/registry.git"
expect "added pack garage @1" $OTO pack add garage
expect "Project ready" $OTO init --name "Second garage" --slug garage2 --pack garage --project "$WORK/garage2"
expect "knowledge layer written" $OTO build --project "$WORK/garage2"
expect "b.plate=NW-101" $OTO query --project "$WORK/garage2" ask GQ1 GARAGE=garage.north
STEPS=$((STEPS + 1)); python3 - "$WORK/garage2" <<'EOF' >"$OUT" 2>&1 || fail "the second project's record"
import json, sys
o = json.load(open(sys.argv[1] + "/project.config.json"))["ontology"]
assert o["name"] == "garage-fleet" and o["origin"] == "pack" and o["pack"]["name"] == "garage", o
print("record: garage-fleet @%s, origin %s, pack %s" % (o["release"], o["origin"], o["pack"]["name"]))
EOF
cat "$OUT"

printf '\nALL STEPS PASSED (%d checks). Work dir: %s\n' "$STEPS" "$WORK"
