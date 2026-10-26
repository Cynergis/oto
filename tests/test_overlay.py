"""Overlay connectors (roadmap K2, K7) and schema introspection (C1).

A materialize connector pushes OTO's graph into a store OTO owns. An overlay connector reads a store
that already exists, in place: its catalog (`introspect`), its query log (`query_log`) and a read-only
query (`native_read`), and never copies a row. The manifest declares the mode; the interface and the
kit check what the mode claims. SQLite is the reference overlay: in the stdlib, so the whole chain
runs on every machine. `oto data introspect` turns a store's catalog into a proposal in the data
vocabulary, cited to a schema document, that goes through the gates like any other change."""
import contextlib
import io
import json
import os
import sqlite3

import pytest

from oto import connectors
from oto.cli import main
from oto.connectors import conformance
from oto.curate import session
from oto.project import Project
from oto.scaffold import init

LEDGER_SQL = """
CREATE TABLE accounts (
  account_id INTEGER PRIMARY KEY,
  currency   CHAR(3) NOT NULL
);
CREATE TABLE postings (
  posting_id   INTEGER PRIMARY KEY,
  account_id   INTEGER NOT NULL REFERENCES accounts(account_id),
  amount_cents BIGINT NOT NULL,
  posted_at    TEXT
);
CREATE VIEW daily_balances AS
  SELECT account_id, date(posted_at) AS day, sum(amount_cents) AS balance_cents FROM postings GROUP BY 1, 2;
INSERT INTO accounts VALUES (1, 'CAD'), (2, 'USD');
INSERT INTO postings VALUES (10, 1, 1250, '2026-10-01 09:00'), (11, 1, -250, '2026-10-02 09:00'), (12, 2, 900, '2026-10-02 10:00');
"""


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


@pytest.fixture
def ledger_db(tmp_path):
    path = str(tmp_path / "ledger.sqlite")
    con = sqlite3.connect(path)
    con.executescript(LEDGER_SQL)
    con.commit()
    con.close()
    return path


# ---- the interface and the manifest ----

def test_the_manifest_declares_the_mode_and_the_interface_checks_what_the_mode_claims():
    assert connectors.OVERLAY_METHODS == ("introspect", "query_log", "native_read")
    sqlite = connectors.get("sqlite")
    assert sqlite.MANIFEST["modes"] == ["materialize", "overlay"], "the reference overlay, in the stdlib"
    assert connectors.interface_problems(sqlite) == []

    class HalfOverlay(connectors.Connector):
        name = "half"
        MANIFEST = dict(sqlite.MANIFEST, name="half", modes=["overlay"])

        def introspect(self, session):
            return {"store": "x", "tables": []}
    problems = connectors.interface_problems(HalfOverlay)
    assert any("query_log" in p for p in problems) and any("native_read" in p for p in problems), problems
    assert not any("publish" in p for p in problems), "an overlay-only connector owes nothing of the materialize interface"
    neo4j = connectors.get("neo4j")
    assert neo4j.MANIFEST["modes"] == ["materialize"] and connectors.interface_problems(neo4j) == []


# ---- the SQLite overlay ----

