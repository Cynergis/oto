"""Usage (roadmap C4): who reads a table and how, read from the store's query log, never guessed.

A query log is a list of statements with how often each ran and, when the store says, who ran it.
Each statement is read for the tables it touches and classified by a deterministic rule as
transactional (reads by key, writes: an application serving a user) or analytical (aggregates,
groupings, windows, scans: a report or a model). One `Usage` per reader and table, its kind the
calls-weighted majority, its evidence `query_log`, `use_of` the table and `used_by` the component,
team or role the person maps the principal to. The statement text is hashed into the usage
document and never kept, so a log can be read without copying what the queries said. The catalog
says what tables exist; a statement on a table the graph lacks is a gap. The proposal goes through
the gates like any other change, and a use whose kind changed is a supersession the merge refuses."""
import contextlib
import hashlib
import io
import json
import os
import sqlite3

import pytest

from oto import connectors, usage
from oto.cli import main
from oto.curate import session
from oto.project import Project
from oto.scaffold import init

HERE = os.path.dirname(__file__)
FIXTURES = os.path.join(HERE, "fixtures", "usage")
LOG = os.path.join(FIXTURES, "ledger-log.json")
FLIPPED = os.path.join(FIXTURES, "ledger-log-flipped.json")
PLAIN = os.path.join(FIXTURES, "plain.sql")

LEDGER_SQL = """
CREATE TABLE accounts (account_id INTEGER PRIMARY KEY, currency CHAR(3) NOT NULL);
CREATE TABLE postings (posting_id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(account_id),
  amount_cents BIGINT NOT NULL, posted_at TEXT);
CREATE VIEW daily_balances AS SELECT account_id, date(posted_at) AS day, sum(amount_cents) AS balance_cents FROM postings GROUP BY 1, 2;
"""


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _gates(root, proposal, note):
    for step in (("curate", "start"), ("curate", "add", "--from", proposal), ("curate", "check"),
                 ("curate", "apply", "--by", "Sam Lee", "--note", note)):
        code, out = _cli(*step, "--project", root)
        assert code == 0 and "not in the document" not in out, (step, out)
    code, out = _cli("build", "--project", root)
    assert code == 0, out


@pytest.fixture
def described(tmp_path):
    """A data project whose estate declares the ledger store, the payment API component and the
    compliance role, with the catalog introspected and applied."""
    db = str(tmp_path / "ledger.sqlite")
    con = sqlite3.connect(db)
    con.executescript(LEDGER_SQL)
    con.commit()
    con.close()
    root = str(tmp_path / "described")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="described", name="The ledger, described", ontology="data", empty=True)
    seed = os.path.join(root, "seed.json")
    with open(seed, "w", encoding="utf-8") as f:
        json.dump({"source_doc": "estate", "as_of": "2026-10-01", "nodes": [
            {"id": "environment.production", "type": "Environment", "label": "Production", "attributes": {}},
            {"id": "datastore.ledger", "type": "DataStore", "label": "Ledger database", "attributes": {}},
            {"id": "system.ledger", "type": "System", "label": "Ledger", "attributes": {}},
            {"id": "component.payment-api", "type": "Component", "label": "Payment API", "attributes": {}},
            {"id": "role.r-compliance", "type": "Role", "label": "Compliance", "attributes": {}}],
            "edges": [{"from": "datastore.ledger", "rel": "runs_in", "to": "environment.production"},
                      {"from": "component.payment-api", "rel": "runs_in", "to": "environment.production"},
                      {"from": "component.payment-api", "rel": "part_of", "to": "system.ledger"}]}, f)
    _gates(root, seed, "the estate")
    code, out = _cli("data", "introspect", "--path", db, "--store", "datastore.ledger", "--at", "2026-10-26", "--project", root)
    assert code == 0, out
    _gates(root, os.path.join(root, "proposals", "schema-ledger.json"), "the schema")
    return root, db


# ---- the classifier and the shapes, as functions ----

