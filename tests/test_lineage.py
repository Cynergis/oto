"""Lineage (roadmap C3): what loads a table and where the rows come from, read from what the
ETL already says.

Two readers, both deterministic: a dbt manifest (`target/manifest.json`), whose models, seeds and
sources are the jobs, the tables they load and the feeds behind them; and SQL files, one job per
file, whose INSERT, MERGE, CREATE ... AS and COPY statements say what is written and whose FROM and
JOIN say what is read. Either becomes a lineage document in the corpus and a proposal in the data
vocabulary: `LoadJob` and `Feed` nodes quoting their lines, `loaded_by` and `sourced_from` edges to
tables the graph already holds. The catalog says what tables exist (`oto data introspect`); lineage
says how they are loaded, so a job that loads a table the graph lacks is a gap to report, never a
table to invent. The proposal goes through the gates like any other change."""
import contextlib
import io
import json
import os
import shutil
import sqlite3

import pytest

from oto.packs.data import lineage
from oto.cli import main
from oto.curate import session
from oto.project import Project
from oto.scaffold import init

HERE = os.path.dirname(__file__)
FIXTURES = os.path.join(HERE, "fixtures", "lineage")
MANIFEST = os.path.join(FIXTURES, "dbt-manifest.json")
SQL_DIR = os.path.join(FIXTURES, "sql")

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
    """A data project whose estate declares the ledger store and whose catalog is introspected and
    applied: the tables exist before lineage says how they are loaded."""
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
            {"id": "datastore.ledger", "type": "DataStore", "label": "Ledger database", "attributes": {}}],
            "edges": [{"from": "datastore.ledger", "rel": "runs_in", "to": "environment.production"}]}, f)
    _gates(root, seed, "the store")
    code, out = _cli("data", "introspect", "--path", db, "--store", "datastore.ledger", "--at", "2026-10-26", "--project", root)
    assert code == 0, out
    _gates(root, os.path.join(root, "proposals", "schema-ledger.json"), "the schema")
    return root


# ---- the readers, as functions ----

def test_the_dbt_reader_turns_models_seeds_and_sources_into_jobs_and_feeds():
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    read = lineage.read_dbt(manifest)
    assert read["tool"] == "dbt" and read["about"] == "dbt 1.8.0, project ledger, generated 2026-10-20T02:00:00Z"
    jobs = {j["name"]: j for j in read["jobs"]}
    assert set(jobs) == {"postings", "daily_balances", "unknown_report", "accounts"}, "an ephemeral model is no job and a test is nothing here"
    postings = jobs["postings"]
    assert postings["tool"] == "dbt" and postings["schedule"] == "nightly at 02:00" and postings["loads"] == ["postings"]
    assert postings["sources"] == [{"feed": "custodian.settlements"}, {"table": "accounts"}], "the ephemeral model collapses to the source behind it"
    assert jobs["daily_balances"]["schedule"] == "nightly at 03:00", "config.meta.schedule counts as meta.schedule"
    assert jobs["daily_balances"]["sources"] == [{"table": "postings"}]
    assert jobs["accounts"]["sources"] == [{"feed": "seed accounts"}], "a seed is a table loaded from a file"
    feeds = {f["name"]: f for f in read["feeds"]}
    assert feeds["custodian.settlements"]["kind"] == "file", "the loader says a file drop"
    assert feeds["custodian.settlements"]["summary"] == "The custodian's nightly file of settled payments."
    assert feeds["seed accounts"]["kind"] == "file" and "seeds/accounts.csv" in feeds["seed accounts"]["summary"]


def test_the_dbt_reader_refuses_what_is_not_a_manifest():
    with pytest.raises(lineage.LineageError) as e:
        lineage.read_dbt({"models": []})
    assert "manifest" in str(e.value)


