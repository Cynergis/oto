"""Ingest runs: claim, extract, fail visibly, archive only once the graph holds the facts."""
import json
import os
import tempfile

import pytest

from oto.cli import main
from oto.intake import pipeline
from oto.project import Project
from oto.scaffold import init

VOCAB = {"classes": {"Thing": "a thing"}, "properties": {"near": ["Thing", "Thing", None, "close"]},
         "temporal": {}}
NODE = {"id": "t.1", "type": "Thing", "label": "One", "aliases": [], "summary": "s", "attributes": {},
        "tags": [], "as_of": "2026-01-01", "valid_from": "2026-01-01", "source_doc": "a",
        "status": "current", "sources": ["a"]}


def _project(root):
    init(root, slug="kb", name="KB")
    with open(os.path.join(root, "ontology.config.json"), "w", encoding="utf-8") as f:
        json.dump(VOCAB, f)
    with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
        json.dump({"nodes": [NODE], "edges": []}, f)
    return Project.standard(root)


def _drop(project, name, text):
    with open(os.path.join(project.layout.inbox, name), "w", encoding="utf-8") as f:
        f.write(text)


def _names(directory):
    return sorted(n for n in os.listdir(directory) if not n.startswith(".")) if os.path.isdir(directory) else []


# ---- claim and extract ----

def test_a_run_claims_the_inbox_and_leaves_successes_in_processing():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _drop(project, "a.md", "# A\n\nText.\n")
        _drop(project, "b.md", "# B\n\nMore.\n")
        result = pipeline.ingest(project)
        layout = project.layout
        assert _names(layout.inbox) == []
        assert _names(layout.processing) == ["a.md", "b.md"]
        assert _names(layout.archive) == []
        assert sorted(result["written"]) == ["a", "b"]
        assert os.path.exists(os.path.join(layout.corpus, "a.md"))


def test_the_manifest_records_every_file_with_its_hash_and_outcome():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _drop(project, "a.md", "# A\n")
        _drop(project, "weird.xyz", "?")
        result = pipeline.ingest(project)
        manifest = json.load(open(result["manifest"], encoding="utf-8"))
        assert manifest["run_id"] == result["run_id"] and manifest["completed"] is False
        by_name = {e["file"]: e for e in manifest["files"]}
        assert by_name["a.md"]["outcome"] == pipeline.EXTRACTED and by_name["a.md"]["slug"] == "a"
        assert len(by_name["a.md"]["sha256"]) == 64
        assert by_name["weird.xyz"]["outcome"] == pipeline.UNSUPPORTED
        assert manifest["summary"][pipeline.EXTRACTED] == 1


def test_a_failure_moves_the_file_to_errors_with_the_reason_beside_it():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _drop(project, "weird.xyz", "?")
        _drop(project, "secret.md", "# Keys\n\nSIN on file: 046 454 286\n")
        result = pipeline.ingest(project)
        errors = os.path.join(project.layout.errors, result["run_id"])
        assert _names(project.layout.processing) == []
        assert sorted(_names(errors)) == ["secret.md", "secret.md.error.json",
                                          "weird.xyz", "weird.xyz.error.json"]
        blocked = json.load(open(os.path.join(errors, "secret.md.error.json"), encoding="utf-8"))
        assert blocked["outcome"] == pipeline.BLOCKED and "046454286" not in json.dumps(blocked)
        unsupported = json.load(open(os.path.join(errors, "weird.xyz.error.json"), encoding="utf-8"))
        assert "no extractor" in unsupported["reason"]
        assert not os.path.exists(os.path.join(project.layout.corpus, "secret.md"))


def test_leftovers_in_processing_are_claimed_again_and_a_name_clash_stays_in_the_inbox():
    """Re-running is the recovery from a crash: extraction is idempotent."""
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        layout = project.layout
        os.makedirs(layout.processing, exist_ok=True)
        with open(os.path.join(layout.processing, "left.md"), "w") as f:
            f.write("# Left\n")
        _drop(project, "left.md", "# Newer\n")
        _drop(project, "fresh.md", "# Fresh\n")
        result = pipeline.ingest(project)
        assert sorted(result["written"]) == ["fresh", "left"]
        assert result["collisions"] == ["left.md"]
        assert _names(layout.inbox) == ["left.md"]
        assert open(os.path.join(layout.corpus, "left.md"), encoding="utf-8").read() == "# Left\n"


def test_an_external_inbox_is_copied_and_left_untouched():
    """Pointing --inbox at a folder of originals must never empty it."""
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as originals:
        project = _project(root)
        with open(os.path.join(originals, "a.md"), "w") as f:
            f.write("# A\n")
        result = pipeline.ingest(project, inbox=originals)
        assert result["written"] == ["a"]
        assert _names(originals) == ["a.md"], "the originals were moved"
        assert _names(project.layout.processing) == ["a.md"]
        manifest = json.load(open(result["manifest"], encoding="utf-8"))
        assert manifest["copied"] is True and manifest["inbox"] == os.path.abspath(originals)


def test_a_second_run_cannot_start_while_one_holds_the_lock():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        os.makedirs(project.layout.processing, exist_ok=True)
        with pipeline.Lock(project.layout.processing, "held"):
            with pytest.raises(pipeline.IngestLocked):
                pipeline.ingest(project)
        pipeline.ingest(project)          # released on exit


