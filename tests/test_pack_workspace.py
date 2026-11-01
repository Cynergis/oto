"""The ontology workspace (docs/plans/ontology-workspace.md, phase 2): a pack in the making, in a directory of
its own, with a trial project beside the deliverable.

`oto pack new <name> --to <dir>` lays the workspace out with no ontology on the machine: a starter vocabulary
to fill (the interview's job), the bases it extends embedded, the trial project, the two workflows.
`oto pack check --strict` holds the deliverable to the vocabulary's three gates and the rationale.
`oto pack try` writes the trial project's vocabulary from the pack, builds it and asks its questions.
`oto pack publish` ships the pack and leaves the trial project and the workflows behind.
`oto pack new --from-project` opens a workspace from a project that grew its own vocabulary: the bridge."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys

import pytest

from oto.cli import main
from oto.model import packs
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GARAGE_CONFIG = {
    "name": "garage", "ontology_version": 1, "strict_domains": False, "languages": ["en"],
    "classes": {"Bus": {"definition": "A vehicle of the fleet, identified by its plate."},
                "Garage": {"definition": "A depot where buses are parked and maintained."},
                "Mechanic": {"definition": "A person who maintains buses at a garage."}},
    "properties": {"parked_at": {"domain": "Bus", "range": "Garage", "inverse": "parks", "definition": "Where this bus is based."},
                   "maintained_by": {"domain": "Bus", "range": "Mechanic", "inverse": "maintains", "definition": "Who keeps this bus on the road."},
                   "works_at": {"domain": "Mechanic", "range": "Garage", "inverse": "employs", "definition": "The garage a mechanic works at."}},
    "attributes": {"Bus": {"plate": {"type": "string", "required": True, "definition": "The registration plate."},
                           "capacity": {"type": "integer", "definition": "Seats."}}}}
GARAGE_RATIONALE = {"classes": {
    "Bus": {"question": "Which buses do we run, and where is each based?", "why": "The fleet is what the garage exists for; a bus is the unit everything else attaches to.", "alternatives": "A spreadsheet of plates.", "validated_by": "Test Driver"},
    "Garage": {"question": "Where is a bus parked and maintained?", "why": "Two depots; where a bus lives decides who sees it and who services it.", "alternatives": "A garage attribute on the bus.", "validated_by": "Test Driver"},
    "Mechanic": {"question": "Who keeps a given bus on the road?", "why": "One accountable person per bus is the maintenance plan's unit of accountability.", "alternatives": "A free-text note per bus.", "validated_by": "Test Driver"}},
  "properties": {
    "parked_at": {"question": "Where is this bus based?", "why": "Dispatch and maintenance both start from the depot a bus returns to each night.", "alternatives": "A garage attribute on the bus.", "validated_by": "Test Driver"},
    "maintained_by": {"question": "Who is accountable for keeping this bus on the road?", "why": "One named mechanic per bus is the maintenance plan's unit of accountability.", "alternatives": "A free-text note per bus.", "validated_by": "Test Driver"},
    "works_at": {"question": "At which garage does this mechanic work?", "why": "A mechanic services the buses of the garage they work at; a planner spots a bus maintained from the wrong depot.", "alternatives": "Inferring it from the buses they maintain.", "validated_by": "Test Driver"}}}
GARAGE_QUESTIONS = {"questions": {
    "GQ1": {"who": "a dispatcher", "question": "Which buses are parked at $GARAGE, with their plate and capacity?", "why": "Dispatch starts from what is at the depot.",
            "validated_by": "Test Driver", "params": {"GARAGE": {"type": "Garage"}},
            "ask": {"when": [{"node": "b", "type": "Bus"}, {"edge": ["b", "parked_at", "$GARAGE"]}], "select": ["b.label", "b.plate", "b.capacity"]},
            "gate": "any", "gaps": {"when": [{"node": "$GARAGE", "type": "Garage"}], "say": "no bus is parked at this garage"}},
    "GQ2": {"who": "a maintenance planner", "question": "Who maintains $BUS, and at which garage do they work?", "why": "One accountable mechanic per bus.",
            "validated_by": "Test Driver", "params": {"BUS": {"type": "Bus"}},
            "ask": {"when": [{"edge": ["$BUS", "maintained_by", "m"]}, {"node": "m", "type": "Mechanic"}, {"edge": ["m", "works_at", "g"]}, {"node": "g", "type": "Garage"}],
                    "select": ["m.label", "g.label"]},
            "gate": "any", "gaps": {"when": [{"node": "$BUS", "type": "Bus"}], "say": "nobody is recorded as maintaining this bus"}}}}
GARAGE_SAMPLE = {"nodes": [
    {"id": "garage.north", "type": "Garage", "label": "North garage", "attributes": {}, "as_of": "2026-11-01", "valid_from": "2026-11-01", "source_doc": "sample", "status": "current", "sources": ["sample"]},
    {"id": "mechanic.ada", "type": "Mechanic", "label": "Ada Okafor", "attributes": {}, "as_of": "2026-11-01", "valid_from": "2026-11-01", "source_doc": "sample", "status": "current", "sources": ["sample"]},
    {"id": "bus.nw-101", "type": "Bus", "label": "Bus NW-101", "attributes": {"plate": "NW-101", "capacity": 48}, "as_of": "2026-11-01", "valid_from": "2026-11-01", "source_doc": "sample", "status": "current", "sources": ["sample"]}],
  "edges": [{"from": "bus.nw-101", "rel": "parked_at", "to": "garage.north"}, {"from": "bus.nw-101", "rel": "maintained_by", "to": "mechanic.ada"},
            {"from": "mechanic.ada", "rel": "works_at", "to": "garage.north"}]}


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def _fill(workspace, name="garage"):
    """The interview's output, written by hand: the deliverable's files."""
    own = os.path.join(workspace, "ontology", name)
    for filename, payload in (("ontology.config.json", GARAGE_CONFIG), ("ontology.rationale.json", GARAGE_RATIONALE),
                              ("questions.json", GARAGE_QUESTIONS), ("sample.graph.json", GARAGE_SAMPLE)):
        with open(os.path.join(own, filename), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    with open(os.path.join(own, "README.md"), "w", encoding="utf-8") as f:
        f.write("# Garage\n\nBuses, where they are based, who maintains them. Edit it as the garage changes.\n")


# ---- the workspace ----

def test_pack_new_lays_out_a_workspace_with_a_starter_vocabulary_the_interview_fills(tmp_path):
    code, out = _cli("pack", "new", "garage", "--to", str(tmp_path), "--domain", "operations", "--maintainer", "Test Driver")
    assert code == 0 and "workspace" in out and "not yet usable" in out and "interview" in out, out
    w = str(tmp_path / "garage")
    for path in ("manifest.json", "README.md", "ontology/garage/manifest.json", "ontology/garage/ontology.config.json",
                 "ontology/garage/ontology.rationale.json", "ontology/garage/questions.json", "ontology/garage/sample.graph.json",
                 "ontology/garage/README.md", "ontology/oto-core/ontology.config.json", "skills/start/SKILL.md", ".claude-plugin/plugin.json",
                 "trial/project.config.json", "trial/ontology.config.json", ".github/workflows/pack-check.yml", ".github/workflows/pack-publish.yml"):
        assert os.path.exists(os.path.join(w, path)), path
    manifest = packs.read(w)
    assert manifest["name"] == "garage" and manifest["release"] == 1 and manifest["domain"] == "operations" and manifest["ontology"]["name"] == "garage"
    with open(os.path.join(w, "ontology", "garage", "manifest.json"), encoding="utf-8") as f:
        own = json.load(f)
    assert own["extends"] == ["oto-core"] and own["release"] == 1, "a root vocabulary rests on the engine's own"
    with open(os.path.join(w, "ontology", "garage", "ontology.config.json"), encoding="utf-8") as f:
        config = json.load(f)
    assert config["classes"] == {} and config["properties"] == {} and config["ontology_version"] == 1
    with open(os.path.join(w, "trial", "project.config.json"), encoding="utf-8") as f:
        trial = json.load(f)
    assert trial["kind"] == "knowledge" and trial["trial_of"] == "garage", "the trial project is where documents are read; the pack is the deliverable"
    assert packs.check(w), "an empty vocabulary is not usable yet: that is the interview's job"
    with open(os.path.join(w, ".github", "workflows", "pack-check.yml"), encoding="utf-8") as f:
        assert "oto pack check" in f.read()
    with open(os.path.join(w, ".github", "workflows", "pack-publish.yml"), encoding="utf-8") as f:
        assert "oto pack publish" in f.read()


def test_pack_new_extends_the_packs_it_names_and_embeds_them(tmp_path):
    code, out = _cli("pack", "new", "depot", "--to", str(tmp_path), "--extends", "software-architecture")
    assert code == 0, out
    w = str(tmp_path / "depot")
    with open(os.path.join(w, "ontology", "depot", "manifest.json"), encoding="utf-8") as f:
        assert json.load(f)["extends"] == ["software-architecture"]
    assert sorted(os.listdir(os.path.join(w, "ontology"))) == ["depot", "oto-core", "portfolio", "product", "software-architecture"], \
        "the base and everything it rests on, so the workspace composes with nothing else on the machine"


# ---- the gates ----

def test_pack_check_strict_holds_the_deliverable_to_the_rationale_as_well(tmp_path):
    _cli("pack", "new", "garage", "--to", str(tmp_path))
    w = str(tmp_path / "garage")
    _fill(w)
    code, out = _cli("pack", "check", w)
    assert code == 0 and "check clean" in out, out
    code, out = _cli("pack", "check", w, "--strict")
    assert code == 0 and "check clean" in out and "rationale" in out, out
    own = os.path.join(w, "ontology", "garage", "ontology.rationale.json")
    with open(own, encoding="utf-8") as f:
        rationale = json.load(f)
    rationale["classes"]["Bus"]["validated_by"] = ""
    del rationale["properties"]["works_at"]
    with open(own, "w", encoding="utf-8") as f:
        json.dump(rationale, f)
    code, out = _cli("pack", "check", w)
    assert code == 0, "without --strict the rationale is advisory, as it is for the packs the registry already holds: " + out
    code, out = _cli("pack", "check", w, "--strict")
    assert code == 1 and "rationale" in out and "works_at" in out and "Bus" in out, out


def test_pack_try_writes_the_trial_vocabulary_from_the_pack_builds_it_and_asks_its_questions(tmp_path):
    _cli("pack", "new", "garage", "--to", str(tmp_path))
    w = str(tmp_path / "garage")
    _fill(w)
    code, out = _cli("pack", "try", w)
    import re
    answered = re.search(r"questions: (\d+) declared; the live graph answers (\d+) as required", out)
    assert code == 0 and answered and answered.group(1) == answered.group(2) and int(answered.group(1)) >= 2, \
        "the pack's two questions and the bases' own, every one answered from the sample: " + out
    with open(os.path.join(w, "trial", "ontology.config.json"), encoding="utf-8") as f:
        trial = json.load(f)
    assert {"Bus", "Garage", "Mechanic", "Document", "Tool", "Graph"} <= set(trial["classes"]), "the pack's vocabulary composed with its bases"
    assert "trial" in trial["_about"].lower() and "oto pack try" in trial["_about"], "the trial's file says it is written from the pack"
    with open(os.path.join(w, "trial", "questions.json"), encoding="utf-8") as f:
        assert set(json.load(f)["questions"]) >= {"GQ1", "GQ2"}
    code, out = _cli("query", "--project", os.path.join(w, "trial"), "ask", "GQ1", "GARAGE=garage.north")
    assert code == 0 and "b.plate=NW-101" in out, "the trial starts from the pack's sample: " + out
    # a document and a proposal in the trial survive the next `try`: only the vocabulary is the pack's
    with open(os.path.join(w, "trial", "inbox", "notes.md"), "w", encoding="utf-8") as f:
        f.write("Bus NW-205 is parked at the South garage.\n")
    code, out = _cli("pack", "try", w)
    assert code == 0 and os.path.exists(os.path.join(w, "trial", "inbox", "notes.md")), out


# ---- the release ----

def test_pack_publish_ships_the_pack_and_leaves_the_trial_project_and_the_workflows_behind(tmp_path, monkeypatch):
    monkeypatch.setenv("OTO_REGISTRIES", str(tmp_path / "registries.json"))
    _cli("pack", "new", "garage", "--to", str(tmp_path / "work"))
    w = str(tmp_path / "work" / "garage")
    _fill(w)
    os.makedirs(os.path.join(w, "tests"))
    with open(os.path.join(w, "tests", "test_garage.py"), "w", encoding="utf-8") as f:
        f.write("def test_nothing():\n    pass\n")
    bare = str(tmp_path / "registry.git")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True)
    code, out = _cli("pack", "publish", "--from", w, "--to", bare, "--registry-name", "test", "--note", "first cut")
    assert code == 0 and "published pack garage @1" in out, out
    clone = str(tmp_path / "clone")
    subprocess.run(["git", "clone", "-q", bare, clone], check=True)
    shipped = sorted(os.listdir(os.path.join(clone, "packs", "garage")))
    assert "trial" not in shipped and ".github" not in shipped, shipped
    assert "tests" in shipped and "ontology" in shipped and "skills" in shipped, shipped


# ---- the bridge ----

def test_pack_new_from_a_project_that_grew_its_own_vocabulary_opens_a_workspace(tmp_path):
    root = str(tmp_path / "kb")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="kb", name="Northwind Garage")
    for filename, payload in (("ontology.config.json", dict(GARAGE_CONFIG, name="Northwind Garage", temporal=json.load(open(os.path.join(root, "ontology.config.json")))["temporal"])),
                              ("ontology.rationale.json", GARAGE_RATIONALE), ("questions.json", GARAGE_QUESTIONS)):
        with open(os.path.join(root, filename), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
        json.dump(GARAGE_SAMPLE, f)
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    code, out = _cli("pack", "new", "garage-fleet", "--from-project", root, "--to", str(tmp_path / "work"), "--maintainer", "Test Driver")
    assert code == 0 and "from the project" in out, out
    w = str(tmp_path / "work" / "garage-fleet")
    assert os.path.exists(os.path.join(w, "ontology", "garage-fleet", "ontology.config.json")) and os.path.exists(os.path.join(w, "trial", "project.config.json"))
    code, out = _cli("pack", "check", w)
    assert code == 0 and "check clean" in out, out
    code, out = _cli("pack", "try", w)
    assert code == 0 and "as required" in out and "answers 0" not in out, out


def test_a_workspace_may_live_in_a_folder_of_another_name_as_the_sandbox_s_project_folder_does(tmp_path):
    """`oto sandbox up --kind ontology` lays the workspace out in the sandbox's `project` folder; an installed pack
    lives under its own name, but a workspace is a repository and may be called anything."""
    w = str(tmp_path / "project")
    directory, problems = packs.new("garage", into=w)
    assert directory == w and os.path.exists(os.path.join(w, "trial", "project.config.json"))
    assert [p for p in problems if "directory" in p] == [], problems
    assert len(problems) == 1 and "declares no classes" in problems[0], "the one problem is the empty vocabulary: " + "; ".join(problems)
    _fill(w)
    code, out = _cli("pack", "check", w, "--strict")
    assert code == 0 and "check clean" in out, out
    code, out = _cli("pack", "try", w)
    assert code == 0 and "as required" in out, out
