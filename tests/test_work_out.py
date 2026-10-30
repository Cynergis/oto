"""The plan is a pack of the registry (ADR-0010); the engine ships no pack with tools of its own. The
work pack, with communication on it, is the second domain feature to leave: the `work` pack of
Cynergis/oto-registry carries the two ontologies, the commands and the board's status hook in its
code/, the work skill, and the SessionStart hook that opens a session with the inbox. The engine's
repository forgets it: no pack, no ontology, no skill, no hook that names `oto work`, no shipped
manifest that provides a `work` command, and the documents say where the plan went and why. What
the pack needs from the engine stays: the write path (oto/assertion.py), the command and status
seams, `oto decide`, and the roadmap project this repository tracks with the pack."""
import contextlib
import io
import json
import os

from oto import assertion as _assertion, extensions
from oto.cli import main
from oto.model import ontologies

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GONE = ("oto/ontologies/work", "oto/ontologies/communication", "oto/packs/work", "skills/work", ".claude/skills/work",
        "tests/test_work.py", "tests/test_work_remind.py", "tests/scenarios/roadmap")
FORGETS = ("README.md", "docs/ARCHITECTURE.md", "docs/E2E-TESTING.md", "skills/README.md", "skills/concierge/SKILL.md", "roadmap/README.md",
           "oto/cli/__init__.py", "oto/extensions.py", "oto/tracing.py", "hooks/hooks.json")
ADR = os.path.join(ROOT, "docs", "adr", "0010-a-domain-feature-is-a-pack-of-the-registry.md")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def test_the_engine_s_repository_holds_nothing_of_the_work_pack():
    for path in GONE:
        assert not os.path.exists(os.path.join(ROOT, path)), path
    assert not {"work", "communication"} & set(ontologies.available())
    shipped = os.path.join(ROOT, "oto", "ontologies")
    for name in sorted(os.listdir(shipped)):
        manifest = os.path.join(shipped, name, "manifest.json")
        if os.path.exists(manifest):
            with open(manifest, encoding="utf-8") as f:
                provides = json.load(f).get("provides") or {}
            assert not any(c.get("name") == "work" for c in provides.get("commands") or []), "%s provides the work command" % name
            assert not provides.get("status"), "%s provides a status hook: the board was the only one, and it is the pack's" % name
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "oto")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".py"):
                with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                    imports = "\n".join(l for l in f.read().splitlines() if l.lstrip().startswith(("from ", "import ")))
                assert "packs.work" not in imports and "oto_work" not in imports, os.path.join(dirpath, name)
    assert "work" not in {c["name"] for c in extensions.commands()}, "a machine with the engine alone has no work command"


def test_the_write_path_stays_the_engine_s():
    assert _assertion.commit and _assertion.identity and _assertion.gates and _assertion.no_candidate and _assertion.WriteError
    code, out = _cli("--help")
    assert code == 0 and "  work " not in out and "packs:" in out.lower(), out
    code, out = _cli("work", "board", "--project", "somewhere")
    assert code == 2 and "invalid choice" in out and "work" in out, "an unknown command, as argparse says it: the pack brings it"
    code, out = _cli("decide", "--help")
    assert code == 0, "the sign-off and the milestone's state stay the core's: oto decide"


def test_the_plugin_hook_no_longer_names_the_inbox():
    with open(os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8") as f:
        hooks = json.load(f)["hooks"]
    commands = [h["command"] for group in hooks["SessionStart"] for h in group["hooks"]]
    assert any("oto status" in c for c in commands), "the status hook stays"
    assert not any("oto work" in c for c in commands), "the inbox hook is the work pack's own hooks/hooks.json"


def test_the_reminder_workflow_installs_the_pack_beside_the_engine():
    with open(os.path.join(ROOT, ".github", "workflows", "oto-remind.yml"), encoding="utf-8") as f:
        text = f.read()
    assert "schedule:" in text and "cron:" in text and "workflow_dispatch:" in text
    assert "oto pack add https://github.com/Cynergis/oto-registry.git --path packs/work" in text, "oto work remind needs the pack"
    assert text.index("oto pack add") < text.index("oto work remind --at"), "the pack is installed before the step that runs it"
    assert "oto work remind" in text and "--project roadmap" in text and "gh pr create" in text


def test_the_documents_point_at_the_work_pack_and_name_the_decision():
    for path in FORGETS:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            text = f.read()
        assert "oto/packs/work" not in text and "oto/ontologies/work" not in text and "oto/ontologies/communication" not in text \
            and "packs.work" not in text and "skills/work/" not in text, "%s still points into the engine for the plan" % path
    for path in ("docs/ARCHITECTURE.md", "docs/E2E-TESTING.md", "roadmap/README.md", "skills/README.md"):
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            text = f.read()
        assert "0010" in text and ("work@cynergis" in text or "oto pack add work" in text or "packs/work" in text), "%s says where the plan went and why" % path
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "oto work remind" in text and "OTO_PRINCIPAL" in text and "oto_work" in text and "assertion.py" in text and "status snapshot" in text, \
        "the architecture document keeps the row, pointing at the registry's pack, and the write path it rests on"
    with open(os.path.join(ROOT, "docs", "E2E-TESTING.md"), encoding="utf-8") as f:
        e2e = f.read()
    assert "## 31." in e2e and "oto work remind" in e2e and "OTO_PRINCIPAL" in e2e and "phase 6" in e2e.lower()
    with open(os.path.join(ROOT, "skills", "packs", "SKILL.md"), encoding="utf-8") as f:
        assert "`work`" in f.read(), "the packs skill knows the work pack"


def test_the_roadmap_stays_here_and_phase_6_is_reached():
    with open(os.path.join(ROOT, "roadmap", "graph.json"), encoding="utf-8") as f:
        graph = json.load(f)
    phase6 = next(n for n in graph["nodes"] if n["id"] == "milestone.phase-6")
    assert phase6["attributes"]["state"] == "reached" and any(s.startswith("assertion:") for s in phase6.get("sources") or []), \
        "a named person decided it, under the gates"
    with open(os.path.join(ROOT, "roadmap", "project.config.json"), encoding="utf-8") as f:
        config = json.load(f)
    assert config["ontology"]["name"] == "communication", "the roadmap composes the pack's vocabulary, its own copy in the project"
    with open(ADR, encoding="utf-8") as f:
        head = f.read().split("---")[1]
    assert "workitem.epic-m" in head and "workitem.epic-n" in head, "the decision governs the plan's epics"
    edges = {(e["from"], e["rel"], e["to"]) for e in graph["edges"]}
    assert ("decision.adr-0010", "governs", "workitem.epic-m") in edges and ("decision.adr-0010", "governs", "workitem.epic-n") in edges
