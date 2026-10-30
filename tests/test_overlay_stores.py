"""The Postgres and BigQuery overlays (roadmap K8) and the read-only passthrough (K5).

Both read a store in place: the catalog from information_schema, the query log from what the store
keeps (pg_stat_statements; INFORMATION_SCHEMA.JOBS), one SELECT at a time and never a write. Each
runs here against a fake connection or client that replays rows recorded from a real store
(tests/fixtures/overlay), so the overlay is tested on every machine without credentials; the live
kit runs for Postgres in CI's postgres job (OTO_POSTGRES_DSN) and for BigQuery by hand.

`kg_read` is the served passthrough: one read-only query against the overlay the deploy config
names, and off unless `oto.deploy.json` says `overlay.native_read: true`."""
import contextlib
import io
import json
import os
import re
import sqlite3
import types

import pytest

from oto import connectors, deploy
from oto.cli import main
from oto.connectors import conformance
from oto.project import Project
from oto.scaffold import init

from test_apps import _engine, _get
from test_overlay import LEDGER_SQL

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "overlay")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


# ---- a fake Postgres connection: DB-API 2.0, replaying recorded rows ----

class FakeCursor:
    def __init__(self, con):
        self.con, self.rows, self.description = con, [], None

    def execute(self, sql, params=None):
        self.con.executed.append(sql.strip())
        text = sql.strip()
        fx = self.con.fixture
        if text.startswith("START TRANSACTION") or text == "ROLLBACK":
            self.rows = []
        elif "information_schema.tables" in text:
            self.rows = fx["tables"]
        elif "information_schema.columns" in text:
            self.rows = fx["columns"]
        elif "table_constraints" in text:
            self.rows = fx["keys"]
        elif "pg_extension" in text:
            self.rows = fx.get("extension", [])
        elif "pg_stat_statements" in text:
            self.rows = fx["log"]
        elif text in fx["queries"]:
            self.rows = fx["queries"][text]["rows"]
            self.description = [(c,) for c in fx["queries"][text]["columns"]]
        elif re.match(r"(?i)^(select|with)\b", text):
            raise RuntimeError('relation "nothing_here" does not exist')
        else:
            raise RuntimeError("cannot execute %s in a read-only transaction" % text.split()[0].upper())

    def fetchall(self):
        return list(self.rows)

    def fetchmany(self, n):
        return list(self.rows[:n])

    def close(self):
        pass


class FakePostgres:
    def __init__(self, fixture):
        self.fixture, self.executed, self.closed = fixture, [], False

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        self.executed.append("ROLLBACK")

    def close(self):
        self.closed = True


# ---- a fake BigQuery client, replaying recorded rows ----

class FakeRows(list):
    def __init__(self, columns, rows):
        super().__init__(types.SimpleNamespace(values=lambda r=r: list(r)) for r in rows)
        self.schema = [types.SimpleNamespace(name=c) for c in columns]


class FakeJob:
    def __init__(self, client, sql, dry_run):
        self.client, self.sql, self.dry_run = client, sql, dry_run
        first = re.findall(r"(?i)\b(select|with|insert|update|delete|create|drop|merge)\b", sql)
        self.statement_type = "INSERT" if "insert into" in sql.lower() else (first[0].upper() if first else "UNKNOWN")

    def result(self, max_results=None):
        fx, sql = self.client.fixture, self.sql.strip()
        if "INFORMATION_SCHEMA.TABLES" in sql:
            columns, rows = ["table_name", "table_type"], fx["tables"]
        elif "INFORMATION_SCHEMA.COLUMNS" in sql:
            columns, rows = ["table_name", "column_name", "data_type", "is_nullable", "ordinal_position"], fx["columns"]
        elif "KEY_COLUMN_USAGE" in sql:
            columns, rows = ["table_name", "column_name", "constraint_type", "ref_table", "ref_column"], fx["keys"]
        elif "JOBS_BY_PROJECT" in sql:
            columns, rows = ["creation_time", "user_email", "query", "total_bytes_processed", "statement_type"], fx["log"]
        elif sql in fx["queries"]:
            columns, rows = fx["queries"][sql]["columns"], fx["queries"][sql]["rows"]
        else:
            raise RuntimeError("Not found: Table acme:ledger.nothing_here")
        return FakeRows(columns, rows[:max_results] if max_results else rows)