def test_two_runs_in_one_second_get_distinct_ids(tmp_path):
    first = pipeline.new_run_id(str(tmp_path))
    open(tmp_path / (first + ".json"), "w").close()
    second = pipeline.new_run_id(str(tmp_path))
    assert first != second and second.startswith(first)


# ---- complete ----

def _ingest_and_build(project, name="a.md", text="# A\n\nText.\n"):
    _drop(project, name, text)
    result = pipeline.ingest(project)
    root = os.path.dirname(project.src)
    assert main(["build", "--project", root]) == 0
    return result["run_id"]


def test_complete_refuses_until_the_graph_holds_the_run():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _drop(project, "a.md", "# A\n")
        run_id = pipeline.ingest(project)["run_id"]
        with pytest.raises(pipeline.NotReady, match="no build"):
            pipeline.complete(project, run_id)
        assert main(["build", "--project", root]) == 0
        assert main(["curate", "start", "--project", root]) == 0
        with pytest.raises(pipeline.NotReady, match="candidate is open"):
            pipeline.complete(project, run_id)
        assert main(["curate", "abort", "--project", root]) == 0
        # The build must postdate the run's documents.
        doc = os.path.join(project.layout.corpus, "a.md")
        later = os.path.getmtime(project.layout.database) + 10
        os.utime(doc, (later, later))
        with pytest.raises(pipeline.NotReady, match="predates"):
            pipeline.complete(project, run_id)
        pipeline.complete(project, run_id, force=True)
        assert _names(project.layout.archive) == ["a.md"]


def test_complete_archives_and_closes_the_run():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        run_id = _ingest_and_build(project)
        assert [m["run_id"] for m in pipeline.open_runs(project)] == [run_id]
        result = pipeline.complete(project)
        assert result["run_id"] == run_id and result["archived"] == ["a.md"]
        assert _names(project.layout.processing) == [] and _names(project.layout.archive) == ["a.md"]
        assert pipeline.open_runs(project) == []
        manifest = [m for m in pipeline.runs(project) if m["run_id"] == run_id][0]
        assert manifest["completed"] is True
        index = json.load(open(os.path.join(project.layout.runs, "index.json"), encoding="utf-8"))
        assert index["a.md"]["run_id"] == run_id and index["a.md"]["slug"] == "a"
        with pytest.raises(pipeline.NotReady, match="already complete"):
            pipeline.complete(project, run_id)


def test_a_new_version_of_an_archived_document_is_flagged_and_kept_apart():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _ingest_and_build(project, "a.md", "# A\n\nVersion one.\n")
        pipeline.complete(project)
        _drop(project, "a.md", "# A\n\nVersion two.\n")
        result = pipeline.ingest(project)
        assert result["new_versions"] == ["a.md"]
        manifest = json.load(open(result["manifest"], encoding="utf-8"))
        assert "previous_sha256" in manifest["files"][0]
        assert main(["build", "--project", root]) == 0
        # The graph cites `a`; nobody has re-attested that fact against version two, so the run
        # cannot close. Forcing it is the maintainer's call; the normal path re-attests first.
        with pytest.raises(pipeline.NotReady, match="re-attested"):
            pipeline.complete(project)
        done = pipeline.complete(project, force=True)
        assert done["versioned"] == ["a.md"]
        assert sorted(_names(project.layout.archive)) == sorted(["a.md", done["run_id"]])
        assert _names(os.path.join(project.layout.archive, done["run_id"])) == ["a.md"]


def test_an_identical_re_ingest_does_not_duplicate_the_archive():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _ingest_and_build(project)
        pipeline.complete(project)
        _drop(project, "a.md", "# A\n\nText.\n")
        run_id = pipeline.ingest(project)["run_id"]
        assert main(["build", "--project", root]) == 0
        done = pipeline.complete(project, run_id)
        assert done["archived"] == ["a.md"] and done["versioned"] == []
        assert _names(project.layout.archive) == ["a.md"]


# ---- through the command line, and status ----

def test_cli_run_complete_and_runs(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _drop(project, "a.md", "# A\n")
        assert main(["ingest", "--project", root]) == 0
        assert main(["ingest", "complete", "--project", root]) == 1
        assert "not ready" in capsys.readouterr().err
        assert main(["build", "--project", root]) == 0
        assert main(["ingest", "complete", "--project", root]) == 0
        assert "processing/ is empty" in capsys.readouterr().out
        assert main(["ingest", "runs", "--project", root]) == 0
        assert "complete" in capsys.readouterr().out


def test_status_points_at_complete_when_the_graph_holds_the_run():
    from oto.cli.status import gather

    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _ingest_and_build(project)
        s = gather(project)
        assert s["processing"] == 1 and s["open_runs"]
        assert s["next"].startswith("oto ingest complete")
        pipeline.complete(project)
        assert gather(project)["processing"] == 0


def test_runs_open_prints_only_open_run_ids(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        run_id = _ingest_and_build(project)
        capsys.readouterr()
        assert main(["ingest", "runs", "--project", root, "--open"]) == 0
        assert capsys.readouterr().out.strip() == run_id
        pipeline.complete(project)
        assert main(["ingest", "runs", "--project", root, "--open"]) == 0
        assert capsys.readouterr().out.strip() == ""