def test_the_classifier_is_a_deterministic_rule():
    t, a = "transactional", "analytical"
    assert usage.classify("SELECT * FROM postings WHERE account_id = $1") == t, "a read by key"
    assert usage.classify("SELECT p.* FROM postings p JOIN accounts a ON a.account_id = p.account_id WHERE p.posting_id = 10 LIMIT 1") == t
    assert usage.classify("INSERT INTO postings SELECT * FROM staging") == t and usage.classify("UPDATE accounts SET currency = 'CAD' WHERE account_id = 1") == t
    assert usage.classify("DELETE FROM postings WHERE posting_id = 1") == t and usage.classify("MERGE INTO postings USING s ON true WHEN MATCHED THEN DELETE") == t
    assert usage.classify("SELECT account_id, sum(amount_cents) FROM postings GROUP BY 1") == a, "an aggregate"
    assert usage.classify("SELECT count(*) FROM postings WHERE posted_at > '2026-01-01'") == a
    assert usage.classify("SELECT account_id, amount_cents, sum(amount_cents) OVER (PARTITION BY account_id) FROM postings") == a, "a window"
    assert usage.classify("SELECT DISTINCT currency FROM accounts") == a and usage.classify("SELECT * FROM postings") == a, "a scan"
    assert usage.classify("SELECT * FROM postings WHERE posted_at >= '2026-01-01'") == a, "a range over many rows"
    assert usage.classify("SELECT 1") is None and usage.classify("SET search_path TO public") is None and usage.classify("BEGIN") is None, "nothing read is no use"
    assert usage.classify("SELECT * FROM pg_stat_statements") is None and usage.classify("SELECT * FROM information_schema.tables") is None, "the store's own tables are not the estate's"


def test_a_statement_shape_is_hashed_and_its_text_never_kept():
    one = "SELECT posting_id FROM postings WHERE account_id = 42 AND note <> 'secret-token-123'"
    two = "select posting_id\n  from postings where account_id = 7 and note <> 'other'  -- a comment"
    assert usage.shape(one) == usage.shape(two) == "select posting_id from postings where account_id = ? and note <> ?"
    assert usage.shape_hash(one) == usage.shape_hash(two) == hashlib.sha256(usage.shape(one).encode("utf-8")).hexdigest()[:12]
    assert "secret" not in usage.shape(one) and "42" not in usage.shape(one)
    assert usage.tables_of(one) == {"reads": ["postings"], "writes": []}
    assert usage.tables_of("INSERT INTO postings SELECT * FROM staging s JOIN accounts a ON true") == {"reads": ["staging", "accounts"], "writes": ["postings"]}
    assert usage.tables_of("SELECT * FROM `acme.ledger.postings` WHERE account_id = 1") == {"reads": ["postings"], "writes": []}, "a qualified name is the table's own"
    assert usage.tables_of("WITH x AS (SELECT 1) SELECT * FROM x") == {"reads": [], "writes": []}, "a CTE is not a table"
    assert usage.tables_of("DELETE FROM postings WHERE posting_id = 1") == {"reads": [], "writes": ["postings"]}, "a delete writes"


def test_the_log_file_reader_takes_json_jsonl_and_plain_statements(tmp_path):
    entries = usage.read_log_file(LOG)
    assert len(entries) == 9 and entries[0] == {"by": "payment_api", "sql": "SELECT posting_id, amount_cents FROM postings WHERE account_id = 42 AND note <> 'secret-token-123'", "calls": 1200}
    jsonl = tmp_path / "log.jsonl"
    jsonl.write_text('{"sql": "SELECT * FROM postings WHERE posting_id = 1", "user": "api"}\n\n{"query": "SELECT count(*) FROM accounts", "calls": "3"}\n', encoding="utf-8")
    assert usage.read_log_file(str(jsonl)) == [{"by": "api", "sql": "SELECT * FROM postings WHERE posting_id = 1", "calls": 1},
                                               {"by": None, "sql": "SELECT count(*) FROM accounts", "calls": 3}], "user or by, query or sql, calls 1 when unsaid"
    plain = usage.read_log_file(PLAIN)
    assert [e["sql"] for e in plain] == ["SELECT * FROM postings WHERE posting_id = 10", "SELECT count(*) FROM accounts", "SELECT 1"]
    assert all(e["by"] is None and e["calls"] == 1 for e in plain)
    with pytest.raises(usage.UsageError):
        usage.read_log_file(str(tmp_path / "missing.json"))
    bad = tmp_path / "bad.json"
    bad.write_text('{"not": "a list"}', encoding="utf-8")
    with pytest.raises(usage.UsageError) as e:
        usage.read_log_file(str(bad))
    assert "list" in str(e.value)


