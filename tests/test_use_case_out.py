"""A use case of the graph lives outside the engine (ADR-0007); the factory is the first. Building
software from the graph is something one does with a knowledge graph, not a knowledge graph, so
the factory (its plugin, the factory-run pack, its code, its tests, its E2E) lives in
Cynergis/oto-factory as a pack that reaches the engine through the seams and a pack's code/, and
the engine's repository forgets it: no folder, no pack, no command, no row, the engine plugin alone
in its marketplace. What a factory needs from the engine stays: the policy snapshot and its reader, the
architecture's measurement; the work pack's verdict event comes with the registry's work pack (ADR-0010)."""
import contextlib
import io
import json
import os
import re

from oto import arch as _arch
from oto.cli import main
from oto.model import ontologies

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GONE = ("factory", "oto/ontologies/factory-run", "oto/packs/factory", "oto/factory.py", "oto/cli/factory.py",
        "tests/test_factory.py", "tests/test_factory_out.py", "tests/test_factory_plugin.py", "tests/test_factory_run.py")
FORGETS = ("README.md", "docs/ARCHITECTURE.md", "docs/E2E-TESTING.md", "skills/concierge/SKILL.md", "oto/cli/__init__.py")
ADR = os.path.join(ROOT, "docs", "adr", "0007-a-use-case-lives-outside-the-engine.md")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def test_the_engine_s_repository_holds_nothing_of_the_factory():
    for path in GONE:
        assert not os.path.exists(os.path.join(ROOT, path)), path
    shipped = os.path.join(ROOT, "oto", "ontologies")
    for name in sorted(os.listdir(shipped)):
        manifest = os.path.join(shipped, name, "manifest.json")
        if os.path.exists(manifest):
            with open(manifest, encoding="utf-8") as f:
                provides = json.load(f).get("provides") or {}
            assert "factory" not in {c["name"] for c in provides.get("commands", [])}, "%s provides a factory command" % name
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "oto")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".py"):
                with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                    imports = "\n".join(l for l in f.read().splitlines() if l.lstrip().startswith(("from ", "import ")))
                assert "packs.factory" not in imports and "oto_factory" not in imports, os.path.join(dirpath, name)


def test_the_marketplace_lists_the_engine_plugin_alone():
    with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8") as f:
        plugins = json.load(f)["plugins"]
    assert [p["name"] for p in plugins] == ["oto"]


def test_the_documents_point_at_the_factory_s_repository_and_name_no_factory_command():
    for path in FORGETS:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            text = f.read()
        assert "oto factory" not in text, "%s still names a factory command" % path
        assert "factory/" not in text.replace(".factory/", ""), "%s still points into a factory folder" % path
    for path in ("README.md", "docs/ARCHITECTURE.md", "docs/E2E-TESTING.md"):
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            text = f.read()
        assert "Cynergis/oto-factory" in text and "0007" in text, "%s says where the factory went and why" % path


def test_what_a_factory_needs_from_the_engine_stays():
    code, out = _cli("--help")
    assert code == 0 and "  work " not in out, "the verdict event is the work pack's, a pack of the registry (ADR-0010)"
    code, out = _cli("policy", "--help")
    assert code == 0 and "snapshot" in out and "denials" in out, out
    code, out = _cli("arch", "--help")
    assert code == 0 and "measure" in out, out
    assert callable(_arch.measure) and callable(_arch.measure_from), "measuring a requirement is the architecture's (H6)"
    assert os.path.exists(os.path.join(ROOT, "hooks", "policy_snapshot.py")), "the reader any guard copies"


def test_the_decision_is_recorded_and_accepted():
    with open(ADR, encoding="utf-8") as f:
        text = f.read()
    head = text.split("---")[1]
    assert "id: ADR-0007" in head and "status: accepted" in head and "decided_by: Chiheb Dkhil" in head and "governs: [workitem.epic-j]" in head
    decision = text.split("## Decision")[1].split("## Consequences")[0]
    assert "repository of its own" in decision and "pack seams" in decision and "registry" in decision and "forgets it" in decision
    assert re.search(r"the factory is the first", decision)
    with open(os.path.join(ROOT, "roadmap", "graph.json"), encoding="utf-8") as f:
        graph = json.load(f)
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["decision.adr-0007"]["attributes"]["status"] == "accepted" and nodes["decision.adr-0007"].get("evidence")
    assert ("decision.adr-0007", "governs", "workitem.epic-j") in {(e["from"], e["rel"], e["to"]) for e in graph["edges"]}, "ADR-0007 shaped Epic J"
