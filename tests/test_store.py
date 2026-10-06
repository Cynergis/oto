"""The store interface: the SQLite implementation returns exactly the rows the engine's text is
built from, and the engine can be pointed at any store."""
import json
import os
import tempfile

from oto.builder import build
from oto.project import Project
from oto.scaffold import init
from oto.serve.store import SqliteStore, fts_tokens

ONTOLOGY = {
    "classes": {"Machine": {"definition": "A machine."}, "Site": {"definition": "A place."}, "Document": {"definition": "A source."}},
    "properties": {"installed_at": {"domain": "Machine", "range": "Site", "inverse": "hosts", "definition": "Where a machine runs."}},
    "attributes": {"Machine": {"state": {"type": "enum:running|idle", "definition": "lifecycle"}, "tonnage": {"type": "number", "definition": "t"}}},
    "temporal": {},
}
STAMP = {"as_of": "2026-01-01", "valid_from": "2026-01-01", "source_doc": "handbook", "status": "current",
         "sources": ["handbook"]}
GRAPH = {
    "nodes": [
        dict(id="m.1", type="Machine", label="Press 01", aliases=["Press One"], summary="A stamping press.",
             attributes={"state": "running", "tonnage": 40}, tags=["machine", "line-a"],
             evidence=[{"doc": "handbook", "where": "p.3", "quote": "Press 01 is a 40 t press."}], **STAMP),
        dict(id="m.0", type="Machine", label="Press 00", aliases=[], summary="The old press.", attributes={},
             tags=["machine"], as_of="2025-01-01", valid_from="2025-01-01", valid_to="2026-01-01",
             source_doc="handbook", status="superseded", superseded_by="m.1", sources=["handbook"]),
        dict(id="s.1", type="Site", label="North Plant", aliases=["NP"], summary="The north plant.",
             attributes={}, tags=["site"], **STAMP),
        dict(id="doc.handbook", type="Document", label="Plant handbook", aliases=[], summary="The handbook.",
             attributes={"date": "2025-12-01"}, tags=[], **STAMP),
    ],
    "edges": [{"from": "m.1", "rel": "installed_at", "to": "s.1"},
              {"from": "m.0", "rel": "installed_at", "to": "s.1", "status": "superseded"}],
}
LEXICON = {"entries": [{"term": "the press", "aka": ["big press"], "targets": ["m.1"], "status": "current", "note": ""},
                       {"term": "the mill", "targets": [], "status": "not_ingested", "note": "no document yet"}]}


def _built(root):
    init(root, slug="kb", name="KB")
    for name, payload in (("ontology.config.json", ONTOLOGY), ("graph.json", GRAPH), ("lexicon.json", LEXICON)):
        with open(os.path.join(root, name), "w", encoding="utf-8") as f:
            json.dump(payload, f)
    os.makedirs(os.path.join(root, "notes"), exist_ok=True)
    with open(os.path.join(root, "notes", "presses.md"), "w", encoding="utf-8") as f:
        f.write("# Presses\n\nPress 01 stamps door panels on line A.\n")
    project = Project.standard(root)
    build(project)
    return project


def test_fts_tokens_split_on_anything_but_letters_and_digits():
    assert fts_tokens("press-01, line A") == ["press", "01", "line", "A"]
    assert fts_tokens("") == []


def test_the_sqlite_store_returns_the_rows_the_engine_reads():
    with tempfile.TemporaryDirectory() as root:
        project = _built(root)
        store = SqliteStore(project.layout.database)
        try:
            assert store.kind == "sqlite" and store.meta("build_seq") is not None
            assert {"derived", "derived_attributes", "policy", "lexicon", "changelog"} <= store.features()
            n = store.node("m.1")
            assert n["label"] == "Press 01" and n["type"] == "Machine" and n["superseded_by"] is None
            assert json.loads(n["attributes"]) == {"state": "running", "tonnage": 40}
            assert json.loads(n["evidence"])[0]["where"] == "p.3" and json.loads(n["tags"]) == ["machine", "line-a"]
            assert n["degree"] == 1
            assert store.node("nope") is None and store.label("nope") == "nope"
            assert store.by_name("press one") == ["m.1"] and store.by_name("np") == ["s.1"]
            assert store.by_text("stamping")[0] == "m.1"
            assert store.aliases("m.1") == ["Press One"]
            assert [(e["rel"], e["dst"], e["status"]) for e in store.edges_out("m.1")] == [("installed_at", "s.1", "current")]
            assert sorted(e["src"] for e in store.edges_in("s.1")) == ["m.0", "m.1"]
            assert store.edges_in("s.1", "nothing") == []
            assert store.edge("m.1", "installed_at", "s.1")["status"] == "current"
            assert store.predecessors("m.1") == ["m.0"]
            assert [r["path"] for r in store.search("door panels")] == ["notes/presses.md"]
            assert [r["id"] for r in store.by_type("Machine")] == ["m.0", "m.1"]
            assert [r["id"] for r in store.by_type("Machine", state="running")] == ["m.1"]
            assert store.status_counts() == [{"status": "current", "c": 3}, {"status": "superseded", "c": 1}]
            assert [r["id"] for r in store.superseded()] == ["m.0"]
            assert store.policy_findings() == []
            assert store.count() == 4 and store.count(type_="Machine") == 2 and store.count(tag="line") == 1
            assert store.count(type_="Machine", attr="state", value="running") == 1
            assert store.group_by("type")[0] == {"g": "Machine", "c": 2}
            assert [r["g"] for r in store.group_by("state", type_="Machine")] == [None, "running"]
            assert store.lexicon("big press")[0]["target"] == "m.1"
            assert store.lexicon_fuzzy("mill")[0]["status"] == "not_ingested"
            assert [d["id"] for d in store.documents()] == ["doc.handbook"] and store.documents("zzz") == []
            assert store.frontier() == "2026-01-01"
            counts = store.counts()
            assert counts["nodes"] == 4 and counts["edges"] == 2 and counts["superseded"] == 1
            assert store.types_current()[0]["c"] == 1 and store.rels_counts()[0] == {"rel": "installed_at", "c": 2}
            assert store.hubs(1)[0]["id"] == "s.1"
            assert len(store.tags_current()) == 3
            assert store.docs_count("notes/") == 1 and store.docs_count("documents/") == 0
            assert store.changelog() == []
        finally:
            store.close()


