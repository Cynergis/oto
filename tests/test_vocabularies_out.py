"""A domain vocabulary is a pack of the registry; the engine ships its own vocabulary and no other
(ADR-0011). `oto-core` stays under oto/ontologies/, the schema the engine's code is written against;
the nine domain vocabularies it shipped (agent, architecture, auto-claims, organization-process,
platform, portfolio, product, professional-services, software-architecture) are packs of the registry,
and the suite carries them under tests/fixtures/packs, resolved the way an installed pack is. The arch
command, the code map, compile, impact and measure, and the served `arch_context` went with the
architecture pack into its own code/, mounted through the command seam and the new `provides.tools`
seam; `oto init --ontology <name>` fetches a vocabulary the machine lacks from the registries it knows,
and names `oto pack add` when none lists it; the repository files write the architecture workflow
only for a project that composes the pack; the documents say where everything went."""
import contextlib
import importlib
import io
import json
import os
import re

import pytest

from oto import adr as _adr, extensions, repo as _repo
from oto.cli import main
from oto.model import ontologies, registry as _registry
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_PACKS = os.path.join(ROOT, "tests", "fixtures", "packs")
DOMAIN = ("agent", "architecture", "auto-claims", "organization-process", "platform", "portfolio", "product", "professional-services",
          "software-architecture")
GONE = tuple("oto/ontologies/%s" % name for name in DOMAIN) + ("oto/arch.py", "oto/cli/arch.py", "tests/test_arch_context.py",
                                                                 "tests/test_arch_map.py", "tests/test_architecture_pack.py", "tests/fixtures/arch")
FORGETS = ("README.md", "docs/ARCHITECTURE.md", "docs/E2E-TESTING.md", "skills/README.md", "skills/concierge/SKILL.md", "skills/packs/SKILL.md",
           "oto/cli/__init__.py", "oto/extensions.py", "oto/model/ontologies.py", "oto/serve/engine.py", "oto/serve/http.py", "oto/repo.py")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def _init(root, ontology, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug=os.path.basename(root), name=os.path.basename(root).title(), ontology=ontology, **kw)
    with open(os.path.join(root, "project.config.json"), encoding="utf-8") as f:
        return json.load(f)


def _engine(root):
    """The served engine reloaded on a built project, as `oto serve` starts it."""
    project = Project.standard(root)
    os.environ["OTO_DB"] = project.layout.database
    os.environ["OTO_PROJECT_CONFIG"] = project.config_path
    os.environ.pop("OTO_STORE", None)
    from oto.serve import engine
    return importlib.reload(engine)


# ---- the engine ----

def test_the_engine_ships_its_own_vocabulary_and_no_other(monkeypatch, tmp_path):
    for path in GONE:
        assert not os.path.exists(os.path.join(ROOT, path)), path
    assert sorted(os.listdir(os.path.join(ROOT, "oto", "ontologies"))) == ["oto-core"], "oto-core, the engine's own schema, and nothing else"
    manifest = ontologies.manifest_for("oto-core")
    assert ontologies.origin("oto-core") == ontologies.BUILTIN and not manifest.get("provides"), "its own vocabulary provides no tool: it is the schema"
    monkeypatch.setenv("OTO_PACKS", str(tmp_path / "no-packs"))                   # a machine with the engine alone
    assert ontologies.available() == ["oto-core"], ontologies.available()
    assert extensions.commands() == [] and extensions.adapters() == {}, "no pack command, no framework adapter: every one is a pack's"
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "oto")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".py"):
                with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                    source = f.read()
                imports = "\n".join(l for l in source.splitlines() if l.lstrip().startswith(("from ", "import ")))
                assert "oto.arch" not in imports and "oto_architecture" not in imports and "import arch" not in imports, os.path.join(dirpath, name)
                for word in DOMAIN:
                    assert not re.search(r"""ontologies[/\\]%s\b""" % re.escape(word), source), "%s names a vocabulary the engine no longer ships" % os.path.join(dirpath, name)
    with open(os.path.join(ROOT, "oto", "serve", "engine.py"), encoding="utf-8") as f:
        engine_source = f.read()
    assert "arch_context" not in engine_source.replace("PACK_ROUTES", "") and "def _mount_pack_tools" in engine_source, \
        "the served context tool is the architecture pack's, mounted through provides.tools"