def test_sqlite_introspects_tables_views_columns_keys_and_references_in_place(ledger_db):
    sqlite = connectors.get("sqlite")
    s = sqlite.connect({"path": ledger_db})
    schema = sqlite.introspect(s)
    assert schema["store"] == "ledger" and [t["name"] for t in schema["tables"]] == ["accounts", "daily_balances", "postings"]
    assert {t["name"]: t["kind"] for t in schema["tables"]} == {"accounts": "table", "postings": "table", "daily_balances": "view"}
    postings = next(t for t in schema["tables"] if t["name"] == "postings")
    by_name = {c["name"]: c for c in postings["columns"]}
    assert by_name["posting_id"] == {"name": "posting_id", "type": "INTEGER", "nullable": False, "key": "primary", "references": None}
    assert by_name["account_id"] == {"name": "account_id", "type": "INTEGER", "nullable": False, "key": "foreign", "references": "accounts.account_id"}
    assert by_name["posted_at"]["nullable"] is True and by_name["posted_at"]["key"] is None
    view = next(t for t in schema["tables"] if t["name"] == "daily_balances")
    assert [c["name"] for c in view["columns"]] == ["account_id", "day", "balance_cents"]
    assert sqlite.introspect(s) == schema, "the catalog read twice is the same catalog"
    assert sqlite.query_log(s) == [], "SQLite keeps no query log: an empty list, not an error"
    before = sqlite3.connect(ledger_db).execute("SELECT count(*) FROM postings").fetchone()[0]
    assert before == 3


def test_sqlite_native_read_is_read_only(ledger_db):
    sqlite = connectors.get("sqlite")
    s = sqlite.connect({"path": ledger_db})
    result = sqlite.native_read(s, "SELECT account_id, sum(amount_cents) AS total FROM postings GROUP BY 1 ORDER BY 1")
    assert result["columns"] == ["account_id", "total"] and result["rows"] == [[1, 1000], [2, 900]]
    assert sqlite.native_read(s, "SELECT * FROM postings", limit=2)["rows"].__len__() == 2 and result["truncated"] is False
    for sql in ("DELETE FROM postings", "UPDATE postings SET amount_cents = 0", "DROP TABLE accounts", "INSERT INTO accounts VALUES (3, 'EUR')",
                "SELECT 1; DELETE FROM postings", "PRAGMA journal_mode = OFF", "CREATE TABLE x (a)", "ATTACH DATABASE ':memory:' AS m"):
        with pytest.raises(ValueError) as caught:
            sqlite.native_read(s, sql)
        assert "read" in str(caught.value).lower(), sql
    assert sqlite3.connect(ledger_db).execute("SELECT count(*) FROM postings").fetchone()[0] == 3, "nothing changed"
    with pytest.raises(ValueError):
        sqlite.native_read(s, "SELECT * FROM nothing_here")


# ---- the kit ----

def test_the_kit_checks_the_overlay_claims_and_lists_them_in_the_report(tmp_path):
    root = str(tmp_path / "ledger")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="ledger", name="Ledger", ontology="data")
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    project = Project.standard(root)
    sqlite = connectors.get("sqlite")

    def sessions(name):
        return sqlite.connect({"path": str(tmp_path / ("%s.db" % name))})
    result = conformance.run(sqlite, project, sessions)
    names = [c["name"] for c in result["checks"]]
    assert names[:2] == ["manifest", "interface"]
    assert {"overlay introspect", "overlay read-only", "overlay log"} <= set(names), names
    assert result["passed"], conformance.report(result)
    text = conformance.report(result)
    assert "overlay introspect ok" in text.replace("  ", " ") or "overlay introspect" in text
    code, out = _cli("connectors", "check", "sqlite", "--project", root)
    assert code == 0 and "overlay introspect" in out and "passed" in out, out


def test_the_listing_shows_both_modes():
    code, out = _cli("connectors", "list")
    assert code == 0 and "sqlite" in out and "materialize, overlay" in out, out


# ---- oto data introspect ----

def _seed_store(root, store_id, name):
    """The estate declares the store before the data layer describes it: a DataStore that runs in an
    environment, through the gates."""
    path = os.path.join(root, "seed-%s.json" % store_id.split(".", 1)[1])
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"source_doc": "estate", "as_of": "2026-10-01", "nodes": [
            {"id": "environment.production", "type": "Environment", "label": "Production", "attributes": {}},
            {"id": store_id, "type": "DataStore", "label": name, "attributes": {}}],
            "edges": [{"from": store_id, "rel": "runs_in", "to": "environment.production"}]}, f)
    for step in (("curate", "start"), ("curate", "add", "--from", path), ("curate", "check"), ("curate", "apply", "--by", "Sam Lee", "--note", "the store")):
        code, out = _cli(*step, "--project", root)
        assert code == 0, out