def test_uses_are_one_per_reader_and_table_with_the_calls_weighted_kind():
    uses, left_out = usage.uses(usage.read_log_file(LOG))
    by_key = {(u["reader"], u["table"]): u for u in uses}
    assert set(by_key) == {("payment_api", "postings"), ("payment_api", "accounts"), ("compliance", "daily_balances"), ("compliance", "postings"),
                           ("compliance", "accounts"), ("etl", "postings"), ("etl", "staging_settlements"), ("analyst", "postings")}
    api = by_key[("payment_api", "postings")]
    assert api["kind"] == "transactional" and api["calls"] == 1500 and len(api["statements"]) == 1, "two statements of one shape are one shape"
    assert api["statements"][0] == {"hash": usage.shape_hash("SELECT posting_id, amount_cents FROM postings WHERE account_id = 1 AND note <> 'x'"), "kind": "transactional", "calls": 1500}
    assert by_key[("compliance", "postings")]["kind"] == "analytical" and by_key[("etl", "postings")]["kind"] == "transactional", "a write is transactional"
    assert by_key[("analyst", "postings")]["kind"] == "analytical"
    assert left_out == {"no_table": 1, "system": 1}, left_out
    mixed = usage.uses([{"by": "x", "sql": "SELECT * FROM t WHERE id = 1", "calls": 10}, {"by": "x", "sql": "SELECT count(*) FROM t", "calls": 10}])[0]
    assert mixed[0]["kind"] == "transactional", "a tie is transactional: the reader you must tell before a change"
    anonymous = usage.uses([{"by": None, "sql": "SELECT * FROM t WHERE id = 1", "calls": 1}])[0]
    assert anonymous[0]["reader"] is None


# ---- the command ----

def test_usage_from_a_log_file_writes_the_document_and_a_proposal_without_the_query_text(described):
    root, _db = described
    code, out = _cli("data", "usage", "--log", LOG, "--store", "datastore.ledger", "--reader", "payment_api=component.payment-api",
                     "--reader", "compliance=role.r-compliance", "--at", "2026-10-27", "--project", root)
    assert code == 0, out
    assert "7 use(s)" in out and "usage-ledger-log" in out and "curate add" in out, out
    assert "staging_settlements" in out and "graph lacks" in out, "a statement on a table the graph lacks is a gap"
    assert "etl" in out and "analyst" in out and "not mapped" in out, "an unmapped principal is a gap, said with how to map it"
    text = open(os.path.join(root, "build", "documents", "usage-ledger-log.md"), encoding="utf-8").read()
    assert text.startswith("# Usage of ledger from the log") and "## payment_api uses postings (transactional)" in text and "1500 call(s)" in text, text
    assert "## compliance uses daily_balances (analytical)" in text and "## analyst uses postings (analytical)" in text
    assert "- payment_api: component.payment-api" in text and "- analyst: not mapped" in text
    for secret in ("secret-token-123", "amount_cents", "account_id = 42", "SELECT"):
        assert secret not in text, "the statement text is hashed, never kept: %s" % secret
    assert usage.shape_hash("SELECT posting_id, amount_cents FROM postings WHERE account_id = 42 AND note <> 'secret-token-123'") in text
    assert os.path.exists(os.path.join(root, "archive", "usage-ledger-log.md"))
    with open(os.path.join(root, "proposals", "usage-ledger-log.json"), encoding="utf-8") as f:
        proposal = json.load(f)
    assert "secret-token-123" not in json.dumps(proposal) and "SELECT" not in json.dumps(proposal)
    assert proposal["source_doc"] == "usage-ledger-log" and proposal["as_of"] == "2026-10-27"
    nodes = {n["id"]: n for n in proposal["nodes"]}
    assert nodes["document.usage-ledger-log"]["attributes"] == {"kind": "usage"}
    api = nodes["usage.payment-api-postings"]
    assert api["type"] == "Usage" and api["label"] == "payment_api uses postings"
    assert api["attributes"] == {"kind": "transactional", "evidence": "query_log"}
    assert api["evidence"] == [{"doc": "usage-ledger-log", "where": "payment_api", "quote": "payment_api uses postings (transactional)"}]
    assert "calls" not in api["attributes"] and "1500" not in api["summary"], "counts change every read; they are the document's, so the fact holds across reads"
    assert nodes["usage.compliance-daily-balances"]["attributes"] == {"kind": "analytical", "evidence": "query_log"}
    assert "usage.etl-staging-settlements" not in nodes and not any(n["type"] == "Table" for n in proposal["nodes"])
    assert len([n for n in proposal["nodes"] if n["type"] == "Usage"]) == 7
    edges = {(e["from"], e["rel"], e["to"]) for e in proposal["edges"]}
    assert ("usage.payment-api-postings", "use_of", "table.ledger-postings") in edges
    assert ("usage.payment-api-postings", "used_by", "component.payment-api") in edges
    assert ("usage.compliance-daily-balances", "use_of", "table.ledger-daily-balances") in edges
    assert ("usage.compliance-daily-balances", "used_by", "role.r-compliance") in edges
    assert ("usage.etl-postings", "use_of", "table.ledger-postings") in edges
    assert not any(e["from"] == "usage.etl-postings" and e["rel"] == "used_by" for e in proposal["edges"]), "unmapped is unattributed, not invented"


