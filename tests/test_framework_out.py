"""A framework is a pack of the registry (ADR-0008); the engine ships none. ADR-0006 made an
architecture framework a pack plus an adapter and ADR-0007 kept the packs that describe the world in
the engine; a framework describes nothing of the world, it is a notation someone else owns, so CALM,
the first, moves to Cynergis/oto-registry as the `calm` pack with its adapter in its code/, reached
through the adapter seam like a pack of the user's. The engine's repository forgets it: no pack, no
module, no fixture, no shipped manifest that provides an adapter, and the documents say where the
framework went and why. What a framework needs from the engine stays: the adapter seam, the
architecture command, the reified model's neutral attributes."""
import contextlib
import io
import json
import os
import re

from oto import extensions
from oto.cli import main
from oto.model import ontologies

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GONE = ("oto/ontologies/calm", "oto/packs/calm.py", "oto/packs/calm", "tests/test_calm_pack.py", "tests/test_arch_calm.py", "tests/fixtures/calm")
FORGETS = ("README.md", "docs/ARCHITECTURE.md", "docs/E2E-TESTING.md", "skills/concierge/SKILL.md", "oto/repo.py", "THIRD-PARTY-LICENSES.md")
ADR = os.path.join(ROOT, "docs", "adr", "0008-a-framework-is-a-pack-of-the-registry.md")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def test_the_engine_s_repository_holds_nothing_of_calm():
    for path in GONE:
        assert not os.path.exists(os.path.join(ROOT, path)), path
    assert "calm" not in ontologies.available()
    shipped = os.path.join(ROOT, "oto", "ontologies")
    for name in sorted(os.listdir(shipped)):
        manifest = os.path.join(shipped, name, "manifest.json")
        if os.path.exists(manifest):
            with open(manifest, encoding="utf-8") as f:
                provides = json.load(f).get("provides") or {}
            assert "adapters" not in provides, "%s provides a framework adapter: a framework is a pack of the registry" % name
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "oto")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".py"):
                with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                    source = f.read()
                imports = "\n".join(l for l in source.splitlines() if l.lstrip().startswith(("from ", "import ")))
                assert "packs.calm" not in imports and "oto_calm" not in imports, os.path.join(dirpath, name)
                assert "calm_" not in source.lower().replace("calm_pack", ""), "%s names a CALM attribute" % os.path.join(dirpath, name)
    assert extensions.adapters() == {}, "a machine with the engine alone has no framework adapter"


def test_import_and_export_without_a_framework_pack_say_so(tmp_path):
    from oto.scaffold import init
    root = str(tmp_path / "invoice")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="invoice", name="Invoice", ontology="architecture")
    code, out = _cli("arch", "import", "--framework", "calm", "--file", "model.json", "--at", "2026-10-29", "--project", root)
    assert code == 1 and "no adapter for framework 'calm'" in out and "none" in out, out
    code, out = _cli("arch", "export", "--project", root)
    assert code == 1 and "--framework" in out, out
    code, out = _cli("arch", "--help")
    assert code == 0 and "import" in out and "export" in out and "migrate" in out and "--framework" in out, "the seam stays: a framework pack plugs in"


def test_the_documents_point_at_the_calm_pack_and_name_the_decision():
    for path in FORGETS:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            text = f.read()
        assert "oto/packs/calm.py" not in text and "oto/ontologies/calm" not in text and "tests/fixtures/calm/" not in text, "%s still points into the engine for CALM" % path
    for path in ("README.md", "docs/ARCHITECTURE.md", "docs/E2E-TESTING.md"):
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            text = f.read()
        assert "0008" in text and ("calm@cynergis" in text or "oto pack add calm" in text or "packs/calm" in text), "%s says where CALM went and why" % path
    with open(os.path.join(ROOT, "kits", "oto-gcp", "files", "home", ".oto", "init.sh"), encoding="utf-8") as f:
        init = f.read()
    assert "Cynergis/oto-registry" in init and "/oto:packs" in init, \
        "the sandbox kit adds the registry, where the calm pack is turned on from the session with the packs skill"
    with open(os.path.join(ROOT, "skills", "packs", "SKILL.md"), encoding="utf-8") as f:
        assert "`calm`" in f.read(), "the packs skill knows the calm pack"


def test_the_engine_s_tests_carry_a_framework_of_their_own(plain_framework):
    """What the core does with a framework's model is tested through the plain adapter under
    tests/fixtures/frameworks, never through CALM."""
    assert set(extensions.adapters()) == {"plain"} and extensions.only_adapter() == "plain"
    adapter = extensions.adapter("plain")
    assert adapter["module"].__file__.startswith(os.path.join(ROOT, "tests", "fixtures", "frameworks", "plain", "code"))
    with open(plain_framework, encoding="utf-8") as f:
        model = json.load(f)
    assert "calm" not in json.dumps(model).lower(), "the fixture is the reified model, named after no framework"
    assert {n["type"] for n in model["proposal"]["nodes"]} >= {"System", "Component", "Relationship", "Control", "Flow", "FlowStep", "Document"}


def test_the_decision_is_recorded_and_accepted():
    with open(ADR, encoding="utf-8") as f:
        text = f.read()
    head = text.split("---")[1]
    assert "id: ADR-0008" in head and "status: accepted" in head and "decided_by: Chiheb Dkhil" in head and "governs: [workitem.epic-h]" in head
    decision = text.split("## Decision")[1].split("## Consequences")[0]
    assert "registry" in decision and "pack" in decision and "adapter" in decision and re.search(r"calm", decision, re.I)
    assert "ships no" in decision or "none" in decision
    with open(os.path.join(ROOT, "roadmap", "graph.json"), encoding="utf-8") as f:
        graph = json.load(f)
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["decision.adr-0008"]["attributes"]["status"] == "accepted" and nodes["decision.adr-0008"].get("evidence")
    assert ("decision.adr-0008", "governs", "workitem.epic-h") in {(e["from"], e["rel"], e["to"]) for e in graph["edges"]}, "ADR-0008 shaped Epic H"
