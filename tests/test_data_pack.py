"""The data pack (roadmap Epic C, groundwork): a database schema as facts, with what each table is
about, where its rows come from and who reads them. On software-architecture, so a table is part of
a `DataStore` that already exists and a consumer is a `Component` that already exists: the data layer
and the architecture graph share one vocabulary (phase 5 relies on it).

    Table, Column          the schema: a column is of one table; a foreign key references a column
    Feed, LoadJob          lineage: a table is loaded by a job, which is sourced from a feed, a table or a store
    Usage                  who reads a table and how: transactional or analytical, from a log or declared
    description_status     what a table or column means is a draft until a person confirms it
"""
import contextlib
import io
import json
import os

import pytest

from oto.cli import main
from oto.model import ontologies, vocabulary as vocab
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(ROOT, "oto", "ontologies", "data")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _own():
    with open(os.path.join(PACK, "ontology.config.json"), encoding="utf-8") as f:
        return json.load(f)


# ---- the vocabulary ----

def test_the_pack_sits_on_software_architecture_and_passes_its_own_check():
    manifest = ontologies.manifest_for("data")
    assert manifest["extends"] == ["software-architecture"] and manifest["release"] == 1 and manifest["domain"] == "data"
    assert manifest["engine"] == ">=0.11"
    assert ontologies.self_check("data") == [], ontologies.self_check("data")
    config, _sample, readme = ontologies.load("data")
    assert {"Table", "Column", "Feed", "LoadJob", "Usage"} <= set(config["classes"])
    assert {"DataStore", "Component", "Document", "Decision"} <= set(config["classes"]), "composed on the estate: nothing is declared twice"
    assert "first draft" in readme.lower() or "edit it" in readme.lower()


def test_a_column_is_of_one_table_and_a_use_is_of_one_table():
    own = _own()
    column_of, use_of = own["properties"]["column_of"], own["properties"]["use_of"]
    assert column_of["domain"] == "Column" and column_of["range"] == "Table" and column_of["min"] == 1 and column_of["max"] == 1
    assert use_of["domain"] == "Usage" and use_of["range"] == "Table" and use_of["min"] == 1 and use_of["max"] == 1
    assert own["properties"]["references"] == dict(own["properties"]["references"], domain="Column", range="Column"), "a foreign key points at the column it references"
    assert own["properties"]["loaded_by"]["domain"] == "Table" and own["properties"]["loaded_by"]["range"] == "LoadJob"
    assert set(own["properties"]["sourced_from"]["range"].split("|")) == {"Feed", "Table", "DataStore"} and own["properties"]["sourced_from"]["domain"] == "LoadJob"
    assert set(own["properties"]["used_by"]["range"].split("|")) >= {"Component", "Team"} and own["properties"]["used_by"]["domain"] == "Usage"


def test_a_table_is_part_of_the_store_the_estate_declares():
    """`part_of` is widened, not duplicated; a component's `reads_from` stays at the store's grain,
    and a table's readers are its `Usage` rows, which say how it is read."""
    config, _sample, _readme = ontologies.load("data")
    assert "Table" in config["properties"]["part_of"]["domain"].split("|") and "DataStore" in config["properties"]["part_of"]["range"].split("|")
    assert "Table" not in config["properties"]["reads_from"]["range"].split("|")
    own = _own()
    assert set(own["properties"]) == {"column_of", "references", "loaded_by", "sourced_from", "use_of", "used_by", "part_of"}


def test_meaning_is_a_draft_until_a_person_confirms_it():
    own = _own()
    for kind in ("Table", "Column"):
        status = own["attributes"][kind]["description_status"]
        assert status["type"] == "enum:draft|confirmed" and status["default"] == "draft", kind
        assert own["attributes"][kind]["description"]["type"] == "string"
    assert own["attributes"]["Column"]["type"]["required"] is True, "a column without a type is not a column"
    assert own["attributes"]["Column"]["key"]["type"] == "enum:primary|foreign"
    assert own["attributes"]["Column"]["nullable"]["type"] == "boolean"
    assert own["attributes"]["Table"]["kind"]["type"] == "enum:table|view"
    assert own["attributes"]["Usage"]["kind"] == dict(own["attributes"]["Usage"]["kind"], type="enum:transactional|analytical", required=True)
    assert own["attributes"]["Usage"]["evidence"]["type"] == "enum:query_log|declared" and own["attributes"]["Usage"]["evidence"]["default"] == "declared"
    assert own["attributes"]["Feed"]["kind"]["type"] == "enum:file|api|stream|database"
    assert set(own["attributes"]["LoadJob"]) == {"schedule", "tool"}


# ---- the questions ----