def test_the_reader_map_can_live_in_the_project_config_and_must_name_nodes_the_graph_holds(described):
    root, _db = described
    config_path = os.path.join(root, "project.config.json")
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    config["usage"] = {"readers": {"payment_api": "component.payment-api", "analyst": "role.r-compliance"}}
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    code, out = _cli("data", "usage", "--log", LOG, "--store", "datastore.ledger", "--reader", "compliance=role.r-compliance", "--at", "2026-10-27", "--project", root)
    assert code == 0, out
    gaps = out.split("gaps")[-1] if "gaps" in out else ""
    assert "analyst" not in gaps and "etl" in gaps, gaps
    with open(os.path.join(root, "proposals", "usage-ledger-log.json"), encoding="utf-8") as f:
        edges = {(e["from"], e["rel"], e["to"]) for e in json.load(f)["edges"]}
    assert ("usage.analyst-postings", "used_by", "role.r-compliance") in edges and ("usage.payment-api-postings", "used_by", "component.payment-api") in edges
    code, out = _cli("data", "usage", "--log", LOG, "--store", "datastore.ledger", "--reader", "etl=component.nope", "--at", "2026-10-27", "--project", root)
    assert code == 1 and "component.nope" in out, "a reader map is the person's claim and must resolve"
    code, out = _cli("data", "usage", "--log", LOG, "--store", "datastore.ledger", "--reader", "etl", "--at", "2026-10-27", "--project", root)
    assert code == 1 and "principal=node.id" in out, out


def test_usage_goes_through_the_gates_and_a_changed_kind_is_a_supersession(described):
    root, _db = described
    code, out = _cli("data", "usage", "--log", LOG, "--store", "datastore.ledger", "--reader", "payment_api=component.payment-api",
                     "--reader", "compliance=role.r-compliance", "--at", "2026-10-27", "--project", root)
    assert code == 0, out
    _gates(root, os.path.join(root, "proposals", "usage-ledger-log.json"), "the ledger's usage")
    graph = session.live(Project.standard(root))
    kinds = {}
    for n in graph["nodes"]:
        kinds[n["type"]] = kinds.get(n["type"], 0) + 1
    assert kinds["Usage"] == 7 and kinds["Table"] == 3 and kinds["Document"] == 2, kinds
    code, out = _cli("query", "--project", root, "ask", "DT3", "TABLE=table.ledger-postings")
    assert code == 0 and "status: answered" in out and "Payment API" in out and "u.kind=transactional" in out and "u.evidence=query_log" in out, out
    assert "Compliance" in out and "u.kind=analytical" in out
    code, out = _cli("ontology", "check", "--project", root)
    assert code == 0 and "every node satisfies them" in out, out
    before = session.live(Project.standard(root))
    code, out = _cli("data", "usage", "--log", LOG, "--store", "datastore.ledger", "--reader", "payment_api=component.payment-api",
                     "--reader", "compliance=role.r-compliance", "--at", "2026-10-28", "--project", root)
    assert code == 0, out
    _gates(root, os.path.join(root, "proposals", "usage-ledger-log.json"), "the same log")
    after = session.live(Project.standard(root))
    assert len(after["nodes"]) == len(before["nodes"]) and len(after["edges"]) == len(before["edges"]), "the same log twice is one set of facts"
    code, out = _cli("data", "usage", "--log", FLIPPED, "--store", "datastore.ledger", "--reader", "payment_api=component.payment-api", "--at", "2026-10-29", "--project", root)
    assert code == 0 and "1 changed" in out and "usage.payment-api-postings" in out and "supersession" in out, "a kind that flipped is said before the gates see it"
    code, out = _cli("curate", "start", "--project", root)
    assert code == 0, out
    code, out = _cli("curate", "add", "--from", os.path.join(root, "proposals", "usage-ledger-log.json"), "--project", root)
    assert code == 1 and "supersession" in out and "usage.payment-api-postings" in out, out