class FakeBigQuery:
    def __init__(self, fixture):
        self.fixture, self.queries = fixture, []

    def query(self, sql, job_config=None):
        dry = bool(getattr(job_config, "dry_run", False))
        self.queries.append((sql.strip(), dry, getattr(job_config, "maximum_bytes_billed", None)))
        return FakeJob(self, sql, dry)

    def close(self):
        pass


# ---- the manifests ----

def test_both_are_listed_as_overlay_only_and_import_nothing_until_connected():
    assert connectors.available() == ["bigquery", "neo4j", "postgres", "sqlite"]
    for name, language in (("postgres", "sql"), ("bigquery", "sql")):
        c = connectors.get(name)
        assert c.MANIFEST["modes"] == ["overlay"] and c.MANIFEST["query_language"] == language, name
        assert connectors.manifest_problems(c.MANIFEST) == [] and connectors.interface_problems(c) == [], name
    code, out = _cli("connectors", "list")
    assert code == 0 and "postgres" in out and "bigquery" in out and "overlay" in out


# ---- Postgres ----

def test_postgres_introspects_the_ledger_from_information_schema():
    pg = connectors.get("postgres")
    fake = FakePostgres(_fixture("postgres-ledger.json"))
    s = pg.connect({"connection": fake, "schema": "public", "name": "ledger"})
    schema = pg.introspect(s)
    assert schema["store"] == "ledger" and [t["name"] for t in schema["tables"]] == ["accounts", "daily_balances", "postings"]
    assert {t["name"]: t["kind"] for t in schema["tables"]} == {"accounts": "table", "postings": "table", "daily_balances": "view"}
    postings = {c["name"]: c for c in next(t for t in schema["tables"] if t["name"] == "postings")["columns"]}
    assert postings["posting_id"] == {"name": "posting_id", "type": "integer", "nullable": False, "key": "primary", "references": None}
    assert postings["account_id"] == {"name": "account_id", "type": "integer", "nullable": False, "key": "foreign", "references": "accounts.account_id"}
    assert postings["posted_at"]["type"] == "timestamp without time zone" and postings["posted_at"]["nullable"] is True
    assert all("%s" in q or "information_schema" in q for q in fake.executed if "schema" in q), "the schema is a parameter, never spliced into the SQL"
    assert pg.introspect(s) == schema
    log = pg.query_log(s)
    assert log[0] == {"by": "payment_api", "sql": "SELECT * FROM postings WHERE account_id = $1", "calls": 1240, "total_ms": 310.5}, "with who ran it"
    empty = pg.connect({"connection": FakePostgres(dict(_fixture("postgres-ledger.json"), extension=[])), "schema": "public"})
    assert pg.query_log(empty) == [], "without pg_stat_statements there is no log, and that is not an error"


def test_postgres_native_read_runs_one_select_in_a_read_only_transaction():
    pg = connectors.get("postgres")
    fake = FakePostgres(_fixture("postgres-ledger.json"))
    s = pg.connect({"connection": fake, "schema": "public"})
    result = pg.native_read(s, "SELECT account_id, sum(amount_cents) AS total FROM postings GROUP BY 1 ORDER BY 1")
    assert result == {"columns": ["account_id", "total"], "rows": [[1, 1000], [2, 900]], "truncated": False}
    assert fake.executed[-3:] == ["START TRANSACTION READ ONLY", "SELECT account_id, sum(amount_cents) AS total FROM postings GROUP BY 1 ORDER BY 1", "ROLLBACK"], fake.executed
    for sql in ("DELETE FROM postings", "SELECT 1; DELETE FROM postings", "CREATE TABLE x (a int)", "COPY postings TO '/tmp/x'"):
        with pytest.raises(ValueError) as caught:
            pg.native_read(s, sql)
        assert "read" in str(caught.value).lower(), sql
    assert not any(q.startswith(("DELETE", "CREATE", "COPY")) for q in fake.executed), "refused by the words, before the store sees it"
    with pytest.raises(ValueError) as caught:
        pg.native_read(s, "SELECT * FROM nothing_here")
    assert "nothing_here" in str(caught.value) and fake.executed[-1] == "ROLLBACK", "an error still ends the transaction"