def test_the_fixture_packs_are_the_registry_s_and_resolve_as_installed_packs(tmp_path):
    with open(os.path.join(ROOT, "tests", "conftest.py"), encoding="utf-8") as f:
        assert "ADR-0011" in f.read() and os.environ["OTO_PACKS"] == FIXTURE_PACKS
    for name in DOMAIN:
        assert os.path.exists(os.path.join(FIXTURE_PACKS, name, "manifest.json")) and ontologies.origin(name) == ontologies.PACK, name
        assert ontologies.self_check(name) == [], (name, ontologies.self_check(name))
    with open(os.path.join(FIXTURE_PACKS, "architecture", "ontology", "architecture", "manifest.json"), encoding="utf-8") as f:
        provides = json.load(f)["provides"]
    assert provides == {"commands": [{"name": "arch", "module": "oto_architecture.cli", "label": "architecture"}], "tools": ["oto_architecture.served"]}
    assert os.path.exists(os.path.join(FIXTURE_PACKS, "architecture", "ontology", "architecture", "code", "oto_architecture", "cli.py")), \
        "the pack carries the command's code, as the registry's does"
    config = _init(str(tmp_path / "shop"), "product")
    assert config["ontology"]["name"] == "product" and config["ontology"]["origin"] == ontologies.PACK and config["ontology"]["release"] == 14, config["ontology"]
    code, out = _cli("ontology", "list")
    assert code == 0 and "oto-core" in out and "product" in out, out


def test_a_vocabulary_the_machine_lacks_is_fetched_from_a_registry_that_lists_it_or_the_pack_is_named(monkeypatch, tmp_path):
    monkeypatch.setenv("OTO_PACKS", str(tmp_path / "no-packs"))
    monkeypatch.setenv("OTO_ONTOLOGIES", str(tmp_path / "user"))
    assert "product" not in ontologies.available()
    monkeypatch.setattr(_registry, "find", lambda name: (None, None))
    with pytest.raises(ValueError) as refused:
        _init(str(tmp_path / "shop"), "product")
    message = str(refused.value)
    assert "product" in message and "ADR-0011" in message and "oto pack add product" in message and "oto registry add" in message, message

    def fetch(name, release=None, force=False, kind="ontology"):
        import shutil
        src = os.path.join(FIXTURE_PACKS, name, "ontology")
        for part in os.listdir(src):                               # as `oto ontology add` installs: the vocabulary and the ones it extends
            shutil.copytree(os.path.join(src, part), os.path.join(str(tmp_path / "user"), part), dirs_exist_ok=True)
        return str(tmp_path / "user" / name), {"name": name}
    monkeypatch.setattr(_registry, "find", lambda name: ({"name": "cynergis"}, {"name": name, "release": 14}))
    monkeypatch.setattr(_registry, "fetch", fetch)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        init(str(tmp_path / "store"), slug="store", name="Store", ontology="product")
    assert "not on this machine: fetched from the registry cynergis (release 14)" in out.getvalue(), out.getvalue()
    with open(os.path.join(str(tmp_path / "store"), "project.config.json"), encoding="utf-8") as f:
        assert json.load(f)["ontology"]["name"] == "product"


