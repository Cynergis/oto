"""The guardrails of the guardrailed route (docs/plans/graph-journeys.md, phase 3).

A change drafted from transcripts merges on its own when five guardrails hold on its fact-level
diff: additive only, cited and attributed as the speaker's assertions, in scope, clean, bounded.
One fails: the route moves to reviewed with the finding posted, and a person decides."""
import contextlib
import io
import json
import os
import tempfile

from oto import route
from oto.cli import main
from oto.curate import assertions, session

from test_curate import _node, _project
from test_route import _commit, _git

SETTINGS = {"from": "inbox/transcripts", "classes": ["Claim"], "max_facts": 3, "additive_only": True, "attributed": True}


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def _configure(project, settings=SETTINGS):
    with open(project.config_path, encoding="utf-8") as f:
        config = json.load(f)
    config["routes"] = {"guardrailed": dict(settings)}
    with open(project.config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def _manifest(project, run_id, folder="inbox/transcripts", files=None, strict=True, completed=False):
    os.makedirs(project.layout.runs, exist_ok=True)
    with open(os.path.join(project.layout.runs, run_id + ".json"), "w", encoding="utf-8") as f:
        json.dump({"run_id": run_id, "started": "2026-11-02T10:00:00", "inbox": os.path.join(project.data, *folder.split("/")),
                   "strict_privacy": strict, "files": files or [{"file": "standup.md", "sha256": "abc123", "outcome": "extracted", "slug": "standup"}],
                   "completed": completed}, f)


def _repository(root, settings=SETTINGS):
    project = _project(root)
    _configure(project, settings)
    _git(root, "init", "-q", "-b", "main")
    return project, _commit(root, "the project")


DANA = assertions.content_id("Dana Ortiz", "2026-11-02", "the data platform is blocked on the platform team")


def _assert(project, by="Dana Ortiz", text="the data platform is blocked on the platform team"):
    code, out = _cli("curate", "assert", "--by", by, "--at", "2026-11-02", "--text", text, "--project", project.data)
    assert code == 0, out
    return out.split()[1]           # "recorded a-<its id>"


def _fact(nid, assertion=DANA, **over):
    base = dict(source_type="human_assertion", sources=["assertion:%s" % assertion, "standup"], source_doc="standup", summary="a statement")
    base.update(over)
    return _node(nid, **base)


def _apply(project, nodes, edges=(), mutate=None):
    session.start(project)
    candidate = session.candidate(project)
    candidate["nodes"].extend(nodes)
    candidate["edges"].extend(edges)
    if mutate:
        mutate(candidate)
    with open(session.candidate_path(project), "w", encoding="utf-8") as f:
        json.dump(candidate, f)
    code, out = _cli("curate", "apply", "--project", project.data, "--by", "oto pipeline", "--note", "the standup", "--force")
    assert code == 0, out


def test_a_transcript_change_that_holds_the_five_guardrails_merges_on_its_own():
    with tempfile.TemporaryDirectory() as root:
        project, base = _repository(root)
        _manifest(project, "20261102-1")
        _assert(project)
        _apply(project, [_fact("c.2")])
        head = _commit(root, "oto author: the standup")
        result = route.guardrails(root, base, head)
        assert result["ok"], result
        assert [g["name"] for g in result["guardrails"]] == ["additive", "attributed", "scope", "clean", "bounded"]
        assert all(g["ok"] for g in result["guardrails"]), result["guardrails"]
        verdict = route.check(root, base, head, authors=["oto pipeline"], verified=True)
        assert verdict["ok"] and verdict["route"] == route.GUARDRAILED, verdict
        assert any("five guardrails" in r for r in verdict["reasons"]), verdict["reasons"]
        code, out = _cli("route", "guardrails", "--base", base, "--head", head, "--project", root)
        assert code == 0 and "guardrails: pass" in out and "attributed" in out, out
        code, out = _cli("route", "check", "--base", base, "--head", head, "--author", "oto pipeline", "--verified", "--project", root)
        assert code == 0 and "route: guardrailed" in out, out


def _failing(root, prepare, mutate=None, nodes=None, edges=(), settings=SETTINGS):
    """A transcript change with one thing wrong; returns the guardrails result and the gate's verdict."""
    project, base = _repository(root, settings)
    extra = prepare(project) if prepare else None
    _manifest(project, "20261102-1", **(extra or {}))
    _assert(project)
    _apply(project, nodes if nodes is not None else [_fact("c.2")], edges=edges, mutate=mutate)
    head = _commit(root, "oto author: the standup")
    return route.guardrails(root, base, head), route.check(root, base, head, authors=["oto pipeline"], verified=True)


def _only(result, name):
    failed = [g["name"] for g in result["guardrails"] if not g["ok"]]
    assert failed == [name], (failed, result["guardrails"])
    return [g for g in result["guardrails"] if g["name"] == name][0]["detail"]


def test_additive_only_a_fact_changed_or_retired_goes_to_a_person():
    with tempfile.TemporaryDirectory() as root:
        def rename(candidate):
            [n for n in candidate["nodes"] if n["id"] == "c.1"][0]["summary"] = "a transcript rewrote it"
        result, verdict = _failing(root, None, mutate=rename)
        detail = _only(result, "additive")
        assert "c.1" in detail and "changed" in detail, detail
        assert not verdict["ok"] and verdict["route"] == route.REVIEWED and verdict["proposed"] == route.GUARDRAILED
        assert any("additive" in r for r in verdict["reasons"]), verdict["reasons"]
    with tempfile.TemporaryDirectory() as root:
        def retire(candidate):
            old = [n for n in candidate["nodes"] if n["id"] == "c.1"][0]
            old.update(status="superseded", valid_to="2026-11-02", superseded_by="c.2")
        result, _verdict = _failing(root, None, mutate=retire, nodes=[_fact("c.2", supersedes="c.1", valid_from="2026-11-02", change_note="restated")])
        assert "superseded" in _only(result, "additive")


def test_cited_and_attributed_a_fact_that_is_not_the_speakers_assertion_goes_to_a_person():
    with tempfile.TemporaryDirectory() as root:
        result, verdict = _failing(root, None, nodes=[_node("c.2", sources=["standup"], source_doc="standup")])
        detail = _only(result, "attributed")
        assert "c.2" in detail and "assertion" in detail, detail
        assert not verdict["ok"] and verdict["route"] == route.REVIEWED
    with tempfile.TemporaryDirectory() as root:
        # an assertion, but citing no transcript document of the run
        result, _verdict = _failing(root, None, nodes=[_fact("c.2", sources=["assertion:" + DANA], source_doc=None)])
        assert "transcript" in _only(result, "attributed")


def test_in_scope_a_class_outside_the_list_or_a_touched_vocabulary_goes_to_a_person():
    with tempfile.TemporaryDirectory() as root:
        result, _verdict = _failing(root, None, nodes=[_fact("p.2", type="Party")])
        detail = _only(result, "scope")
        assert "Party" in detail and "Claim" in detail, detail
    with tempfile.TemporaryDirectory() as root:
        def widen(project):
            with open(project.ontology_config_path, encoding="utf-8") as f:
                vocab = json.load(f)
            vocab["classes"]["Meeting"] = {"definition": "a meeting"}
            with open(project.ontology_config_path, "w", encoding="utf-8") as f:
                json.dump(vocab, f)
        result, _verdict = _failing(root, widen)
        assert "vocabulary" in _only(result, "scope")


def test_clean_a_run_without_the_strict_privacy_scan_or_a_transcript_already_ingested_goes_to_a_person():
    with tempfile.TemporaryDirectory() as root:
        result, _verdict = _failing(root, lambda project: {"strict": False})
        assert "strict" in _only(result, "clean")
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _configure(project)
        _manifest(project, "20261101-9", files=[{"file": "standup-old.md", "sha256": "abc123", "outcome": "extracted", "slug": "standup-old"}], completed=True)
        _git(root, "init", "-q", "-b", "main")
        base = _commit(root, "the project, one run already")
        _manifest(project, "20261102-1")
        _assert(project)
        _apply(project, [_fact("c.2")])
        head = _commit(root, "oto author: the same transcript again")
        result = route.guardrails(root, base, head)
        detail = _only(result, "clean")
        assert "abc123"[:8] in detail and "20261101-9" in detail, detail


def test_bounded_more_facts_than_the_limit_go_to_a_person():
    with tempfile.TemporaryDirectory() as root:
        nodes = [_fact("c.%d" % i) for i in range(2, 6)]
        result, verdict = _failing(root, None, nodes=nodes)
        detail = _only(result, "bounded")
        assert "4" in detail and "3" in detail, detail
        assert verdict["route"] == route.REVIEWED and route.check(root, base_of(root), "HEAD", authors=["x"], verified=True, approved=True)["ok"]


def base_of(root):
    return _git(root, "rev-list", "--max-parents=0", "HEAD")


def test_without_guardrail_settings_there_is_nothing_to_run_and_a_person_reviews():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _git(root, "init", "-q", "-b", "main")
        base = _commit(root, "the project")
        code, out = _cli("route", "guardrails", "--base", base, "--project", root)
        assert code == 1 and "routes" in out and "guardrailed" in out, out


def test_status_says_the_route_settings_and_the_ingest_manifest_records_the_privacy_mode(capsys):
    from oto.intake import pipeline
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _configure(project)
        assert main(["status", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "routes" in out and "inbox/transcripts" in out and "Claim" in out and "3" in out, out
        os.makedirs(os.path.join(root, "inbox", "transcripts"), exist_ok=True)
        with open(os.path.join(root, "inbox", "transcripts", "standup.md"), "w", encoding="utf-8") as f:
            f.write("# Standup\n\nDana: the data platform is blocked on the platform team.\n")
        result = pipeline.ingest(project, inbox=os.path.join(root, "inbox", "transcripts"), strict_privacy=True)
        with open(result["manifest"], encoding="utf-8") as f:
            manifest = json.load(f)
        assert manifest["strict_privacy"] is True and manifest["allow_personal_data"] is False
        assert manifest["files"][0]["sha256"] and manifest["files"][0]["outcome"] == "extracted"


def test_curate_check_refuses_a_plain_fact_while_a_transcript_run_is_open():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _configure(project)
        _manifest(project, "20261102-1")
        session.start(project)
        candidate = session.candidate(project)
        candidate["nodes"].append(_node("c.2", sources=["standup"], source_doc="standup"))
        with open(session.candidate_path(project), "w", encoding="utf-8") as f:
            json.dump(candidate, f)
        code, out = _cli("curate", "check", "--project", root)
        assert code == 1 and "c.2" in out and "assertion" in out and "transcript" in out, out
        _assert(project)
        candidate["nodes"][-1] = _fact("c.2")
        with open(session.candidate_path(project), "w", encoding="utf-8") as f:
            json.dump(candidate, f)
        code, out = _cli("curate", "check", "--project", root)
        assert code == 0, out


def test_the_guardrails_are_the_bases_so_a_transcript_change_cannot_raise_its_own_limit():
    with tempfile.TemporaryDirectory() as root:
        project, base = _repository(root)                                       # max_facts 3, on main
        _manifest(project, "20261102-1")
        _assert(project)
        _configure(project, dict(SETTINGS, max_facts=100))                      # the change raises it for itself
        _apply(project, [_fact("c.%d" % i) for i in range(2, 6)])
        head = _commit(root, "oto author: the standup, and a higher limit")
        result = route.guardrails(root, base, head)
        detail = _only(result, "bounded")
        assert "4" in detail and "3" in detail, "the base's limit holds: " + detail
        verdict = route.check(root, base, head, authors=["oto pipeline"], verified=True)
        assert verdict["route"] == route.REVIEWED and any("policy" in r for r in verdict["reasons"]), verdict["reasons"]