def test_the_sql_scanner_finds_what_a_file_writes_and_reads_and_ignores_comments_literals_and_ctes():
    with open(os.path.join(SQL_DIR, "posting_load.sql"), encoding="utf-8") as f:
        job = lineage.scan_sql(f.read(), "posting_load.sql")
    assert job["name"] == "posting_load" and job["tool"] == "settlement-job" and job["schedule"] == "nightly at 02:00"
    assert job["loads"] == ["postings"], "a table written and read in the same file is the job's own staging, not a load"
    assert job["sources"] == [{"feed": "s3://custodian/settlements"}, {"table": "accounts"}], job["sources"]
    assert "nowhere" not in json.dumps(job) and "elsewhere" not in json.dumps(job), "comments and string literals are not SQL"
    with open(os.path.join(SQL_DIR, "balance_rollup.sql"), encoding="utf-8") as f:
        job = lineage.scan_sql(f.read(), "balance_rollup.sql")
    assert job["tool"] == "sql" and job["schedule"] == "nightly at 03:00"
    assert job["loads"] == ["daily_balances"] and job["sources"] == [{"table": "postings"}], "a CTE is not a table"
    feeds = {f["name"]: f for f in lineage.scan_sql(open(os.path.join(SQL_DIR, "posting_load.sql"), encoding="utf-8").read(), "x.sql")["feeds"]}
    assert feeds["s3://custodian/settlements"]["kind"] == "file"
    assert lineage.scan_sql("SELECT 1;", "nothing.sql")["loads"] == []
    job = lineage.scan_sql("CREATE TABLE snap AS SELECT * FROM src JOIN UNNEST(arr) u ON true; DELETE FROM gone WHERE x = 1;", "c.sql")
    assert job["loads"] == ["snap"] and job["sources"] == [{"table": "src"}], "a function call is not a table and a DELETE is not a load"


# ---- the command ----

def test_lineage_from_dbt_writes_the_document_and_a_proposal_cited_to_it_and_reports_the_gaps(described):
    root = described
    code, out = _cli("data", "lineage", "--dbt", MANIFEST, "--store", "datastore.ledger", "--at", "2026-10-27", "--project", root)
    assert code == 0, out
    assert "3 job(s)" in out and "2 feed(s)" in out and "lineage-ledger-dbt" in out and "curate add" in out, out
    assert "unknown_report" in out and "graph lacks" in out, "a job that loads a table the graph lacks is a gap, reported and not invented"
    text = open(os.path.join(root, "build", "documents", "lineage-ledger-dbt.md"), encoding="utf-8").read()
    assert text.startswith("# Lineage of ledger from dbt") and "dbt 1.8.0" in text
    assert "## postings (dbt)" in text and "- loads postings" in text and "- sourced from feed custodian.settlements" in text and "- schedule nightly at 02:00" in text, text
    assert os.path.exists(os.path.join(root, "archive", "lineage-ledger-dbt.md"))
    with open(os.path.join(root, "proposals", "lineage-ledger-dbt.json"), encoding="utf-8") as f:
        proposal = json.load(f)
    assert proposal["source_doc"] == "lineage-ledger-dbt" and proposal["as_of"] == "2026-10-27"
    nodes = {n["id"]: n for n in proposal["nodes"]}
    assert nodes["document.lineage-ledger-dbt"]["attributes"] == {"kind": "lineage"}
    job = nodes["loadjob.dbt-postings"]
    assert job["type"] == "LoadJob" and job["attributes"] == {"tool": "dbt", "schedule": "nightly at 02:00"}
    assert job["evidence"] == [{"doc": "lineage-ledger-dbt", "where": "postings", "quote": "postings (dbt)"}]
    assert nodes["loadjob.dbt-daily-balances"]["attributes"] == {"tool": "dbt", "schedule": "nightly at 03:00"}
    assert "schedule" not in nodes["loadjob.dbt-accounts"]["attributes"], "no schedule is no schedule, not an empty one"
    feed = nodes["feed.custodian-settlements"]
    assert feed["type"] == "Feed" and feed["attributes"] == {"kind": "file"} and feed["summary"] == "The custodian's nightly file of settled payments."
    assert feed["evidence"] == [{"doc": "lineage-ledger-dbt", "where": "feeds", "quote": "custodian.settlements (file)"}]
    assert nodes["feed.dbt-seed-accounts"]["attributes"] == {"kind": "file"}
    assert "loadjob.dbt-unknown-report" not in nodes and "loadjob.dbt-stg-settlements" not in nodes
    assert not any(n["type"] == "Table" for n in proposal["nodes"]), "the catalog says what tables exist; lineage never invents one"
    edges = {(e["from"], e["rel"], e["to"]) for e in proposal["edges"]}
    assert ("table.ledger-postings", "loaded_by", "loadjob.dbt-postings") in edges
    assert ("loadjob.dbt-postings", "sourced_from", "feed.custodian-settlements") in edges
    assert ("loadjob.dbt-postings", "sourced_from", "table.ledger-accounts") in edges
    assert ("table.ledger-daily-balances", "loaded_by", "loadjob.dbt-daily-balances") in edges
    assert ("loadjob.dbt-daily-balances", "sourced_from", "table.ledger-postings") in edges
    assert ("table.ledger-accounts", "loaded_by", "loadjob.dbt-accounts") in edges
    assert ("loadjob.dbt-accounts", "sourced_from", "feed.dbt-seed-accounts") in edges
    assert not any("unknown" in e["from"] or "unknown" in e["to"] for e in proposal["edges"])