def test_a_pack_refreshed_from_its_own_embedded_copy_keeps_it(monkeypatch, tmp_path):
    """`oto pack refresh` re-embeds the ontology from this machine. Since the engine ships no domain
    vocabulary, the copy on the machine is usually the pack's own, under the packs directory: the
    sources are copied aside before ontology/ is cleared, or the refresh would delete what it copies."""
    import shutil
    from oto.model import packs
    mine = tmp_path / "packs"
    shutil.copytree(os.path.join(FIXTURE_PACKS, "architecture"), str(mine / "architecture"))
    monkeypatch.setenv("OTO_PACKS", str(mine))
    monkeypatch.setenv("OTO_ONTOLOGIES", str(tmp_path / "user"))
    assert ontologies.dir_for("architecture") == os.path.join(str(mine), "architecture", "ontology", "architecture"), "the only copy is the pack's own"
    old, new = packs.refresh(str(mine / "architecture"))
    assert (old, new) == (7, 7)
    assert os.path.exists(os.path.join(str(mine), "architecture", "ontology", "architecture", "code", "oto_architecture", "cli.py")), "the code travelled"
    assert sorted(os.listdir(os.path.join(str(mine), "architecture", "ontology"))) == ["architecture", "oto-core", "portfolio", "product", "software-architecture"]
    assert packs.check(str(mine / "architecture")) == [], packs.check(str(mine / "architecture"))


# ---- the gates' own apply ----

def test_facts_a_command_generated_land_through_the_gates_or_not_at_all(tmp_path):
    """`oto.curate.apply.apply_proposals`, the helper the architecture and policy packs call (it was the
    arch module's): a candidate, the proposals added, checked, applied with who and why, built; refused
    at the gate, the candidate is aborted and the graph unchanged."""
    from oto.curate.apply import GateError, apply_proposals
    root = str(tmp_path / "arch")
    _init(root, "architecture", empty=True)
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    seed = os.path.join(root, "seed.json")
    with open(seed, "w", encoding="utf-8") as f:
        json.dump({"source_doc": "estate", "as_of": "2026-10-01", "nodes": [
            {"id": "environment.production", "type": "Environment", "label": "Production", "attributes": {}}], "edges": []}, f)
    with pytest.raises(GateError) as refused:
        apply_proposals(Project.standard(root), [seed], "", "the estate")
    assert "--by" in str(refused.value)
    apply_proposals(Project.standard(root), [seed], "Sam Lee", "the estate")
    code, out = _cli("query", "--project", root, "entity", "environment.production")
    assert code == 0 and "Production" in out, out
    bad = os.path.join(root, "bad.json")
    with open(bad, "w", encoding="utf-8") as f:
        json.dump({"source_doc": "estate", "as_of": "2026-10-02", "nodes": [{"id": "nowhere.x", "type": "NoSuchClass", "label": "X", "attributes": {}}], "edges": []}, f)
    with pytest.raises(GateError) as refused:
        apply_proposals(Project.standard(root), [bad], "Sam Lee", "a bad one")
    assert "graph is unchanged" in str(refused.value) or "refused" in str(refused.value), str(refused.value)
    assert not os.path.exists(os.path.join(root, "candidate.json")) and not os.path.isdir(os.path.join(root, "candidate")), "the candidate was aborted"


# ---- the tools seam ----

