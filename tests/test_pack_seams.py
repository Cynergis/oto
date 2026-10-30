"""The pack seams (ADR-0006, step 2). A pack's manifest declares what it provides beyond its
vocabulary: build stages, commands, served endpoints, write hooks and framework adapters. The
engine loads a pack's contributions only when the pack is composed in the project (its own classes
are in the vocabulary); commands and adapters are discovered from every pack the machine has, since
a command must exist before a project is named. The core names none of the packs: the policy and
iam stages and the pack commands come from manifests, the engine ships no framework adapter at all
(ADR-0008: the calm pack is the registry's), and a toy pack in a temporary directory proves a pack
the engine has never heard of plugs in the same way."""
import contextlib
import importlib
import io
import json
import os
import sys
import textwrap
import urllib.request

import pytest

from oto import builder, extensions
from oto.cli import main
from oto.model import ontologies, ontology_manifest
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_STAGES = ["knowledge", "rules", "ontology", "semantic", "sqlite", "neo4j", "site"]


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


# ---- what the shipped packs declare ----

def test_the_shipped_packs_declare_what_they_provide_and_the_core_names_none_of_them():
    policy = ontologies.manifest_for("policy")["provides"]
    assert [s["name"] for s in policy["stages"]] == ["policy", "iam"]
    assert policy["stages"][0]["module"] == "oto.packs.policy.bundle_stage" and policy["stages"][0]["owns"] == ["policy"]
    assert policy["stages"][1]["module"] == "oto.packs.policy.iam_stage" and policy["stages"][1]["owns"] == ["iam"]
    assert policy["commands"] == [{"name": "policy", "module": "oto.packs.policy.cli", "label": "policy"}]
    assert policy["write_hooks"] == ["oto.packs.policy:enforce"] and policy["read_hooks"] == ["oto.packs.policy:police_read"]
    architecture = ontologies.manifest_for("architecture")["provides"]
    assert "adapters" not in architecture and architecture["commands"] == [{"name": "arch", "module": "oto.cli.arch", "label": "architecture"}]
    for pack in ontologies.available():
        assert "adapters" not in (ontologies.manifest_for(pack).get("provides") or {}), "%s: the engine ships no framework adapter (ADR-0008)" % pack
    for pack, command, module, label in (("work", "work", "oto.packs.work.cli", "work and communication"), ("data", "data", "oto.packs.data.cli", "data")):
        provides = ontologies.manifest_for(pack)["provides"]
        assert provides["commands"] == [{"name": command, "module": module, "label": label}], pack
    assert [n for n, _p in builder.STAGES] == CORE_STAGES, "the core's stage list names no pack"
    with open(os.path.join(ROOT, "oto", "cli", "__init__.py"), encoding="utf-8") as f:
        cli = f.read()
    for name in ("policy", "work", "data", "ddd", "arch"):
        assert "from . import %s" % name not in cli and ", %s," % name not in cli.split("CORE_COMMANDS")[1].split(")")[0], \
            "the CLI imports no pack command by name: %s" % name
    for path in ("oto/assertion.py", "oto/cli/curate.py", "oto/deploy.py"):
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            source = f.read()
        assert "policy.enforce" not in source and "_policy.enforce" not in source and "before_write" in source, path
    for pack in ontologies.available():
        assert ontology_manifest.problems(ontologies.dir_for(pack)) == [], pack


def test_a_manifest_s_provides_is_checked_in_shape(tmp_path):
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "ontology.config.json").write_text(json.dumps({"name": "Bad", "ontology_version": 1, "classes": {"Thing": {"definition": "a thing"}}, "properties": {}}))
    (bad / "README.md").write_text("bad\n")
    (bad / "manifest.json").write_text(json.dumps({"name": "bad", "release": 1, "provides": {
        "stages": [{"module": "x.y"}], "commands": "oto.cli.policy", "write_hooks": ["no-colon"], "adapters": [{"framework": "c4"}], "views": []}}))
    problems = ontology_manifest.problems(str(bad))
    text = "\n".join(problems)
    assert "stages" in text and "name" in text, text
    assert "commands must be a list" in text, text
    assert "write_hooks" in text and "module:function" in text, text
    assert "adapters" in text and "module" in text, text
    assert "views" in text and "not a kind" in text, text


# ---- a toy pack, unknown to the engine ----

