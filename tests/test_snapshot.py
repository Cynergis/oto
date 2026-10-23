"""The project snapshot: what the workbench shows, written by the engine in one object. Every surface
renders it and none reads the project's files itself, so they cannot disagree; its token moves when
anything in it does, so an open page knows when to reload."""
import io
import json
import os
import contextlib

import pytest

from oto import snapshot
from oto.cli import main
from oto.project import Project
from oto.scaffold import init


@pytest.fixture
def root(tmp_path):
    path = str(tmp_path / "kb")
    with contextlib.redirect_stdout(io.StringIO()):
        init(path, slug="kb", name="KB")
    return path


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def test_a_new_project_has_every_station_and_nothing_started(root):
    s = snapshot.for_root(root)
    assert s["snapshot"] == snapshot.SNAPSHOT and s["project"] == {"name": "KB", "slug": "kb"}
    assert [st["id"] for st in s["stations"]] == [sid for sid, _ in snapshot.STATIONS]
    assert all(st["state"] in snapshot.STATES and st["line"] for st in s["stations"])
    assert s["overview"]["facts"] == 0 and s["build"]["built"] is False


def test_the_token_is_the_same_for_the_same_project_and_moves_when_it_changes(root):
    first = snapshot.for_root(root)["token"]
    assert snapshot.for_root(root)["token"] == first, "nothing from the clock"
    with open(os.path.join(root, "inbox", "memo.md"), "w", encoding="utf-8") as f:
        f.write("# Memo\n")
    moved = snapshot.for_root(root)
    assert moved["token"] != first and moved["sources"]["inbox"] == ["memo.md"]
    assert {"station": "sources", "what": "1 document waiting in the inbox", "detail": None} in moved["open"]


def test_no_project_no_snapshot(tmp_path):
    assert snapshot.for_root(str(tmp_path)) is None


def test_oto_status_prints_it(root):
    code, out = _cli("status", "--project", root, "--snapshot")
    assert code == 0
    printed = json.loads(out)
    assert printed["snapshot"] == snapshot.SNAPSHOT and printed["token"] == snapshot.for_root(root)["token"]


def test_api_status_serves_it_and_api_changes_names_its_token(tmp_path):
    import urllib.request
    root = str(tmp_path / "claims")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="claims", name="Claims", ontology="auto-claims")
    from oto.builder import build
    from oto.serve import http as _http
    import importlib
    with contextlib.redirect_stdout(io.StringIO()):
        build(Project.standard(root))
    os.environ["OTO_DB"] = Project.standard(root).layout.database
    from oto.serve import engine
    importlib.reload(engine)
    server = _http.Server(engine, "127.0.0.1", 0, app_dir=None, project_root=root, identity={"slug": "claims"}).start()
    try:
        with urllib.request.urlopen(server.url + "/api/status") as r:
            status = json.loads(r.read())
        with urllib.request.urlopen(server.url + "/api/changes") as r:
            changes = json.loads(r.read())
    finally:
        server.stop()
        os.environ.pop("OTO_DB", None)
    assert status["snapshot"]["snapshot"] == snapshot.SNAPSHOT
    assert changes["snapshot_token"] == status["snapshot"]["token"]
