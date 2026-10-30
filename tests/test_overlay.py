"""Overlay connectors (roadmap K2, K7) and schema introspection (C1).

A materialize connector pushes OTO's graph into a store OTO owns. An overlay connector reads a store
that already exists, in place: its catalog (`introspect`), its query log (`query_log`) and a read-only
query (`native_read`), and never copies a row. The manifest declares the mode; the interface and the
kit check what the mode claims. SQLite is the reference overlay: in the stdlib, so the whole chain
runs on every machine. What the data pack of the registry does with a catalog (`oto data introspect`)
is tested beside that pack (ADR-0010)."""
import contextlib
import io
import json
import os
import sqlite3

import pytest

from oto import connectors
from oto.cli import main
from oto.connectors import conformance
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
        init(root, slug="ledger", name="Ledger", ontology="software-architecture")
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