@pytest.fixture
def described(tmp_path, ledger_db):
    """A data project whose estate declares the ledger store, with the fixture ledger introspected."""
    root = str(tmp_path / "described")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="described", name="The ledger, described", ontology="data", empty=True)
    _seed_store(root, "datastore.ledger", "Ledger database")
    code, out = _cli("data", "introspect", "--path", ledger_db, "--store", "datastore.ledger", "--at", "2026-10-26", "--project", root)
    assert code == 0, out
    return root, out


def test_introspect_writes_the_schema_document_and_a_proposal_cited_to_it(described):
    root, out = described
    assert "schema-ledger" in out and "proposals/schema-ledger.json" in out and "curate add" in out, out
    corpus = os.path.join(root, "build", "documents", "schema-ledger.md")
    assert os.path.exists(corpus), "the snapshot went through ingest: it is in the corpus, so the quotes can be checked"
    text = open(corpus, encoding="utf-8").read()
    assert "## postings (table)" in text and "account_id INTEGER not null references accounts.account_id" in text, text
    with open(os.path.join(root, "proposals", "schema-ledger.json"), encoding="utf-8") as f:
        proposal = json.load(f)
    assert proposal["source_doc"] == "schema-ledger" and proposal["as_of"] == "2026-10-26"
    nodes = {n["id"]: n for n in proposal["nodes"]}
    assert nodes["table.ledger-postings"]["type"] == "Table" and nodes["table.ledger-postings"]["attributes"] == {"kind": "table"}
    assert nodes["table.ledger-daily-balances"]["attributes"] == {"kind": "view"}
    column = nodes["column.ledger-postings-account-id"]
    assert column["type"] == "Column" and column["label"] == "account_id"
    assert column["attributes"] == {"type": "INTEGER", "nullable": False, "key": "foreign"}
    assert column["evidence"] == [{"doc": "schema-ledger", "where": "postings", "quote": "account_id INTEGER not null references accounts.account_id"}]
    assert "description" not in column["attributes"] and "description_status" not in column["attributes"], "meaning is not the catalog's to say: it stays a draft for an agent and a person (C2)"
    assert "datastore.ledger" not in nodes, "the store is the estate's, declared before the data layer describes it"
    assert nodes["document.schema-ledger"]["type"] == "Document" and nodes["document.schema-ledger"]["attributes"] == {"kind": "schema"}
    edges = {(e["from"], e["rel"], e["to"]) for e in proposal["edges"]}
    assert ("column.ledger-postings-account-id", "column_of", "table.ledger-postings") in edges
    assert ("column.ledger-postings-account-id", "references", "column.ledger-accounts-account-id") in edges
    assert ("table.ledger-postings", "part_of", "datastore.ledger") in edges and ("table.ledger-daily-balances", "part_of", "datastore.ledger") in edges
    assert all(n.get("source_type", "extraction") in ("extraction", "observation") for n in proposal["nodes"])


def _through_the_gates(root):
    code, out = _cli("curate", "start", "--project", root)
    assert code == 0, out
    code, out = _cli("curate", "add", "--from", os.path.join(root, "proposals", "schema-ledger.json"), "--project", root)
    assert code == 0, out
    code, out = _cli("curate", "check", "--project", root)
    assert code == 0 and "blocking" not in out and "not in the document" not in out, out
    code, out = _cli("curate", "apply", "--by", "Sam Lee", "--note", "the ledger's schema", "--project", root)
    assert code == 0, out
    code, out = _cli("build", "--project", root)
    assert code == 0, out