def test_the_questions_say_what_the_layer_is_for():
    questions = ontologies.questions_for("data")
    ids = [q for q in questions if q.startswith("DT")]
    assert ids == ["DT1", "DT2", "DT3", "DT4", "DT5", "DT6"], ids
    asks = {q: questions[q]["question"] for q in ids}
    assert "TABLE" in questions["DT1"]["params"] and "column" in asks["DT1"].lower(), "DT1: the schema of a table"
    assert "TABLE" in questions["DT2"]["params"] and "come from" in asks["DT2"].lower(), "DT2: lineage, the priority"
    assert "TABLE" in questions["DT3"]["params"] and "read" in asks["DT3"].lower(), "DT3: usage, the priority"
    assert "draft" in asks["DT4"].lower() or "confirm" in asks["DT4"].lower(), "DT4: what is still a draft"
    assert "STORE" in questions["DT5"]["params"], "DT5: what a store holds"
    assert "FEED" in questions["DT6"]["params"], "DT6: what depends on a feed, downstream"
    assert questions["DT4"]["gate"] == "any" and questions["DT2"]["gate"] == "any"


def test_the_sample_answers_the_questions_from_the_estate_s_own_store():
    """The sample describes the estate's ledger: tables in `datastore.ledger`, read by the components
    the architecture sample already declares, loaded from a feed."""
    _config, sample, _readme = ontologies.load("data")
    own = [n for n in sample["nodes"] if n["type"] in ("Table", "Column", "Feed", "LoadJob", "Usage")]
    assert {n["type"] for n in own} == {"Table", "Column", "Feed", "LoadJob", "Usage"}
    tables = [n for n in own if n["type"] == "Table"]
    assert len(tables) >= 2 and all(n["attributes"]["kind"] in ("table", "view") for n in tables)
    assert any(n["attributes"].get("description_status") == "confirmed" for n in own) and any("description_status" not in n["attributes"] and n["attributes"].get("description") for n in own), "one confirmed, one left to the default: draft"
    edges = {(e["from"], e["rel"], e["to"]) for e in sample["edges"]}
    assert any(rel == "part_of" and to == "datastore.ledger" for _f, rel, to in edges), "a table of the store the estate declares"
    assert any(rel == "used_by" and to.startswith("component.") for _f, rel, to in edges), "read by a component the estate declares"
    assert any(rel == "references" for _f, rel, _t in edges) and any(rel == "sourced_from" for _f, rel, _t in edges)


# ---- installed ----

@pytest.fixture
def ledger(tmp_path):
    root = str(tmp_path / "ledger")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="ledger", name="The ledger, described", ontology="data")
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    return root


def test_the_installed_project_builds_and_answers_what_a_table_holds_where_it_comes_from_and_who_reads_it(ledger):
    code, out = _cli("query", "--project", ledger, "ask", "DT1", "TABLE=table.ledger-postings")
    assert code == 0 and "status: answered" in out and "posting_id" in out and "account_id" in out, out
    code, out = _cli("query", "--project", ledger, "ask", "DT2", "TABLE=table.ledger-postings")
    assert code == 0 and "status: answered" in out and "Posting load" in out and "Custodian settlement file" in out and "s.type=Feed" in out, out
    code, out = _cli("query", "--project", ledger, "ask", "DT3", "TABLE=table.ledger-postings")
    assert code == 0 and "status: answered" in out and "u.kind=transactional" in out and "x.type=Component" in out and "u.evidence=query_log" in out, out
    code, out = _cli("query", "--project", ledger, "ask", "DT4")
    assert code == 0 and "description_status" not in out and "posted_at" in out and "ledger.accounts" in out and "posting_id" not in out, \
        "the default reads as the value: a column nobody confirmed is a draft, a confirmed one is not listed"
    code, out = _cli("query", "--project", ledger, "ask", "DT5", "STORE=datastore.ledger")
    assert code == 0 and "status: answered" in out and "ledger.postings" in out and "t.kind=view" in out, out
    code, out = _cli("query", "--project", ledger, "ask", "DT6", "FEED=feed.custodian-settlements")
    assert code == 0 and "status: answered" in out and "ledger.postings" in out, out
    code, out = _cli("ontology", "check", "--project", ledger)
    assert code == 0 and "shapes:" in out and "every node satisfies them" in out, out


def test_a_column_of_two_tables_and_a_use_of_none_break_the_shapes(ledger):
    project = Project.standard(ledger)
    with open(project.graph_path, encoding="utf-8") as f:
        graph = json.load(f)
    tables = [n["id"] for n in graph["nodes"] if n["type"] == "Table"]
    column = next(n["id"] for n in graph["nodes"] if n["type"] == "Column")
    other = next(t for t in tables if (column, "column_of", t) not in {(e["from"], e["rel"], e["to"]) for e in graph["edges"]})
    graph["edges"].append({"from": column, "rel": "column_of", "to": other})
    graph["nodes"].append({"id": "usage.stray", "type": "Usage", "label": "A use of nothing", "status": "current", "as_of": "2026-10-27",
                           "valid_from": "2026-10-27", "source_doc": "x", "sources": ["x"], "aliases": [], "tags": [],
                           "attributes": {"kind": "analytical"}})
    with open(project.graph_path, "w", encoding="utf-8") as f:
        json.dump(graph, f)
    code, out = _cli("ontology", "check", "--strict", "--project", ledger)
    assert code == 1 and "column_of" in out and "usage.stray" in out, out
