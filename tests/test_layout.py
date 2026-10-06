"""The layout separates authored from generated, so the build directory is safe to delete."""
import json
import os
import tempfile

import pytest

from oto.builder import build, clean, generated_paths
from oto.layout import Layout
from oto.project import Project
from oto.scaffold import init

ONTOLOGY = {"classes": {"M": {"definition": "machine"}, "S": {"definition": "site"}},
            "properties": {"at": {"domain": "M", "range": "S", "definition": "where"}}, "temporal": {}}
STAMP = {"as_of": "2026-01-01", "valid_from": "2026-01-01", "source_doc": "h",
         "status": "current", "sources": ["h"]}
GRAPH = {"nodes": [dict(id="m.1", type="M", label="Press", aliases=[], summary="s",
                        attributes={}, tags=[], **STAMP),
                   dict(id="s.1", type="S", label="Plant", aliases=[], summary="s",
                        attributes={}, tags=[], **STAMP)],
         "edges": [{"from": "m.1", "rel": "at", "to": "s.1"}]}


def _project(root, note="Hand written. Must survive."):
    init(root, slug="kb", name="Test KB")
    with open(os.path.join(root, "ontology.config.json"), "w", encoding="utf-8") as f:
        json.dump(ONTOLOGY, f)
    with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
        json.dump(GRAPH, f)
    project = Project.standard(root)
    os.makedirs(project.layout.notes, exist_ok=True)
    with open(os.path.join(project.layout.notes, "01-note.md"), "w", encoding="utf-8") as f:
        f.write("# Note\n\n%s\n" % note)
    return project


# ---- the separation itself ----

def test_labels_drop_the_build_prefix():
    """These strings land in the search index, so they are output and must not drift."""
    layout = Layout("/p", "/p/build", "acme.db")
    assert layout.label("/p/build/documents/x.md") == "documents/x.md"
    assert layout.label("/p/build/entities/e.md") == "entities/e.md"
    assert layout.label("/p/notes/01.md") == "notes/01.md"


def test_the_build_root_is_the_whole_build_directory():
    layout = Layout("/p", "/p/build", "a.db")
    assert layout.build_root() == "/p/build"
    assert all(path.startswith("/p/build/") for path in layout.generated()), "everything the build owns is under it"
    assert all(not path.startswith("/p/build/") for path in layout.authored() + layout.sources())


# ---- what the build owns ----

def test_generated_paths_never_include_the_corpus_or_the_notes():
    """The corpus comes from ingest, and notes are authored. Stashing either would destroy work."""
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        owned = generated_paths(project)
        assert project.layout.corpus not in owned
        assert project.layout.notes not in owned
        assert project.layout.entities in owned
        assert project.layout.database in owned


def test_nothing_authored_lives_under_the_build_root():
    """The whole point: `build/` must be safe to delete."""
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        build(project)
        build_root = project.layout.build_root()
        assert build_root
        for authored in project.layout.authored():
            assert not os.path.abspath(authored).startswith(os.path.abspath(build_root) + os.sep)


# ---- clean ----

def test_clean_removes_the_build_and_spares_the_notes():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        build(project)
        note = os.path.join(project.layout.notes, "01-note.md")
        assert os.path.exists(project.layout.database)
        clean(project)
        assert not os.path.exists(project.layout.build_root())
        assert os.path.exists(note), "clean destroyed an authored note"
        with open(note, encoding="utf-8") as f:
            assert "Must survive" in f.read()


def test_clean_dry_run_removes_nothing():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        build(project)
        targets = clean(project, dry_run=True)
        assert targets
        assert os.path.exists(project.layout.database)


def test_build_after_clean_reproduces_the_database():
    """`clean` then `build` must be a no-op overall, or the build is not reproducible."""
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        build(project)
        with open(project.layout.database, "rb") as f:
            before = f.read()
        clean(project)
        build(project)
        with open(project.layout.database, "rb") as f:
            assert f.read() == before


def test_authored_notes_are_indexed():
    """A note outside the build root must still reach the search index."""
    import sqlite3

    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        build(project)
        con = sqlite3.connect(project.layout.database)
        rows = con.execute("select path from docs where path like 'notes/%'").fetchall()
        con.close()
        assert rows, "the authored note was not indexed"