def test_the_schema_goes_through_the_gates_and_the_graph_answers_what_the_store_holds(described):
    root, _out = described
    _through_the_gates(root)
    graph = session.live(Project.standard(root))
    kinds = {}
    for n in graph["nodes"]:
        kinds[n["type"]] = kinds.get(n["type"], 0) + 1
    assert kinds["Table"] == 3 and kinds["Column"] == 9 and kinds["DataStore"] == 1 and kinds.get("Document") == 1 and kinds["Environment"] == 1, kinds
    code, out = _cli("query", "--project", root, "ask", "DT5", "STORE=datastore.ledger")
    assert code == 0 and "status: answered" in out and "postings" in out and "t.kind=view" in out, out
    code, out = _cli("query", "--project", root, "ask", "DT1", "TABLE=table.ledger-postings")
    assert code == 0 and "status: answered" in out and "c.key=foreign" in out and "c.type=INTEGER" in out, out
    code, out = _cli("query", "--project", root, "ask", "DT4")
    assert code == 0 and "posting_id" in out, "every introspected meaning is a draft until a person says otherwise"
    code, out = _cli("ontology", "check", "--project", root)
    assert code == 0 and "every node satisfies them" in out, out
    code, out = _cli("audit", "log", "--project", root)
    assert code == 0 and "curate apply" in out


def test_introspecting_again_an_unchanged_store_changes_nothing(described, ledger_db):
    root, _out = described
    _through_the_gates(root)
    before = session.live(Project.standard(root))
    code, out = _cli("data", "introspect", "--path", ledger_db, "--store", "datastore.ledger", "--at", "2026-10-27", "--project", root)
    assert code == 0, out
    _through_the_gates(root)
    after = session.live(Project.standard(root))
    assert len(after["nodes"]) == len(before["nodes"]) and len(after["edges"]) == len(before["edges"]), "the same catalog twice is one set of facts"


def test_introspect_refuses_a_vocabulary_without_tables_and_a_missing_store(tmp_path, ledger_db):
    plain = str(tmp_path / "plain")
    with contextlib.redirect_stdout(io.StringIO()):
        init(plain, slug="plain", name="Plain", ontology="communication")
    code, out = _cli("data", "introspect", "--path", ledger_db, "--store", "datastore.ledger", "--at", "2026-10-26", "--project", plain)
    assert code == 1 and "Table" in out and "data" in out, out
    root = str(tmp_path / "d")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="d", name="D", ontology="data", empty=True)
    code, out = _cli("data", "introspect", "--path", str(tmp_path / "nothing.sqlite"), "--store", "datastore.x", "--at", "2026-10-26", "--project", root)
    assert code == 1 and "nothing.sqlite" in out, out
    code, out = _cli("data", "introspect", "--path", ledger_db, "--store", "datastore.ledger", "--project", root)
    assert code == 1 and "--at" in out, "the date is never defaulted"
    code, out = _cli("data", "introspect", "--path", ledger_db, "--store", "datastore.ledger", "--at", "2026-10-26", "--project", root)
    assert code == 1 and "datastore.ledger" in out and "estate" in out, "the store is declared before it is described"
    assert not os.path.exists(os.path.join(root, "proposals", "schema-ledger.json")) and not os.path.exists(os.path.join(root, "build", "documents", "schema-ledger.md"))


def test_introspect_defaults_to_the_project_s_own_store(tmp_path):
    """Dogfood: with no --path, the project's own built store is the schema described."""
    root = str(tmp_path / "self")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="self", name="Self", ontology="data")
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    _seed_store(root, "datastore.self", "This project's own store")
    code, out = _cli("data", "introspect", "--store", "datastore.self", "--at", "2026-10-26", "--project", root)
    assert code == 0, out
    with open(os.path.join(root, "proposals", "schema-self.json"), encoding="utf-8") as f:
        proposal = json.load(f)
    ids = {n["id"] for n in proposal["nodes"]}
    assert "table.self-nodes" in ids and "table.self-edges" in ids, sorted(ids)[:10]