TOY_EXT = '''
"""A toy pack's code: one of each contribution, recording what the engine called."""
import json, os

CALLS = []


def register(sub):
    p = sub.add_parser("toy", help="the toy pack's command")
    p.add_argument("--project", default=".")
    p.set_defaults(func=lambda args: print("toy says hello from %s" % args.project) or 0)


def run(project):
    out = os.path.join(project.layout.src, "toy")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "marker.json"), "w") as f:
        json.dump({"stage": "toy"}, f)
    print("toy: wrote the marker")


def before_write(project, action, by):
    CALLS.append((action, by))
    return "toy saw %s by %s" % (action, by)


def routes(project):
    return {"/api/toy": lambda args: (200, {"toy": True, "args": args})}


def read_model(project, path, at, **kw):
    return {"framework": "toy", "path": path, "at": at}


def write_model(project):
    return {"framework": "toy", "nodes": []}
'''


@pytest.fixture
def toy(tmp_path, monkeypatch):
    """A pack directory the engine discovers through OTO_ONTOLOGIES, with its code on sys.path."""
    packs = tmp_path / "ontologies"
    pack = packs / "toy"
    pack.mkdir(parents=True)
    (pack / "ontology.config.json").write_text(json.dumps({
        "name": "Toy", "ontology_version": 1, "strict_domains": False, "languages": ["en"],
        "classes": {"Toy": {"definition": "A toy: something the engine has never heard of."}},
        "properties": {"plays_with": {"domain": "Toy", "range": "Toy", "inverse": "played_with_by", "definition": "What a toy plays with."}},
        "attributes": {"Toy": {"colour": {"type": "string", "definition": "The toy's colour."}}}}))
    (pack / "ontology.rationale.json").write_text(json.dumps({
        "classes": {"Toy": {"question": "Which toys are there, and what colour is each? (TY1)", "why": "The one thing the toy pack is about: a toy is a node so it can play with another.", "validated_by": ""}},
        "properties": {"plays_with": {"question": "Which toy plays with which? (TY1)", "why": "Play is the only relation two toys have; without it the pack asks nothing.", "validated_by": ""}}}))
    (pack / "questions.json").write_text(json.dumps({"questions": {"TY1": {
        "who": "a child", "question": "Which toys play with which, and what colour is each?", "why": "the toy's question", "validated_by": "",
        "ask": {"when": [{"edge": ["a", "plays_with", "b"]}], "select": ["a", "a.colour", "b"]}, "gate": "any", "terms": ["Toy", "plays_with", "Toy.colour"]}}}))
    (pack / "sample.graph.json").write_text(json.dumps({"nodes": [
        {"id": "toy.bear", "type": "Toy", "label": "Bear", "summary": "A bear.", "attributes": {"colour": "brown"}, "as_of": "2026-10-28", "valid_from": "2026-10-28",
         "source_doc": "sample", "status": "current", "sources": ["sample"], "aliases": [], "tags": []},
        {"id": "toy.duck", "type": "Toy", "label": "Duck", "summary": "A duck.", "attributes": {"colour": "yellow"}, "as_of": "2026-10-28", "valid_from": "2026-10-28",
         "source_doc": "sample", "status": "current", "sources": ["sample"], "aliases": [], "tags": []}],
        "edges": [{"from": "toy.bear", "rel": "plays_with", "to": "toy.duck", "status": "current"}]}))
    (pack / "README.md").write_text("# Toy\n\nA toy pack: one class, one relation, one of each contribution. First draft; edit it.\n")
    (pack / "manifest.json").write_text(json.dumps({"name": "toy", "release": 1, "domain": "play", "summary": "A toy pack.", "extends": [],
                                                    "namespace": "https://toy.example/ont#", "engine": ">=0.11",
                                                    "carries": ["vocabulary", "rationale", "questions", "sample", "readme", "code"], "provides": {
        "stages": [{"name": "toy", "module": "toy_ext", "owns": []}],
        "commands": [{"name": "toy", "module": "toy_ext", "label": "toys"}],
        "endpoints": ["toy_ext"],
        "write_hooks": ["toy_ext:before_write"],
        "adapters": [{"framework": "toy", "module": "toy_ext", "import": "read_model", "export": "write_model"}]}}))
    code = pack / "code"                                   # a pack carries its own code: the engine puts code/ on the path when it loads the pack
    code.mkdir()
    (code / "toy_ext.py").write_text(textwrap.dedent(TOY_EXT))
    monkeypatch.setenv(ontologies.USER_DIR_ENV, str(packs))
    sys.modules.pop("toy_ext", None)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if not p.endswith(os.path.join("toy", "code"))])
    return str(pack)


def _project(tmp_path, ontology, slug):
    root = str(tmp_path / slug)
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug=slug, name=slug.title(), ontology=ontology)
    return root


