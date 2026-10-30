"""A domain feature is a pack of the registry (ADR-0010); the engine ships no pack with tools of its
own. ADR-0006 made a domain feature a pack plus its tools and ADR-0008 left open whether the engine
keeps shipping the packs that describe the world; the engine answered wrongly by shipping four with
code of their own, listed under "packs" on every machine. The domain model, ddd, leaves first: the
`ddd` pack of Cynergis/oto-registry carries the ontology, the storming importer and the `ddd` command
in its code/, reached through the command seam like a pack of the user's. The engine's repository
forgets it: no pack, no ontology, no module, no shipped manifest that provides a `ddd` command, and
the documents say where the domain model went and why. What the pack needs from the engine stays: the
command seam, `oto decide`, the capture schema, the `architecture` pack it sits on."""
import contextlib
import io
import json
import os
import re

from oto import extensions
from oto.cli import main
from oto.model import ontologies

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GONE = ("oto/ontologies/ddd", "oto/packs/ddd", "tests/test_ddd_architecture.py")
FORGETS = ("README.md", "docs/ARCHITECTURE.md", "docs/E2E-TESTING.md", "skills/concierge/SKILL.md", "oto/cli/__init__.py", "oto/model/lock.py")
ADR = os.path.join(ROOT, "docs", "adr", "0010-a-domain-feature-is-a-pack-of-the-registry.md")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def test_the_engine_s_repository_holds_nothing_of_ddd():
    for path in GONE:
        assert not os.path.exists(os.path.join(ROOT, path)), path
    assert "ddd" not in ontologies.available()
    shipped = os.path.join(ROOT, "oto", "ontologies")
    for name in sorted(os.listdir(shipped)):
        manifest = os.path.join(shipped, name, "manifest.json")
        if os.path.exists(manifest):
            with open(manifest, encoding="utf-8") as f:
                provides = json.load(f).get("provides") or {}
            assert not any(c.get("name") == "ddd" for c in provides.get("commands") or []), "%s provides the ddd command: the domain model is a pack of the registry" % name
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "oto")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".py"):
                with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                    imports = "\n".join(l for l in f.read().splitlines() if l.lstrip().startswith(("from ", "import ")))
                assert "packs.ddd" not in imports and "oto_ddd" not in imports, os.path.join(dirpath, name)
    assert "ddd" not in {c["name"] for c in extensions.commands()}, "a machine with the engine alone has no ddd command"


def test_the_command_line_has_no_ddd_without_the_pack():
    code, out = _cli("--help")
    assert code == 0 and "  ddd " not in out and "packs:" in out.lower(), out
    code, out = _cli("ddd", "storm", "--from", "board.json", "--at", "2026-10-30")
    assert code == 2 and "invalid choice" in out and "ddd" in out, "an unknown command, as argparse says it: the pack brings it"
    code, out = _cli("decide", "--help")
    assert code == 0 and "attribute=value" in out or "readiness" in out, "the sign-off stays the core's: oto decide"


def test_the_documents_point_at_the_ddd_pack_and_name_the_decision():
    for path in FORGETS:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            text = f.read()
        assert "oto/packs/ddd" not in text and "oto/ontologies/ddd" not in text and "packs.ddd" not in text, "%s still points into the engine for ddd" % path
    for path in ("README.md", "docs/ARCHITECTURE.md", "docs/E2E-TESTING.md"):
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            text = f.read()
        assert "0010" in text and ("ddd@cynergis" in text or "oto pack add ddd" in text or "packs/ddd" in text), "%s says where the domain model went and why" % path
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "oto ddd storm" in text and "oto decide" in text and "oto_ddd" in text, "the architecture document keeps the row, pointing at the registry's pack"
    with open(os.path.join(ROOT, "skills", "packs", "SKILL.md"), encoding="utf-8") as f:
        assert "`ddd`" in f.read(), "the packs skill knows the ddd pack"


def test_the_decision_is_recorded_and_accepted():
    with open(ADR, encoding="utf-8") as f:
        text = f.read()
    head = text.split("---")[1]
    assert "id: ADR-0010" in head and "status: accepted" in head and "decided_by: Chiheb Dkhil" in head
    assert re.search(r"governs: \[.*workitem\.epic-i.*\]", head), "the domain model's epic"
    for epic in ("workitem.epic-c", "workitem.epic-e", "workitem.epic-m", "workitem.epic-n"):
        assert epic in head, "the epics whose packs follow are governed too: %s" % epic
    decision = text.split("## Decision")[1].split("## Consequences")[0]
    assert "registry" in decision and "pack" in decision and "code/" in decision and "ddd" in decision
    assert "ships no" in decision
    with open(os.path.join(ROOT, "roadmap", "graph.json"), encoding="utf-8") as f:
        graph = json.load(f)
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["decision.adr-0010"]["attributes"]["status"] == "accepted" and nodes["decision.adr-0010"].get("evidence")
    edges = {(e["from"], e["rel"], e["to"]) for e in graph["edges"]}
    assert ("decision.adr-0010", "governs", "workitem.epic-i") in edges, "ADR-0010 shaped Epic I"
