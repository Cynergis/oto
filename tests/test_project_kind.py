"""Two kinds of project, and a vocabulary that is the pack's (docs/plans/ontology-workspace.md, phase 1).

A project records its `kind` (knowledge; concierge already) and whether its vocabulary is `derived`
from the packs it started from or its `own`. Started from a pack, or from an ontology a pack carries,
the vocabulary is derived: ontology.config.json is what the packs compose, written by the engine, and a
hand edit is refused by `oto ontology check` and `accept`, which name the way to change it (the pack's
workspace, or a pack that extends it); `oto ontology import` into a derived project is refused the same
way. Started with no ontology, or from a directory, the vocabulary is the project's own, as every
project made before this plan is. `oto ontology update` re-derives a derived project after fetching;
`oto status` says which it is."""
import contextlib
import io
import json
import os

import pytest

from oto.cli import main
from oto.model import derived, ontologies
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_PACKS = os.path.join(ROOT, "tests", "fixtures", "packs")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def _init(root, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug=os.path.basename(root), name=os.path.basename(root).title(), **kw)
    with open(os.path.join(root, "project.config.json"), encoding="utf-8") as f:
        return json.load(f)


def _config(root):
    with open(os.path.join(root, "ontology.config.json"), encoding="utf-8") as f:
        return json.load(f)


def _write_config(root, config):
    with open(os.path.join(root, "ontology.config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


# ---- the record ----

def test_a_project_records_its_kind_and_whether_its_vocabulary_is_its_own(tmp_path):
    bare = _init(str(tmp_path / "bare"))
    assert bare["kind"] == "knowledge" and bare["vocabulary"] == derived.OWN, "no ontology: the project writes its own"
    assert "ONLY source" in _config(str(tmp_path / "bare"))["_about"]
    from_pack = _init(str(tmp_path / "estate"), ontology="software-architecture")
    assert from_pack["kind"] == "knowledge" and from_pack["vocabulary"] == derived.DERIVED, "an installed pack's vocabulary is the pack's"
    assert from_pack["ontology"]["origin"] == ontologies.PACK
    about = _config(str(tmp_path / "estate"))["_about"]
    assert "derived" in about.lower() and "software-architecture" in about and "do not edit" in about.lower(), about
    from_dir = _init(str(tmp_path / "copy"), ontology=ontologies.dir_for("organization-process"))
    assert from_dir["vocabulary"] == derived.OWN, "a directory is a copy the project owns"
    concierge = _init(str(tmp_path / "root"), concierge=True)
    assert concierge["kind"] == "concierge" and concierge["vocabulary"] == derived.DERIVED, "a concierge root rests on oto-core and edits nothing"
    assert derived.mode(Project.standard(str(tmp_path / "bare"))) == derived.OWN
    assert derived.mode(Project.standard(str(tmp_path / "estate"))) == derived.DERIVED


def test_a_project_made_before_this_reads_as_owning_its_vocabulary(tmp_path):
    root = str(tmp_path / "old")
    _init(root, ontology="software-architecture")
    with open(os.path.join(root, "project.config.json"), encoding="utf-8") as f:
        config = json.load(f)
    config.pop("vocabulary"); config.pop("kind")
    with open(os.path.join(root, "project.config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    assert derived.mode(Project.standard(root)) == derived.OWN and derived.kind(Project.standard(root)) == "knowledge"
    code, out = _cli("ontology", "check", "--project", root)
    assert code == 0, out


# ---- what derived means ----

def test_the_derived_vocabulary_is_what_the_packs_compose_and_a_hand_edit_is_refused(tmp_path):
    root = str(tmp_path / "estate")
    _init(root, ontology="software-architecture")
    project = Project.standard(root)
    assert derived.drift(project) == [], "fresh from init, the file is the composition"
    composed = derived.compose(project)
    assert composed["name"] == "Estate" and "Component" in composed["classes"] and "Document" in composed["classes"], "composed with its bases, named after the project"
    code, out = _cli("ontology", "check", "--project", root)
    assert code == 0, out

    config = _config(root)
    config["classes"]["Depot"] = {"definition": "Somewhere a bus sleeps."}
    config["properties"]["part_of"]["range"] = config["properties"]["part_of"]["range"] + "|Depot"
    _write_config(root, config)
    drift = derived.drift(project)
    assert any("Depot" in line for line in drift) and any("part_of" in line for line in drift), drift
    code, out = _cli("ontology", "check", "--project", root)
    assert code == 1 and "derived" in out and "software-architecture" in out and "Depot" in out, out
    assert "oto pack new" in out and "--extends" in out, "the way to change it is a pack that extends, or the pack's own workspace: " + out
    code, out = _cli("ontology", "accept", "--project", root)
    assert code == 1 and "derived" in out, out

    written = derived.write(project)
    assert written.endswith("ontology.config.json") and derived.drift(project) == []
    assert "Depot" not in _config(root)["classes"], "re-derived: the hand edit is gone, the packs' vocabulary is back"
    code, out = _cli("ontology", "check", "--project", root)
    assert code == 0, out


def test_import_into_a_derived_project_is_refused_and_an_own_project_takes_it(tmp_path):
    root = str(tmp_path / "estate")
    _init(root, ontology="software-architecture")
    code, out = _cli("ontology", "import", "--from", "organization-process", "--project", root)
    assert code == 1 and "derived" in out and "organization-process" not in _config(root).get("classes", {}).get("Unit", {}).get("definition", ""), out
    assert "Unit" not in _config(root)["classes"], "nothing was written"
    own = str(tmp_path / "own")
    _init(own)
    code, out = _cli("ontology", "import", "--from", "organization-process", "--project", own)
    assert code == 0 and "Unit" in _config(own)["classes"], out


def test_a_merged_start_is_derived_from_every_part(tmp_path):
    root = str(tmp_path / "both")
    config = _init(root, ontology="software-architecture,organization-process")
    assert config["vocabulary"] == derived.DERIVED and config["ontology"]["source"] == "merge"
    project = Project.standard(root)
    assert derived.names(project) == ["software-architecture", "organization-process"]
    assert derived.drift(project) == []
    assert {"Component", "Unit"} <= set(_config(root)["classes"])


# ---- update and status ----

def test_update_re_derives_a_derived_project_and_status_says_so(tmp_path):
    root = str(tmp_path / "estate")
    _init(root, ontology="software-architecture")
    config = _config(root)
    config["classes"]["Depot"] = {"definition": "A hand edit."}
    _write_config(root, config)
    code, out = _cli("ontology", "update", "--project", root)
    assert code == 0 and "re-derived" in out and "software-architecture" in out, out
    assert "Depot" not in _config(root)["classes"]
    code, out = _cli("status", "--project", root)
    assert code == 0 and "derived from software-architecture @12" in out, out
    own = str(tmp_path / "own")
    _init(own)
    code, out = _cli("status", "--project", own)
    assert code == 0 and "derived from" not in out, "an own vocabulary says nothing new: " + out
