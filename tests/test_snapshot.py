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


def _sensitive(root):
    """A snapshot carrying everything a published copy must not: file names, people, their words."""
    s = snapshot.for_root(root)
    s["sources"]["inbox"] = ["salaries-2025.xlsx"]
    s["sources"]["processing"] = ["hr-review.md"]
    s["sources"]["errors"] = [{"file": "Vendor Integration Notes.txt", "reason": "credential: AWS access key id", "run": "r1"}]
    s["sources"]["open_runs"] = ["r2"]
    s["sources"]["waiting"] = {k: len(s["sources"][k]) for k in ("inbox", "processing", "errors", "open_runs")}
    s["survey"]["accepted"], s["survey"]["rejected"] = 1, 1
    s["survey"]["latest"] = [{"term": "Dana Reyes", "verdict": "rejected", "as": None, "by": "Sam Lee", "at": "2025-10-20",
                              "note": "a person"}]
    s["vocabulary"]["classes"] = [{"name": "Bus", "definition": "A vehicle.", "things": 1, "why": "Work orders name one.",
                                   "validated_by": "Dana Reyes, Fleet Manager, 2025-10-20"},
                                  {"name": "Route", "definition": "A line.", "things": 1, "why": None, "validated_by": None}]
    s["rules"]["rules"] = [{"id": "r", "kind": "policy", "severity": "warn", "why": "Stock runs out.", "validated_by": "Dana Reyes"}]
    s["test"]["gold"] = {"questions": 14, "authored_by": "Sam Lee, analyst", "audited_fraction": 0.0}
    s["test"]["feedback"] = [{"id": "fb-0003", "verdict": "wrong", "question": "Is WO-2291 still open?", "by": "Dana Reyes",
                              "at": "2025-10-07", "expected": None, "promoted": False},
                             {"id": "fb-0001", "verdict": "right", "question": "Which garage stocks pads?", "by": "Priya Nair",
                              "at": "2025-10-07", "expected": None, "promoted": False}]
    s["test"]["feedback_counts"], s["test"]["feedback_waiting"] = {"wrong": 1, "right": 1}, 1
    s["open"] = snapshot._open(s)
    s["token"] = snapshot.token(s)
    return s


def test_the_published_snapshot_withholds_files_people_and_their_words_and_keeps_the_counts(root):
    live = _sensitive(root)
    out = snapshot.published(live)
    text = json.dumps(out, ensure_ascii=False)
    for secret in ("salaries-2025.xlsx", "hr-review.md", "Vendor Integration Notes.txt", "AWS", "Dana Reyes", "Sam Lee",
                   "Priya Nair", "Is WO-2291 still open?", "Which garage stocks pads?", "r1", "r2"):
        assert secret not in text, secret
    assert out["published"] is True and live.get("published") is False, "the live one says it is not"
    assert out["sources"]["waiting"] == {"inbox": 1, "processing": 1, "errors": 1, "open_runs": 1}
    assert (out["survey"]["accepted"], out["survey"]["rejected"], out["survey"]["latest"]) == (1, 1, [])
    assert [c["validated_by"] for c in out["vocabulary"]["classes"]] == ["confirmed", None]
    assert out["vocabulary"]["classes"][0]["why"] == "Work orders name one.", "the design's reasons are the product"
    assert out["rules"]["rules"][0]["validated_by"] == "confirmed"
    assert out["test"]["gold"] == {"questions": 14, "authored_by": None, "audited_fraction": 0.0}
    assert out["test"]["feedback"] == [] and out["test"]["feedback_counts"] == {"right": 1, "wrong": 1}
    assert out["withheld"] == sorted(out["withheld"]) and "sources.errors" in out["withheld"] and "test.feedback" in out["withheld"]
    whats = [o["what"] for o in out["open"]]
    assert "1 document could not be read" in whats and "1 reader question waits for its right answer" in whats
    assert out["token"] == snapshot.token(out) and out["token"] != live["token"]
    assert snapshot.published(live) == out, "the same live snapshot gives the same published one"


def test_what_the_published_snapshot_keeps_is_scanned_and_a_credential_refuses_it(root):
    s = _sensitive(root)
    assert snapshot.refusals(snapshot.published(s)) == []
    s["curate"]["changes"] = [{"at": "2025-10-01", "by": "Sam Lee", "note": "key AKIA" + "IOSFODNN7EXAMPLE pasted by mistake",
                               "sources": [], "added": 1, "retired": []}]
    assert snapshot.refusals(snapshot.published(s)), "a credential in a kept note refuses the snapshot"


def test_a_site_built_with_the_workbench_carries_the_published_snapshot(tmp_path):
    root = str(tmp_path / "acme")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="acme", name="Acme", ontology="software-architecture")
    code, out = _cli("build", "--project", root, "--target", "site", "--view", "workbench")
    assert code == 0, out
    site = Project.standard(root).layout.site
    with open(os.path.join(site, "snapshot.json"), encoding="utf-8") as f:
        published = json.load(f)
    assert published["published"] is True and published["project"]["name"] == "Acme"
    assert os.path.exists(os.path.join(site, "data.json")) and os.path.exists(os.path.join(site, "workbench.js"))
    assert "published snapshot" in out
    code, out = _cli("build", "--project", root, "--target", "site")
    assert code == 0 and os.path.exists(os.path.join(site, "snapshot.json")), "the workbench is the default view, and it asks for the snapshot"


def test_the_generated_deploy_workflow_builds_the_site_with_flags_oto_build_accepts():
    from oto import repo
    assert " --app " not in repo.DEPLOY and '--view "${{{{ vars.OTO_SITE_VIEW }}}}"' in repo.DEPLOY


def test_people_the_project_names_are_published_as_their_initials(root):
    live = _sensitive(root)
    live["vocabulary"]["classes"][1]["why"] = "Dana wants work grouped by route; Reyes asked for it twice. Bob agreed."
    live["curate"]["changes"] = [{"at": "2025-10-02", "by": "Sam Lee, analyst", "note": "WO-2304, from Priya Nair's captured statement.",
                                  "sources": [], "added": 1, "retired": []}]
    live["test"]["feedback"][1]["by"] = "Priya Nair, Maintenance Supervisor"
    out = snapshot.published(live)
    assert out["vocabulary"]["classes"][1]["why"] == "D.R. wants work grouped by route; D.R. asked for it twice. Bob agreed.", \
        "a first or last name alone is the person too; a name the project never attributes anything to is left"
    assert out["curate"]["changes"][0]["by"] == "S.L., analyst"
    assert out["curate"]["changes"][0]["note"] == "WO-2304, from P.N.'s captured statement."
    text = json.dumps(out, ensure_ascii=False)
    for name in ("Dana", "Reyes", "Priya", "Nair", "Sam Lee"):
        assert name not in text, name


def test_two_people_with_one_first_name_keep_only_its_initial(root):
    live = _sensitive(root)
    live["rules"]["rules"].append({"id": "r2", "kind": "policy", "severity": "warn", "why": "Dana asked.", "validated_by": "Dana Smith"})
    out = snapshot.published(live)
    assert out["rules"]["rules"][1]["why"] == "D. asked.", "ambiguous between D.R. and D.S."