def test_postgres_settings_come_from_the_config_or_the_environment_never_a_password_in_a_file(tmp_path, monkeypatch):
    pg = connectors.get("postgres")
    root = str(tmp_path / "p")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="p", name="P", ontology="software-architecture", empty=True)
    project = Project.standard(root)
    monkeypatch.delenv("OTO_POSTGRES_DSN", raising=False)
    with pytest.raises(Exception) as caught:
        pg.settings(project)
    assert "OTO_POSTGRES_DSN" in str(caught.value)
    cfg = project.config()
    cfg["postgres"] = {"dsn": "postgresql://ledger@db.internal:5432/ledger", "schema": "finance"}
    with open(project.config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    settings = pg.settings(Project.standard(root))
    assert settings["dsn"] == "postgresql://ledger@db.internal:5432/ledger" and settings["schema"] == "finance" and settings["name"] == "ledger"
    monkeypatch.setenv("OTO_POSTGRES_DSN", "postgresql://x@localhost/other")
    assert pg.settings(Project.standard(root))["dsn"] == "postgresql://x@localhost/other", "the environment overrides the file"
    parts = connectors.get("postgres").parse_dsn("postgresql://ledger:secret@db.internal:5433/ledger?sslmode=require")
    assert parts == {"user": "ledger", "password": "secret", "host": "db.internal", "port": 5433, "database": "ledger", "ssl": True}




# ---- BigQuery ----

def test_bigquery_introspects_the_dataset_from_information_schema():
    bq = connectors.get("bigquery")
    fake = FakeBigQuery(_fixture("bigquery-ledger.json"))
    s = bq.connect({"client": fake, "project": "acme", "dataset": "ledger"})
    schema = bq.introspect(s)
    assert schema["store"] == "ledger" and [t["name"] for t in schema["tables"]] == ["accounts", "daily_balances", "postings"]
    postings = {c["name"]: c for c in next(t for t in schema["tables"] if t["name"] == "postings")["columns"]}
    assert postings["account_id"] == {"name": "account_id", "type": "INT64", "nullable": False, "key": "foreign", "references": "accounts.account_id"}
    assert postings["posting_id"]["key"] == "primary" and postings["posted_at"]["type"] == "TIMESTAMP"
    assert all("`acme.ledger.INFORMATION_SCHEMA." in sql for sql, _d, _b in fake.queries), fake.queries
    assert bq.introspect(s) == schema
    log = bq.query_log(s)
    assert log[0] == {"at": "2026-10-26T02:10:00+00:00", "by": "api@acme.iam.gserviceaccount.com", "sql": "SELECT * FROM `acme.ledger.postings` WHERE account_id = 1",
                      "bytes": 20480, "kind": "SELECT"}, "with who ran it"
    assert "`region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT" in fake.queries[-1][0]


def test_bigquery_native_read_dry_runs_first_and_caps_the_bytes():
    bq = connectors.get("bigquery")
    fake = FakeBigQuery(_fixture("bigquery-ledger.json"))
    s = bq.connect({"client": fake, "project": "acme", "dataset": "ledger", "max_bytes": 5000000})
    sql = "SELECT account_id, SUM(amount_cents) AS total FROM `acme.ledger.postings` GROUP BY 1 ORDER BY 1"
    result = bq.native_read(s, sql)
    assert result == {"columns": ["account_id", "total"], "rows": [[1, 1000], [2, 900]], "truncated": False}
    assert fake.queries[-2:] == [(sql, True, 5000000), (sql, False, 5000000)], "a dry run, then the run, both capped"
    with pytest.raises(ValueError) as caught:
        bq.native_read(s, "DELETE FROM `acme.ledger.postings` WHERE true")
    assert "read" in str(caught.value).lower() and len(fake.queries) == 2, "refused by the words, never sent"
    with pytest.raises(ValueError) as caught:
        bq.native_read(s, "WITH x AS (SELECT 1) INSERT INTO `acme.ledger.t` SELECT * FROM x")
    assert "dry run" in str(caught.value) and fake.queries[-1][1] is True, "a WITH that writes is caught by the dry run and never run"
    with pytest.raises(ValueError):
        bq.native_read(s, "SELECT * FROM `acme.ledger.nothing_here`")


def test_bigquery_settings_name_the_project_and_dataset(tmp_path, monkeypatch):
    bq = connectors.get("bigquery")
    root = str(tmp_path / "b")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="b", name="B", ontology="software-architecture", empty=True)
    project = Project.standard(root)
    monkeypatch.delenv("OTO_BIGQUERY_PROJECT", raising=False)
    monkeypatch.delenv("OTO_BIGQUERY_DATASET", raising=False)
    with pytest.raises(Exception) as caught:
        bq.settings(project)
    assert "OTO_BIGQUERY_PROJECT" in str(caught.value)
    monkeypatch.setenv("OTO_BIGQUERY_PROJECT", "acme")
    monkeypatch.setenv("OTO_BIGQUERY_DATASET", "ledger")
    settings = bq.settings(project)
    assert settings["project"] == "acme" and settings["dataset"] == "ledger" and settings["region"] == "us" and settings["max_bytes"] == 1 << 30