# ---- the database swap ----

def test_a_failure_mid_write_leaves_the_served_database_untouched(tmp_path, monkeypatch):
    """The database is the only generated file a running server reads, so it is the one that must
    never be seen half-written. The target builds into `<name>.db.new` and renames, which is atomic
    on one volume. This test fails if anyone replaces that with a write in place.
    """
    import hashlib
    import os

    from oto import builder
    from oto.cli import main
    from oto.project import Project
    from oto.targets import sqlite as target

    root = str(tmp_path / "proj")
    assert main(["init", "--slug", "atom", "--project", root, "--ontology", "auto-claims"]) == 0
    assert main(["build", "--project", root]) == 0

    project = Project.standard(root)
    database = project.layout.database
    before = hashlib.sha256(open(database, "rb").read()).hexdigest()

    # Fail late: after the tables are populated, before the rename.
    def explode(*_args, **_kwargs):
        raise RuntimeError("disk error during the sqlite stage")

    monkeypatch.setattr(Project, "build_seq", explode)
    with pytest.raises(RuntimeError):
        target.run(project)

    after = hashlib.sha256(open(database, "rb").read()).hexdigest()
    assert after == before, "a failed write reached the database a server is reading"

    # The next build must not be confused by whatever the failed one left behind.
    monkeypatch.undo()
    assert main(["build", "--project", root]) == 0
    assert os.path.exists(database)


def test_serving_reads_the_database_and_nothing_the_build_writes_as_text():
    """Why the markdown artifacts do not need the same protection.

    `oto build` is transactional for them: a failure restores the previous set. It is not atomic, and
    that is acceptable only while nothing serves answers from them. If the engine ever starts reading
    a generated file directly, this test fails and that decision has to be revisited.
    """
    import inspect

    from oto.serve import engine

    source = inspect.getsource(engine)
    for artifact in ("entities/", "cards/", "ontology/", ".md"):
        assert 'open(%r' % artifact not in source
    assert source.count("open(") <= 2, (
        "the engine opens more files than the database and its config; if it now reads a generated "
        "artifact, the build needs to be atomic for that artifact too")


def test_no_search_index_is_written():
    """FTS5 in the database is the search index. The old inverted index had no reader."""
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        build(project)
        assert not os.path.exists(os.path.join(project.layout.graph, "search-index.json"))
        assert os.path.exists(project.layout.database)


def test_every_command_still_works_after_clean():
    """`clean` deletes build/ whole. The next command must recreate it, not refuse."""
    from oto.cli import main

    with tempfile.TemporaryDirectory() as root:
        _project(root)
        assert main(["build", "--project", root]) == 0
        assert main(["clean", "--project", root]) == 0
        assert not os.path.isdir(os.path.join(root, "build"))
        assert main(["status", "--project", root]) == 0
        assert main(["build", "--project", root]) == 0
        assert os.path.exists(Project.standard(root).layout.database)


def test_a_folder_without_a_config_is_not_a_project():
    with tempfile.TemporaryDirectory() as root:
        with pytest.raises(Exception, match="not an OTO project"):
            Project.standard(root)
        assert not os.path.isdir(os.path.join(root, "build")), "nothing may be created there"


def test_a_partial_build_keeps_what_the_other_stages_wrote():
    """`--only site` after a full build reads the store; `--only neo4j` reads the graph files. The
    transaction stashes only what the stages it runs own."""
    import tempfile
    from oto.scaffold import init
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="acme", name="Acme", ontology="software-architecture")
        project = Project.standard(root)
        build(project)
        db = project.layout.database
        before = os.stat(db).st_mtime_ns
        assert generated_paths(project, {"site"}) == [project.layout.site]
        assert generated_paths(project, {"neo4j"}) == []
        assert set(generated_paths(project, {"knowledge", "rules"})) < set(generated_paths(project))
        project.options = {"targets": {"site"}, "view": "explorer", "verify": False}
        assert build(project, only={"site"}) == ["site"]
        assert os.path.exists(os.path.join(project.layout.site, "index.html"))
        assert os.stat(db).st_mtime_ns == before and os.path.exists(os.path.join(project.layout.graph, "knowledge-graph.json"))