def test_usage_through_the_overlay_connectors(described, tmp_path):
    root, db = described
    code, out = _cli("data", "usage", "--connector", "sqlite", "--path", db, "--store", "datastore.ledger", "--at", "2026-10-27", "--project", root)
    assert code == 1 and "no query log" in out and "--log" in out, "SQLite keeps no log: the file reader is the way"

    class FakeCursor:
        def __init__(self, rows):
            self.rows, self.description = rows, None

        def execute(self, sql, params=None):
            text = sql.strip()
            if "pg_extension" in text:
                self.rows = [(1,)]
            elif "pg_stat_statements" in text:
                assert "pg_roles" in text and "rolname" in text, "the log names who ran each statement"
                self.rows = [("payment_api", "SELECT * FROM postings WHERE account_id = $1", 1240, 310.5),
                             ("compliance", "SELECT account_id, sum(amount_cents) FROM postings GROUP BY 1", 12, 88.0),
                             ("ops", "SELECT * FROM pg_stat_statements", 1, 1.0)]
            else:
                raise AssertionError(text)

        def fetchall(self):
            return list(self.rows)

        def close(self):
            pass

    class FakePostgres:
        def cursor(self):
            return FakeCursor([])

        def close(self):
            pass

    done = usage.usage(Project.standard(root), connector_name="postgres", store_id="datastore.ledger", at="2026-10-27",
                       readers={"payment_api": "component.payment-api", "compliance": "role.r-compliance"},
                       settings={"connection": FakePostgres(), "schema": "public", "name": "ledger"})
    assert done["uses"] == 2 and done["doc"] == "usage-ledger-postgres" and done["gaps"] == [], done
    with open(done["proposal"], encoding="utf-8") as f:
        proposal = json.load(f)
    nodes = {n["id"]: n for n in proposal["nodes"]}
    assert nodes["usage.payment-api-postings"]["attributes"] == {"kind": "transactional", "evidence": "query_log"}
    assert nodes["usage.compliance-postings"]["attributes"] == {"kind": "analytical", "evidence": "query_log"}
    assert "account_id" not in json.dumps(proposal)
    text = open(done["document"], encoding="utf-8").read()
    assert "# Usage of ledger from the postgres query log" in text and "1240 call(s)" in text and "SELECT" not in text


def test_usage_refuses_what_it_cannot_cite(described, tmp_path):
    root, _db = described
    code, out = _cli("data", "usage", "--store", "datastore.ledger", "--at", "2026-10-27", "--project", root)
    assert code == 1 and "--log" in out and "--connector" in out, out
    code, out = _cli("data", "usage", "--log", LOG, "--connector", "postgres", "--store", "datastore.ledger", "--at", "2026-10-27", "--project", root)
    assert code == 1 and "one source" in out, out
    code, out = _cli("data", "usage", "--log", LOG, "--store", "datastore.ledger", "--project", root)
    assert code == 1 and "--at" in out, "the date is never defaulted"
    code, out = _cli("data", "usage", "--log", LOG, "--store", "datastore.nope", "--at", "2026-10-27", "--project", root)
    assert code == 1 and "datastore.nope" in out, out
    code, out = _cli("data", "usage", "--log", str(tmp_path / "missing.json"), "--store", "datastore.ledger", "--at", "2026-10-27", "--project", root)
    assert code == 1 and "missing.json" in out, out
    plain = str(tmp_path / "plain")
    with contextlib.redirect_stdout(io.StringIO()):
        init(plain, slug="plain", name="Plain", ontology="communication")
    code, out = _cli("data", "usage", "--log", LOG, "--store", "datastore.ledger", "--at", "2026-10-27", "--project", plain)
    assert code == 1 and "Usage" in out, out
    assert not os.path.exists(os.path.join(root, "proposals", "usage-ledger-log.json"))


def test_the_product_vocabulary_knows_a_usage_document():
    with open(os.path.join(HERE, "..", "oto", "ontologies", "product", "ontology.config.json"), encoding="utf-8") as f:
        kinds = json.load(f)["attributes"]["Document"]["kind"]["type"]
    assert "|usage|" in kinds, kinds
    with open(os.path.join(HERE, "..", "oto", "ontologies", "product", "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["release"] >= 13 and any(c["release"] == 13 and "usage" in c["note"] for c in manifest["changelog"])


def test_the_store_logs_say_who_ran_each_statement():
    """The overlays' query_log carries the principal, so a use can be attributed."""
    from oto.connectors import bigquery as bq_module, postgres as pg_module
    assert "rolname" in pg_module.LOG_SQL and "pg_roles" in pg_module.LOG_SQL
    assert "user_email" in bq_module.LOG_FIELDS