# ---- the kit, for an overlay-only connector ----

def test_the_kit_runs_its_overlay_half_against_the_session_the_caller_opens(tmp_path):
    root = str(tmp_path / "k")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="k", name="K", ontology="software-architecture")
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    pg = connectors.get("postgres")
    fake = FakePostgres(_fixture("postgres-ledger.json"))
    result = conformance.run(pg, Project.standard(root), lambda name: pg.connect({"connection": fake, "schema": "public"}))
    assert [c["name"] for c in result["checks"]] == ["manifest", "interface", "overlay introspect", "overlay read-only", "overlay log"]
    assert result["passed"], conformance.report(result)
    bq = connectors.get("bigquery")
    fake_bq = FakeBigQuery(_fixture("bigquery-ledger.json"))
    result = conformance.run(bq, Project.standard(root), lambda name: bq.connect({"client": fake_bq, "project": "acme", "dataset": "ledger"}))
    assert result["passed"], conformance.report(result)


# ---- kg_read: the passthrough, off unless the deploy config allows it ----

def _deploy_config(root, overlay):
    cfg = deploy.starter("acme/ledger-kg", "https://github.com/acme/ledger-kg-store", "ledger-kg")
    if overlay is not None:
        cfg["overlay"] = overlay
    with open(os.path.join(root, deploy.NAME), "w", encoding="utf-8") as f:
        json.dump(cfg, f)


@pytest.fixture
def served(tmp_path):
    root = str(tmp_path / "served")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="served", name="Served", ontology="software-architecture")
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    ledger = str(tmp_path / "ledger.sqlite")
    con = sqlite3.connect(ledger)
    con.executescript(LEDGER_SQL)
    con.commit()
    con.close()
    return root, ledger