def test_lineage_from_sql_files_is_one_job_per_file(described):
    root = described
    code, out = _cli("data", "lineage", "--sql", SQL_DIR, "--store", "datastore.ledger", "--at", "2026-10-27", "--project", root)
    assert code == 0, out
    assert "2 job(s)" in out and "1 feed(s)" in out and "audit_export" in out and "graph lacks" in out, out
    text = open(os.path.join(root, "build", "documents", "lineage-ledger-sql.md"), encoding="utf-8").read()
    assert "# Lineage of ledger from SQL" in text and "## posting_load (settlement-job)" in text and "## balance_rollup (sql)" in text, text
    assert "- sourced from feed s3://custodian/settlements" in text and "- sourced from table accounts" in text
    with open(os.path.join(root, "proposals", "lineage-ledger-sql.json"), encoding="utf-8") as f:
        proposal = json.load(f)
    nodes = {n["id"]: n for n in proposal["nodes"]}
    assert nodes["loadjob.posting-load"]["attributes"] == {"tool": "settlement-job", "schedule": "nightly at 02:00"}
    assert nodes["loadjob.balance-rollup"]["attributes"] == {"tool": "sql", "schedule": "nightly at 03:00"}
    feed = nodes["feed.s3-custodian-settlements"]
    assert feed["attributes"] == {"kind": "file"} and feed["label"] == "s3://custodian/settlements", "a path names its own feed, apart from a dbt source's"
    edges = {(e["from"], e["rel"], e["to"]) for e in proposal["edges"]}
    assert ("table.ledger-postings", "loaded_by", "loadjob.posting-load") in edges
    assert ("loadjob.posting-load", "sourced_from", "feed.s3-custodian-settlements") in edges
    assert ("loadjob.posting-load", "sourced_from", "table.ledger-accounts") in edges
    assert ("table.ledger-daily-balances", "loaded_by", "loadjob.balance-rollup") in edges
    assert ("loadjob.balance-rollup", "sourced_from", "table.ledger-postings") in edges
    assert "loadjob.audit-export" not in nodes
    one = str(os.path.join(SQL_DIR, "balance_rollup.sql"))
    code, out = _cli("data", "lineage", "--sql", one, "--store", "datastore.ledger", "--at", "2026-10-27", "--project", root)
    assert code == 0 and "1 job(s)" in out, out


def test_lineage_goes_through_the_gates_and_the_graph_answers_where_a_table_comes_from(described):
    root = described
    code, out = _cli("data", "lineage", "--dbt", MANIFEST, "--store", "datastore.ledger", "--at", "2026-10-27", "--project", root)
    assert code == 0, out
    _gates(root, os.path.join(root, "proposals", "lineage-ledger-dbt.json"), "the ledger's lineage")
    graph = session.live(Project.standard(root))
    kinds = {}
    for n in graph["nodes"]:
        kinds[n["type"]] = kinds.get(n["type"], 0) + 1
    assert kinds["LoadJob"] == 3 and kinds["Feed"] == 2 and kinds["Table"] == 3 and kinds["Document"] == 2, kinds
    code, out = _cli("query", "--project", root, "ask", "DT2", "TABLE=table.ledger-daily-balances")
    assert code == 0 and "status: answered" in out and "dbt" in out and "nightly at 03:00" in out and "postings" in out, out
    code, out = _cli("query", "--project", root, "ask", "DT6", "FEED=feed.custodian-settlements")
    assert code == 0 and "status: answered" in out and "postings" in out, out
    code, out = _cli("ontology", "check", "--project", root)
    assert code == 0 and "every node satisfies them" in out, out
    code, out = _cli("audit", "log", "--project", root)
    assert code == 0 and "the ledger's lineage" in out
    before = session.live(Project.standard(root))
    code, out = _cli("data", "lineage", "--dbt", MANIFEST, "--store", "datastore.ledger", "--at", "2026-10-28", "--project", root)
    assert code == 0, out
    _gates(root, os.path.join(root, "proposals", "lineage-ledger-dbt.json"), "the same lineage")
    after = session.live(Project.standard(root))
    assert len(after["nodes"]) == len(before["nodes"]) and len(after["edges"]) == len(before["edges"]), "the same manifest twice is one set of facts"
    code, out = _cli("data", "lineage", "--sql", SQL_DIR, "--store", "datastore.ledger", "--at", "2026-10-28", "--project", root)
    assert code == 0, out
    _gates(root, os.path.join(root, "proposals", "lineage-ledger-sql.json"), "the SQL's lineage")
    code, out = _cli("ontology", "check", "--project", root)
    assert code == 0 and "every node satisfies them" in out, "two readers on one store are two sets of facts, each through the gates; reconciling them is a person's call"
    graph = session.live(Project.standard(root))
    assert {n["id"] for n in graph["nodes"] if n["type"] == "Feed"} == {"feed.custodian-settlements", "feed.dbt-seed-accounts", "feed.s3-custodian-settlements"}