def test_the_engine_answers_from_whatever_store_it_is_given():
    from oto.serve import engine

    with tempfile.TemporaryDirectory() as root:
        project = _built(root)
        store = SqliteStore(project.layout.database)
        engine.use(store)
        try:
            assert "Press 01" in engine.entity_text("Press One")
            assert "[derived by" not in engine.entity_text("m.1")
            assert "SUPERSEDED" in engine.entity_text("m.0") and "Showing current" in engine.entity_text("m.0")
            assert "Press 00" in engine.entity_text("m.1", history=True)
            assert "notes/presses.md" in engine.search_text("door panels")
            assert "count = 2" in engine.count_text(type_="Machine")
            assert "the press" in engine.resolve_text("big press") and "✓ m.1" in engine.resolve_text("big press")
            assert "NOT-INGESTED" not in engine.resolve_text("the mill") and "[NOT_INGESTED]" in engine.resolve_text("the mill")
            assert "Plant handbook" in engine.docs_text()
            assert "Overview: 4 nodes, 2 edges" in engine.overview_text()
            assert "every fact shown is asserted" in engine.explain_text("m.1")
            assert "No policy findings" in engine.policy_text()
        finally:
            engine.use(None)
            store.close()


def test_preflight_refuses_a_server_that_reads_neo4j_nobody_loads():
    from oto.validate.preflight import preflight

    with tempfile.TemporaryDirectory() as root:
        project = _built(root)
        cfg = json.load(open(project.config_path, encoding="utf-8"))
        cfg["serve"] = {"backend": "neo4j"}
        json.dump(cfg, open(project.config_path, "w", encoding="utf-8"))
        warnings = preflight(project)["warnings"]
        assert any("serves from Neo4j" in w and "does not load it" in w for w in warnings), warnings
        cfg["targets"] = ["sqlite", "neo4j"]
        cfg["neo4j"] = {"uri": "bolt://localhost:7687"}
        json.dump(cfg, open(project.config_path, "w", encoding="utf-8"))
        assert not any("serves from Neo4j" in w for w in preflight(project)["warnings"])
        cfg["serve"] = {"backend": "graphite"}
        json.dump(cfg, open(project.config_path, "w", encoding="utf-8"))
        assert any("unknown serve.backend" in w for w in preflight(project)["warnings"])


def test_status_says_which_store_serves_and_whether_neo4j_answers(monkeypatch, capsys):
    from oto.cli import main
    from oto.cli.status import gather

    with tempfile.TemporaryDirectory() as root:
        project = _built(root)
        assert gather(project)["backend"] == "sqlite" and gather(project)["neo4j"] is None
        assert main(["status", "--project", root]) == 0
        assert "serve       sqlite" in capsys.readouterr().out
        cfg = json.load(open(project.config_path, encoding="utf-8"))
        cfg["serve"] = {"backend": "neo4j"}
        cfg["targets"] = ["sqlite", "neo4j"]
        cfg["neo4j"] = {"uri": "bolt://127.0.0.1:1"}
        json.dump(cfg, open(project.config_path, "w", encoding="utf-8"))
        for var in ("NEO4J_PASSWORD", "NEO4J_AUTH", "NEO4J_URI"):
            monkeypatch.delenv(var, raising=False)
        s = gather(project)
        assert s["backend"] == "neo4j" and s["neo4j"]["reachable"] is False and s["neo4j"]["problem"]
        assert s["next"].startswith("the server reads Neo4j and cannot")
        assert main(["status", "--project", root]) == 0
        assert "Neo4j NOT serving" in capsys.readouterr().out