def _call(engine, name, **arguments):
    reply = engine.respond({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    result = reply["result"]
    return result["isError"], "".join(c["text"] for c in result["content"])


def test_kg_read_is_off_without_the_deploy_config_s_say_so(served):
    root, ledger = served
    engine = _engine(Project.standard(root))
    assert "kg_read" in {t["name"] for t in engine.TOOLS}
    error, text = _call(engine, "kg_read", sql="SELECT 1 AS one")
    assert error and "off" in text and "oto.deploy.json" in text, text
    _deploy_config(root, None)
    error, text = _call(engine, "kg_read", sql="SELECT 1 AS one")
    assert error and "off" in text and "native_read" in text, text
    _deploy_config(root, {"connector": "sqlite", "connection": {"endpoint": ledger, "auth": "file"}, "native_read": False})
    error, text = _call(engine, "kg_read", sql="SELECT 1 AS one")
    assert error and "off" in text, text
    assert "kg_read" not in engine.FORWARDABLE, "a dependency's passthrough is its own policy, never reached through kg_call"


def test_kg_read_answers_one_select_through_the_overlay_the_deploy_config_names(served):
    root, ledger = served
    _deploy_config(root, {"connector": "sqlite", "connection": {"endpoint": ledger, "auth": "file"}, "native_read": True})
    code, out = _cli("deploy", "check", "--project", root)
    assert code == 0, out
    engine = _engine(Project.standard(root))
    error, text = _call(engine, "kg_read", sql="SELECT account_id, sum(amount_cents) AS total FROM postings GROUP BY 1 ORDER BY 1")
    assert not error, text
    assert "account_id" in text and "total" in text and "1000" in text and "900" in text and "2 row(s)" in text, text
    assert "sqlite" in text and "read-only" in text, "where it was read, and that nothing could be written"
    error, text = _call(engine, "kg_read", sql="DELETE FROM postings")
    assert error and "read" in text.lower(), text
    error, text = _call(engine, "kg_read", sql="SELECT * FROM postings", limit=2)
    assert not error and "2 row(s)" in text and "more" in text, text
    from oto.serve import http as _http
    server = _http.Server(engine, "127.0.0.1", 0, project_root=root, identity=Project.standard(root).config()).start()
    try:
        status, _c, body = _get(server.url + "/api/read?sql=SELECT+count(*)+AS+n+FROM+postings")
        assert status == 200 and "3" in json.loads(body)["text"], body
    finally:
        server.stop()


def test_the_deploy_config_validates_the_overlay_section(served):
    root, ledger = served
    _deploy_config(root, {"connector": "neo4j", "native_read": True})
    code, out = _cli("deploy", "check", "--project", root)
    assert code == 1 and "overlay" in out and "neo4j" in out, out
    _deploy_config(root, {"connector": "postgres", "connection": {"endpoint": "postgresql://ledger@db.internal/ledger", "auth": "basic", "secret": "PGPASSWORD"}, "native_read": "yes"})
    code, out = _cli("deploy", "check", "--project", root)
    assert code == 1 and "native_read" in out, out
    _deploy_config(root, {"connector": "postgres", "connection": {"endpoint": "postgresql://ledger:hunter2@db.internal/ledger", "auth": "basic"}, "native_read": True})
    code, out = _cli("deploy", "check", "--project", root)
    assert code == 1 and ("secret" in out.lower() or "password" in out.lower()), "a password in the endpoint is refused: name the variable that holds it"
    _deploy_config(root, {"connector": "bigquery", "connection": {"endpoint": "acme", "auth": "adc", "database": "ledger"}, "native_read": True, "schema": "ledger"})
    code, out = _cli("deploy", "check", "--project", root)
    assert code == 0, out


# ---- live, where a Postgres is reachable (CI's postgres job) ----

LIVE = os.environ.get("OTO_POSTGRES_DSN")


@pytest.mark.skipif(not LIVE, reason="no Postgres reachable: set OTO_POSTGRES_DSN")
def test_the_postgres_overlay_against_a_live_store(tmp_path):
    pg = connectors.get("postgres")
    settings = {"dsn": LIVE, "schema": "public", "name": "ledger"}
    s = pg.connect(settings)
    try:
        cur = s["con"].cursor()
        for statement in [x.strip() for x in LEDGER_SQL.replace("INTEGER PRIMARY KEY", "integer PRIMARY KEY").replace("BIGINT", "bigint")
                          .replace("CHAR(3)", "char(3)").replace("TEXT", "timestamp").replace("date(posted_at)", "posted_at::date")
                          .replace("'2026-10-01 09:00'", "'2026-10-01 09:00:00'").replace("'2026-10-02 09:00'", "'2026-10-02 09:00:00'")
                          .replace("'2026-10-02 10:00'", "'2026-10-02 10:00:00'").split(";") if x.strip()]:
            cur.execute(statement)
        s["con"].commit()
    finally:
        pg.close(s)
    root = str(tmp_path / "live")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="live", name="Live", ontology="software-architecture")
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    result = conformance.run(pg, Project.standard(root), lambda name: pg.connect(settings))
    assert result["passed"], conformance.report(result)
    s = pg.connect(settings)
    try:
        schema = pg.introspect(s)
        names = {t["name"] for t in schema["tables"]}
        assert {"accounts", "postings", "daily_balances"} <= names
        postings = {c["name"]: c for c in next(t for t in schema["tables"] if t["name"] == "postings")["columns"]}
        assert postings["account_id"]["references"] == "accounts.account_id" and postings["posting_id"]["key"] == "primary"
        assert pg.native_read(s, "SELECT count(*) AS n FROM postings")["rows"] == [[3]]
        with pytest.raises(ValueError):
            pg.native_read(s, "DELETE FROM postings")
        assert pg.native_read(s, "SELECT count(*) AS n FROM postings")["rows"] == [[3]]
    finally:
        pg.close(s)