def test_a_pack_carries_its_own_code_and_the_engine_puts_it_on_the_path_when_it_loads_the_pack(toy, tmp_path):
    """A pack from outside the engine (the user's directory, an installed plugin) brings its modules in
    its own code/ folder; nothing has to be installed on the machine's Python path for it to plug in."""
    assert extensions.code_dir("toy") == os.path.join(toy, "code")
    assert extensions.code_dir("policy") is None, "the engine's own packs import from the engine; they carry no code/"
    assert "code" in ontologies.manifest_for("toy")["carries"] and ontology_manifest.problems(toy) == []
    before = list(sys.path)
    assert os.path.join(toy, "code") not in before
    found = {c["name"]: c for c in extensions.commands()}
    assert found["toy"]["module"] == "toy_ext"
    code, out = _cli("toy", "--project", "anywhere")
    assert code == 0 and "toy says hello from anywhere" in out, out
    assert sys.path[0] == os.path.join(toy, "code"), "the pack's code/ is on the path once the pack is loaded"
    adapter = extensions.adapter("toy")
    assert adapter["module"].__file__.startswith(os.path.join(toy, "code")), "the module came from the pack, not from the machine"
    assert sys.path.count(os.path.join(toy, "code")) == 1, "added once, however many times the pack is loaded"


def test_a_pack_is_composed_when_its_own_classes_are_in_the_vocabulary(toy, tmp_path):
    assert ontologies.self_check("toy") == [], ontologies.self_check("toy")
    toys = _project(tmp_path, "toy", "toys")
    plain = _project(tmp_path, "data", "plain")
    assert "toy" in extensions.composed(Project.standard(toys)) and "toy" not in extensions.composed(Project.standard(plain))
    assert "data" in extensions.composed(Project.standard(plain)) and "policy" not in extensions.composed(Project.standard(plain))
    ledger = _project(tmp_path, "policy", "ledger")
    assert {"policy", "data", "agent"} <= set(extensions.composed(Project.standard(ledger))), "a pack and what it extends"


def test_a_composed_pack_s_stages_run_in_the_build_and_own_their_output(toy, tmp_path):
    toys = _project(tmp_path, "toy", "toys")
    project = Project.standard(toys)
    names = [n for n, _m in extensions.stages(project)]
    assert names == CORE_STAGES[:-1] + ["toy", "site"], "a pack's stage runs after the core targets and before the site"
    code, out = _cli("build", "--project", toys)
    assert code == 0 and "toy: wrote the marker" in out, out
    assert os.path.exists(os.path.join(project.layout.src, "toy", "marker.json"))
    plain = _project(tmp_path, "data", "plain")
    code, out = _cli("build", "--project", plain)
    assert code == 0 and "toy" not in out and "iam:" not in out and "policy:" not in out, "a project without the pack never sees its stages: " + out
    ledger = _project(tmp_path, "policy", "ledger")
    assert [n for n, _m in extensions.stages(Project.standard(ledger))] == CORE_STAGES[:-1] + ["policy", "iam", "site"]
    code, out = _cli("build", "--project", ledger)
    assert code == 0 and "policy: 4 rule(s)" in out and "iam: 4 binding(s)" in out, out
    paths = builder.generated_paths(Project.standard(ledger))
    assert Project.standard(ledger).layout.policy in paths and Project.standard(ledger).layout.iam in paths, "the stash knows what a pack's stage owns"
    assert Project.standard(plain).layout.policy not in builder.generated_paths(Project.standard(plain))


def test_a_pack_s_command_is_discovered_and_the_help_groups_it_under_its_pack(toy, tmp_path):
    found = {c["name"]: c for c in extensions.commands()}
    assert found["toy"]["module"] == "toy_ext" and found["toy"]["pack"] == "toy" and found["toy"]["label"] == "toys"
    assert {"policy", "work", "data", "arch"} <= set(found)
    assert "ddd" not in found, "the domain model is a pack of the registry (ADR-0010): the engine alone has no ddd command"
    code, out = _cli("toy", "--project", "somewhere")
    assert code == 0 and "toy says hello from somewhere" in out, out
    code, out = _cli("--help")
    assert "toy" in out and "toys" in out and "packs:" in out.lower(), out