def test_lineage_refuses_what_it_cannot_cite(tmp_path, described):
    root = described
    code, out = _cli("data", "lineage", "--store", "datastore.ledger", "--at", "2026-10-27", "--project", root)
    assert code == 1 and "--dbt" in out and "--sql" in out, out
    code, out = _cli("data", "lineage", "--dbt", MANIFEST, "--sql", SQL_DIR, "--store", "datastore.ledger", "--at", "2026-10-27", "--project", root)
    assert code == 1 and "one reader" in out, out
    code, out = _cli("data", "lineage", "--dbt", MANIFEST, "--store", "datastore.ledger", "--project", root)
    assert code == 1 and "--at" in out, "the date is never defaulted"
    code, out = _cli("data", "lineage", "--dbt", MANIFEST, "--store", "datastore.nope", "--at", "2026-10-27", "--project", root)
    assert code == 1 and "datastore.nope" in out, out
    code, out = _cli("data", "lineage", "--dbt", str(tmp_path / "missing.json"), "--store", "datastore.ledger", "--at", "2026-10-27", "--project", root)
    assert code == 1 and "missing.json" in out, out
    bad = tmp_path / "bad.json"
    bad.write_text("{\"models\": []}", encoding="utf-8")
    code, out = _cli("data", "lineage", "--dbt", str(bad), "--store", "datastore.ledger", "--at", "2026-10-27", "--project", root)
    assert code == 1 and "manifest" in out, out
    empty = tmp_path / "empty-sql"
    empty.mkdir()
    code, out = _cli("data", "lineage", "--sql", str(empty), "--store", "datastore.ledger", "--at", "2026-10-27", "--project", root)
    assert code == 1 and "no .sql" in out, out
    plain = str(tmp_path / "plain")
    with contextlib.redirect_stdout(io.StringIO()):
        init(plain, slug="plain", name="Plain", ontology="organization-process")
    code, out = _cli("data", "lineage", "--dbt", MANIFEST, "--store", "datastore.ledger", "--at", "2026-10-27", "--project", plain)
    assert code == 1 and "LoadJob" in out, out
    assert not os.path.exists(os.path.join(root, "proposals", "lineage-ledger-dbt.json"))


def test_the_product_vocabulary_knows_a_lineage_document():
    with open(os.path.join(HERE, "..", "oto", "ontologies", "product", "ontology.config.json"), encoding="utf-8") as f:
        kinds = json.load(f)["attributes"]["Document"]["kind"]["type"]
    assert "|lineage|" in kinds or kinds.endswith("|lineage"), kinds
    with open(os.path.join(HERE, "..", "oto", "ontologies", "product", "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["release"] >= 12 and any(c["release"] == 12 and "lineage" in c["note"] for c in manifest["changelog"])


def test_a_copied_tree_scans_only_sql_files(tmp_path, described):
    tree = tmp_path / "etl"
    shutil.copytree(SQL_DIR, tree)
    (tree / "README.md").write_text("INSERT INTO nothing SELECT * FROM nowhere", encoding="utf-8")
    (tree / "nested").mkdir()
    shutil.copy(os.path.join(SQL_DIR, "balance_rollup.sql"), tree / "nested" / "rollup_again.sql")
    code, out = _cli("data", "lineage", "--sql", str(tree), "--store", "datastore.ledger", "--at", "2026-10-27", "--project", described)
    assert code == 0 and "3 job(s)" in out and "nowhere" not in out, out