def test_a_composed_pack_s_served_tools_are_mounted_beside_the_engine_s(tmp_path):
    invoice = str(tmp_path / "invoice")
    _init(invoice, "architecture")
    code, out = _cli("build", "--project", invoice)
    assert code == 0, out
    found = extensions.tools(Project.standard(invoice))
    assert [t["name"] for t in found] == ["arch_context"] and found[0]["pack"] == "architecture" and found[0]["route"] == "arch-context" and found[0]["forwardable"]
    engine = _engine(invoice)
    try:
        tool = engine.TOOL_BY_NAME["arch_context"]
        assert set(tool["inputSchema"]["properties"]) == {"path", "node"} and "before" in tool["description"]
        assert engine.PACK_ROUTES == {"arch-context": "arch_context"} and engine.ROUTE_OF["arch_context"] == "arch-context"
        assert "arch_context" in engine.FORWARDABLE, "a concierge can ask the architecture graph for a path's context (kg_call)"
        listed = engine.respond({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        assert "arch_context" in {t["name"] for t in listed["result"]["tools"]}
        reply = engine.respond({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "arch_context", "arguments": {"node": "component.invoice-intake"}}})
        text = "".join(c["text"] for c in reply["result"]["content"])
        assert not reply["result"]["isError"] and "Invoice intake" in text and "requirements:" in text and "modules:" in text, text
        with open(os.path.join(ROOT, "oto", "serve", "http.py"), encoding="utf-8") as f:
            http = f.read()
        assert "engine.PACK_ROUTES.get(route)" in http and "arch-context" not in http.replace("arch-context.", "").split("#: A composed pack")[0], \
            "the HTTP server serves a pack's route by asking the engine, and names none of its own"
    finally:
        core = str(tmp_path / "core")
        _init(core, "oto-core", empty=True)
        code, out = _cli("build", "--project", core)
        assert code == 0, out
        engine = _engine(core)
        assert "arch_context" not in engine.TOOL_BY_NAME and engine.PACK_ROUTES == {} and "arch_context" not in engine.FORWARDABLE, \
            "a project that does not compose the pack never sees its tool"


# ---- the repository files ----

def test_the_repository_files_write_the_architecture_workflow_only_for_a_project_that_composes_the_pack(tmp_path):
    plain = _repo.files("acme", "Acme")
    workflow = os.path.join(".github", "workflows", "oto-architecture.yml")
    assert workflow not in plain and os.path.join(".github", "workflows", "oto-checks.yml") in plain
    assert "ADR-0011" in plain[os.path.join(".github", "workflows", "oto-checks.yml")] and "oto arch impact --files" in plain[os.path.join(".github", "workflows", "oto-checks.yml")], \
        "the checks workflow still posts a decision's impact where the pack is composed, and says why it is quiet elsewhere"
    text = _repo.files("acme", "Acme", architecture=True)[workflow]
    assert text.startswith("name: oto architecture")
    assert "oto pack add https://github.com/Cynergis/oto-registry.git --path packs/architecture" in text, "the workflow installs the pack whose code compiles"
    assert "oto arch compile --project ." in text and '--by "oto architecture"' in text and "github.sha" in text
    assert "github.event.head_commit.author.name != 'oto architecture'" in text, "its own commit never compiles again"
    _init(str(tmp_path / "invoice"), "architecture", repo=True)
    assert os.path.exists(os.path.join(str(tmp_path / "invoice"), workflow))
    _init(str(tmp_path / "shop"), "product", repo=True)
    assert not os.path.exists(os.path.join(str(tmp_path / "shop"), workflow)), "a product's repository has nothing to compile"


# ---- the decision and the documents ----

def test_the_decision_is_recorded_and_accepted_and_the_documents_say_where_everything_went():
    with open(os.path.join(ROOT, "docs", "adr", "0011-a-domain-vocabulary-is-a-pack-of-the-registry.md"), encoding="utf-8") as f:
        record = _adr.parse(f.read())
    assert _adr.problems(record) == [], _adr.problems(record)
    front = record["front"]
    assert front["id"] == "ADR-0011" and front["status"] == "accepted" and set(front["governs"]) == {"workitem.epic-h", "workitem.epic-i"}
    decision = _adr.first_sentence(record["sections"]["Decision"]).lower()
    assert "pack of the registry" in decision and "oto-core" in decision and "exactly one vocabulary" in decision
    for path in FORGETS:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            text = f.read()
        assert "ADR-0011" in text or "0011-a-domain-vocabulary" in text, "%s does not name the decision" % path
        for word in DOMAIN:
            assert not re.search(r"(?<![.~\w/])oto/ontologies/%s\b" % re.escape(word), text) and \
                not re.search(r"\(\.\./oto/ontologies/%s" % re.escape(word), text), "%s still points at oto/ontologies/%s" % (path, word)
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        arch_doc = f.read()
    assert "oto pack add architecture" in arch_doc and "oto_architecture" in arch_doc and "provides.tools" in arch_doc, \
        "the architecture document says the arch command and arch_context are the architecture pack's"
    assert "oto-core" in arch_doc and "no other" in arch_doc
    with open(os.path.join(ROOT, "oto", "extensions.py"), encoding="utf-8") as f:
        assert '"tools"' in f.read()
