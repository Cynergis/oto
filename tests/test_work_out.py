"""Work and communication out (ADR-0006, step 5). What the work pack owned splits in two: the engine's
write path, a named person's assertion through the gates (oto/assertion.py: commit, identity, gates),
which decide, the graph descriptors, publish, curate and ingest use; and the pack's own code, the
work items, the board, messages, the inbox and reminders (oto/packs/work), which reaches the engine
only through the pack's manifest: its command, and a status hook that puts the board in the project's
status snapshot."""
import contextlib
import io
import json
import os

from oto import assertion as _assertion, extensions, snapshot as _snapshot
from oto.cli import main
from oto.model import ontologies
from oto.packs import work as _work
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GONE = ("oto/work.py", "oto/cli/work.py")
ENGINE = ("oto/decide.py", "oto/graphs.py", "oto/publish.py", "oto/snapshot.py", "oto/cli/curate.py", "oto/cli/ingest.py", "oto/cli/graphs.py",
          "oto/cli/__init__.py", "oto/builder.py", "oto/serve/engine.py", "oto/assertion.py")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _project(tmp_path, ontology, slug):
    root = str(tmp_path / slug)
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug=slug, name=slug.title(), ontology=ontology)
    return root


def test_the_write_path_is_the_engine_s_and_the_pack_s_code_is_behind_the_pack():
    for path in GONE:
        assert not os.path.exists(os.path.join(ROOT, path)), path
    for name in ("__init__.py", "cli.py"):
        assert os.path.exists(os.path.join(ROOT, "oto", "packs", "work", name)), name
    for path in ENGINE:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            code = "\n".join(l for l in f.read().splitlines() if not l.lstrip().startswith(("#", '"')))
        assert "packs.work" not in code and "import work" not in code and "work as _work" not in code, path
    assert _assertion.commit and _assertion.identity and _assertion.gates and _assertion.no_candidate and _assertion.WriteError
    assert _work.WorkError is _assertion.WriteError, "the pack's refusal is the engine's"
    assert _work.set_state and _work.board and _work.inbox and _work.remind and _work.status
    provides = ontologies.manifest_for("work")["provides"]
    assert provides["commands"] == [{"name": "work", "module": "oto.packs.work.cli", "label": "work and communication"}]
    assert provides["status"] == ["oto.packs.work:status"]
    assert "provides" not in ontologies.manifest_for("communication") or not ontologies.manifest_for("communication")["provides"], \
        "the communication pack extends work and brings no code of its own: its commands are `oto work notify`, `inbox`, `reply`, `remind`"


def test_the_board_reaches_the_status_through_the_pack_s_hook_and_a_project_without_the_pack_has_none(tmp_path):
    plan = _project(tmp_path, "work", "plan")
    code, out = _cli("build", "--project", plan)
    assert code == 0, out
    project = Project.standard(plan)
    hooks = extensions.status_hooks(project)
    assert [h.__name__ for h in hooks] == ["status"]
    s = _snapshot.snapshot(project) if hasattr(_snapshot, "snapshot") else _snapshot.build(project)
    assert "work" in s and set(s["work"]) >= {"open", "blocked", "deployed", "counts"}, "the board, under the key the pack chooses"
    code, out = _cli("work", "board", "--project", plan)
    assert code == 0 and "item(s)" in out, out
    plain = _project(tmp_path, "data", "plain")
    code, out = _cli("build", "--project", plain)
    assert code == 0, out
    assert extensions.status_hooks(Project.standard(plain)) == []
    s = _snapshot.snapshot(Project.standard(plain)) if hasattr(_snapshot, "snapshot") else _snapshot.build(Project.standard(plain))
    assert "work" not in s, "no pack, no board"


def test_decide_and_a_graph_describing_itself_write_through_the_engine_s_path(tmp_path):
    plan = _project(tmp_path, "work", "plan")
    code, out = _cli("build", "--project", plan)
    assert code == 0, out
    project = Project.standard(plan)
    with open(project.ontology_config_path, encoding="utf-8") as f:
        decisions = [(cls, name) for cls, attrs in (json.load(f).get("attributes") or {}).items() for name, spec in attrs.items() if spec.get("decision")]
    assert decisions, "the work pack has a decision attribute to try"
    from oto import audit as _audit
    from oto.curate import session as _session
    item = next(n["id"] for n in _session.live(project)["nodes"] if n["type"] == "WorkItem")
    done = _assertion.commit(project, "Ada looked at the item and found nothing to change", "Ada", "2026-10-28", [item], lambda candidate, source: {}, action="assert")
    assert done["assertion"].startswith("a-"), "the assertion is recorded even when the edit changes nothing"
    record = _audit.read(project)[-1]
    assert record["action"] == "assert" and record["principal"] == "Ada" and record["decision"] == "applied" and item in record["nodes"]
    code, out = _cli("curate", "start", "--project", plan)
    assert code == 0
    try:
        _assertion.commit(project, "a second word while a candidate is open", "Ada", "2026-10-28", [item], lambda candidate, source: {}, action="assert")
    except _assertion.WriteError as refused:
        assert "candidate is open" in str(refused)
    else:
        raise AssertionError("a write while a candidate is open is refused")
    _cli("curate", "abort", "--project", plan)
    identity = _assertion.identity(project)
    assert identity is None or isinstance(identity, str)


def test_the_docs_point_at_the_pack_and_the_assertion_module():
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "packs/work" in text and "assertion.py" in text and "../oto/work.py" not in text
    assert "`status`" in text and "status snapshot" in text