def test_a_composed_pack_s_write_hook_runs_before_apply_decide_and_promote(toy, tmp_path):
    toys = _project(tmp_path, "toy", "toys")
    project = Project.standard(toys)
    ext = extensions._load("toy_ext", "toy")                 # the engine puts the pack's code/ on the path; the test does not
    ext.CALLS.clear()
    note = extensions.before_write(project, "curate apply", "Ada")
    assert note == "toy saw curate apply by Ada" and ext.CALLS == [("curate apply", "Ada")]
    plain = Project.standard(_project(tmp_path, "data", "plain"))
    assert extensions.before_write(plain, "curate apply", "Ada") is None and len(ext.CALLS) == 1, "a project without the pack calls no hook"
    code, out = _cli("curate", "start", "--project", toys)
    assert code == 0, out
    code, out = _cli("curate", "apply", "--by", "Ada", "--note", "nothing changed", "--project", toys)
    assert ("curate apply", "Ada") in ext.CALLS[1:], (code, out, ext.CALLS)


def test_a_composed_pack_s_endpoint_is_served_and_listed(toy, tmp_path):
    toys = _project(tmp_path, "toy", "toys")
    project = Project.standard(toys)
    code, out = _cli("build", "--project", toys)
    assert code == 0, out
    routes = extensions.routes(project)
    assert set(routes) == {"/api/toy"} and routes["/api/toy"]({"x": "1"}) == (200, {"toy": True, "args": {"x": "1"}})
    os.environ["OTO_DB"] = project.layout.database
    os.environ["OTO_PROJECT_CONFIG"] = project.config_path
    os.environ.pop("OTO_STORE", None)
    from oto.serve import engine, http as _http
    importlib.reload(engine)
    server = _http.Server(engine, "127.0.0.1", 0, app_dir=None, project_root=toys, identity=project.config()).start()
    try:
        with urllib.request.urlopen(server.url + "/api/toy?x=1", timeout=10) as r:
            assert r.status == 200 and json.loads(r.read().decode("utf-8")) == {"toy": True, "args": {"x": "1"}}
        with urllib.request.urlopen(server.url + "/api/tools", timeout=10) as r:
            assert "/api/toy" in json.loads(r.read().decode("utf-8"))["routes"]
    finally:
        server.stop()


def test_a_framework_adapter_is_chosen_by_name_and_the_engine_ships_none(toy, tmp_path):
    adapters = extensions.adapters()
    assert set(adapters) == {"toy"}, "the one framework on this machine is the toy's: the engine provides none (ADR-0008)"
    assert extensions.only_adapter() == "toy"
    toy_adapter = extensions.adapter("toy")
    assert toy_adapter["pack"] == "toy" and toy_adapter["migrate"] is None
    assert toy_adapter["read"](None, "model.toy", "2026-10-28") == {"framework": "toy", "path": "model.toy", "at": "2026-10-28"}
    assert toy_adapter["write"](None) == {"framework": "toy", "nodes": []}
    with pytest.raises(extensions.ExtensionError) as refused:
        extensions.adapter("calm")
    assert "calm" in str(refused.value) and "toy" in str(refused.value), "refused by name, the frameworks this machine has listed"
    invoice = _project(tmp_path, "architecture", "invoice")
    code, out = _cli("arch", "export", "--framework", "c4", "--project", invoice)
    assert code == 1 and "c4" in out and "toy" in out, out
    code, out = _cli("arch", "import", "--framework", "c4", "--file", "x.json", "--at", "2026-10-28", "--project", invoice)
    assert code == 1 and "c4" in out, out


def test_without_a_framework_pack_import_and_export_say_which_packs_would_provide_one(tmp_path):
    assert extensions.adapters() == {} and extensions.only_adapter() is None, "a bare machine: the engine ships no adapter"
    invoice = _project(tmp_path, "architecture", "invoice")
    code, out = _cli("arch", "export", "--project", invoice)
    assert code == 1 and "--framework" in out and "none" in out, out
    code, out = _cli("arch", "import", "--framework", "calm", "--file", "x.json", "--at", "2026-10-28", "--project", invoice)
    assert code == 1 and "no adapter for framework 'calm'" in out and "none" in out, out


# ---- the roadmap and the docs ----

def test_adr_0006_governs_the_seven_epics_in_the_roadmap_graph():
    with open(os.path.join(ROOT, "roadmap", "graph.json"), encoding="utf-8") as f:
        graph = json.load(f)
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert "decision.adr-0006" in nodes and nodes["decision.adr-0006"]["attributes"]["status"] == "accepted"
    governed = {e["to"] for e in graph["edges"] if e["from"] == "decision.adr-0006" and e["rel"] == "governs"}
    assert governed == {"workitem.epic-%s" % e for e in "cehijmn"}


def test_the_docs_describe_the_seams():
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "`provides`" in text and "write_hooks" in text and "adapters" in text and "extensions.py" in text
    with open(os.path.join(ROOT, "docs", "E2E-TESTING.md"), encoding="utf-8") as f:
        e2e = f.read()
    assert "## 33." in e2e and "provides" in e2e
