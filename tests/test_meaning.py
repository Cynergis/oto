"""Meaning (roadmap C2) and the data project as a dependency of a concierge (C5).

A table's or column's description is drafted by an agent and confirmed by a named person, never
the other way round. `oto data meaning` lists what has no description yet as a skeleton proposal,
each node with its schema line as evidence and the context an agent needs (type, key, what loads
it, who uses it); the data-meaning skill fills the descriptions; `oto data meaning --check` refuses
a proposal with an empty description or a status other than draft; the proposal goes through the
gates like any other change. `oto data confirm` is a person's decision: it records an assertion by
them, moves `description_status` to `confirmed` and applies under the gates, which allow the move
because the vocabulary marks the attribute as a decision and the node now cites the assertion.
No proposal can confirm: `curate add` refuses a changed status as a supersession. A concierge that
depends on the data graph routes a question about a table to it."""
import contextlib
import io
import json
import os
import re
import sqlite3

import pytest

from oto.packs.data import meaning
from oto.cli import main
from oto.curate import diff, session
from oto.model import vocabulary as _vocabulary
from oto.project import Project
from oto.scaffold import init

from test_apps import _engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "data-meaning", "SKILL.md")

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


def _call(engine, name, **arguments):
    reply = engine.respond({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    result = reply["result"]
    return result["isError"], "".join(c["text"] for c in result["content"])


@pytest.fixture
def described(tmp_path):
    """The ledger introspected and its lineage applied: tables with no meaning yet."""
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
    _gates(root, seed, "the estate")
    code, out = _cli("data", "introspect", "--path", db, "--store", "datastore.ledger", "--at", "2026-10-26", "--project", root)
    assert code == 0, out
    _gates(root, os.path.join(root, "proposals", "schema-ledger.json"), "the schema")
    code, out = _cli("data", "lineage", "--dbt", os.path.join(ROOT, "tests", "fixtures", "lineage", "dbt-manifest.json"),
                     "--store", "datastore.ledger", "--at", "2026-10-27", "--project", root)
    assert code == 0, out
    _gates(root, os.path.join(root, "proposals", "lineage-ledger-dbt.json"), "the lineage")
    return root


# ---- the vocabulary: a decision attribute ----

def test_description_status_is_a_decision_the_vocabulary_declares():
    with open(os.path.join(ROOT, "oto", "ontologies", "data", "ontology.config.json"), encoding="utf-8") as f:
        config = json.load(f)
    for kind in ("Table", "Column"):
        spec = config["attributes"][kind]["description_status"]
        assert spec.get("decision") is True and spec["default"] == "draft", kind
    assert "decision" not in config["attributes"]["Column"]["type"], "a fact is not a decision"
    with open(os.path.join(ROOT, "oto", "ontologies", "data", "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["release"] == 2 and manifest["changelog"][0]["release"] == 2 and "decision" in manifest["changelog"][0]["note"]
    classes = {"T": {"definition": "x"}}
    assert _vocabulary.declaration_problems(classes, {"T": {"s": {"type": "enum:draft|confirmed", "definition": "x", "decision": True}}}) == []
    problems = _vocabulary.declaration_problems(classes, {"T": {"s": {"type": "enum:draft|confirmed", "definition": "x", "decision": "yes"}}})
    assert problems and "decision" in problems[0], problems


def test_a_decision_attribute_moves_with_a_new_assertion_and_not_without():
    vocabulary = {"classes": {"Column": {"definition": "x"}},
                  "attributes": {"Column": {"type": {"type": "string", "definition": "x"},
                                            "description_status": {"type": "enum:draft|confirmed", "definition": "x", "default": "draft", "decision": True}}}}
    live = {"nodes": [{"id": "column.a", "type": "Column", "label": "a", "attributes": {"type": "int", "description_status": "draft"},
                       "sources": ["schema"], "status": "current"}], "edges": []}
    moved = json.loads(json.dumps(live))
    moved["nodes"][0]["attributes"]["description_status"] = "confirmed"
    contradictions = [f for f in diff.check(live, moved, vocabulary) if f.severity == diff.Finding.CONTRADICTION]
    assert contradictions and "description_status" in contradictions[0].detail, "a decision nobody signed is a change like any other"
    moved["nodes"][0]["sources"].append("assertion:a-0001")
    assert not [f for f in diff.check(live, moved, vocabulary) if f.severity == diff.Finding.CONTRADICTION], "signed, the decision moves"
    fact = json.loads(json.dumps(moved))
    fact["nodes"][0]["attributes"]["type"] = "text"
    contradictions = [f for f in diff.check(live, fact, vocabulary) if f.severity == diff.Finding.CONTRADICTION]
    assert contradictions and "type" in contradictions[0].detail and "description_status" not in contradictions[0].detail, "a fact still needs a supersession"


# ---- the skeleton, the check, the gates ----

def test_meaning_lists_what_has_no_description_as_a_skeleton_with_evidence_and_context(described):
    root = described
    code, out = _cli("data", "meaning", "--store", "datastore.ledger", "--at", "2026-10-28", "--project", root)
    assert code == 0, out
    assert "12 table(s) and column(s) without a description" in out and "proposals/meaning-ledger.json" in out and "data-meaning" in out, out
    with open(os.path.join(root, "proposals", "meaning-ledger.json"), encoding="utf-8") as f:
        skeleton = json.load(f)
    assert skeleton["source_doc"] == "schema-ledger" and skeleton["as_of"] == "2026-10-28"
    nodes = {n["id"]: n for n in skeleton["nodes"]}
    assert len(nodes) == 12 and "table.ledger-postings" in nodes and "column.ledger-postings-amount-cents" in nodes
    column = nodes["column.ledger-postings-amount-cents"]
    assert column["type"] == "Column" and column["label"] == "amount_cents"
    assert column["attributes"] == {"description": "", "description_status": "draft"}, "the agent fills the description; the status is the default, said"
    assert column["evidence"] == [{"doc": "schema-ledger", "where": "postings", "quote": "amount_cents BIGINT not null"}], "its schema line, so the citation holds"
    context = skeleton["_context"]
    assert context["column.ledger-postings-amount-cents"] == {"table": "postings", "type": "BIGINT", "nullable": False}
    assert context["table.ledger-postings"]["kind"] == "table" and context["table.ledger-postings"]["columns"] == ["posting_id", "account_id", "amount_cents", "posted_at"]
    assert context["table.ledger-postings"]["loaded_by"] == ["dbt model postings"] or context["table.ledger-postings"]["loaded_by"] == ["postings"]
    assert context["table.ledger-postings"]["sourced_from"] == ["custodian.settlements", "accounts"], context["table.ledger-postings"]
    assert "description" not in json.dumps(context), "context is what the catalog and the lineage say, never a meaning"
    code, out = _cli("data", "meaning", "--store", "datastore.ledger", "--at", "2026-10-28", "--check", os.path.join(root, "proposals", "meaning-ledger.json"), "--project", root)
    assert code == 1 and "12 empty description(s)" in out, "a skeleton is not yet a proposal"


def _filled(root):
    path = os.path.join(root, "proposals", "meaning-ledger.json")
    with open(path, encoding="utf-8") as f:
        skeleton = json.load(f)
    keep = {"table.ledger-postings": "One row per settled payment posted to an account: the amount in cents, when it was posted.",
            "column.ledger-postings-amount-cents": "The posting's amount in cents of the account's currency; negative for a debit."}
    skeleton["nodes"] = [dict(n, attributes=dict(n["attributes"], description=keep[n["id"]])) for n in skeleton["nodes"] if n["id"] in keep]
    skeleton.pop("_context", None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(skeleton, f, indent=2)
    return path


def test_a_drafted_meaning_goes_through_the_gates_and_a_named_person_confirms_it(described):
    root = described
    code, out = _cli("data", "meaning", "--store", "datastore.ledger", "--at", "2026-10-28", "--project", root)
    assert code == 0, out
    path = _filled(root)
    code, out = _cli("data", "meaning", "--check", path, "--project", root)
    assert code == 0 and "2 description(s), all draft" in out, out
    _gates(root, path, "two meanings drafted")
    code, out = _cli("query", "--project", root, "ask", "DT4")
    assert code == 0 and "One row per settled payment" in out, "a draft is listed with what it says"
    code, out = _cli("query", "--project", root, "ask", "DT1", "TABLE=table.ledger-postings")
    assert code == 0 and "status: answered" in out
    code, out = _cli("data", "confirm", "table.ledger-postings", "--by", "Sam Lee", "--at", "2026-10-29", "--project", root)
    assert code == 0 and "confirmed" in out and "Sam Lee" in out, out
    graph = session.live(Project.standard(root))
    node = next(n for n in graph["nodes"] if n["id"] == "table.ledger-postings")
    assert node["attributes"]["description_status"] == "confirmed" and node["attributes"]["description"].startswith("One row per settled payment")
    assert any(str(s).startswith("assertion:") for s in node["sources"]), "the decision cites the person's assertion"
    with open(os.path.join(root, "assertions.jsonl"), encoding="utf-8") as f:
        last = json.loads(f.read().strip().splitlines()[-1])
    assert last["by"] == "Sam Lee" and "table.ledger-postings" in last["about"] and "confirmed" in last["text"]
    code, out = _cli("audit", "log", "--project", root)
    assert code == 0 and "data confirm" in out, out
    code, out = _cli("audit", "verify", "--project", root)
    assert code == 0, out
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    code, out = _cli("query", "--project", root, "ask", "DT4")
    assert code == 0 and "One row per settled payment" not in out and "negative for a debit" in out, "confirmed leaves the steward's list; the column is still a draft"
    code, out = _cli("ontology", "check", "--project", root)
    assert code == 0 and "every node satisfies them" in out, out
    code, out = _cli("data", "confirm", "table.ledger-postings", "--by", "Sam Lee", "--at", "2026-10-30", "--project", root)
    assert code == 0 and "already confirmed" in out, out
    code, out = _cli("data", "confirm", "column.ledger-postings-posted-at", "--by", "Sam Lee", "--at", "2026-10-30", "--project", root)
    assert code == 1 and "no description" in out and "--description" in out, "nothing to confirm, unless the person states it"
    code, out = _cli("data", "confirm", "column.ledger-postings-posted-at", "--description", "When the posting was booked, in UTC.", "--by", "Sam Lee", "--at", "2026-10-30",
                     "--note", "the custodian's clock", "--project", root)
    assert code == 0 and "confirmed" in out, out
    graph = session.live(Project.standard(root))
    node = next(n for n in graph["nodes"] if n["id"] == "column.ledger-postings-posted-at")
    assert node["attributes"] == {"type": "TEXT", "nullable": True, "description": "When the posting was booked, in UTC.", "description_status": "confirmed"}
    code, out = _cli("data", "confirm", "datastore.ledger", "--by", "Sam Lee", "--at", "2026-10-30", "--project", root)
    assert code == 1 and "Table or a Column" in out, out
    code, out = _cli("data", "confirm", "table.ledger-nope", "--by", "Sam Lee", "--at", "2026-10-30", "--project", root)
    assert code == 1 and "table.ledger-nope" in out, out
    code, out = _cli("data", "confirm", "column.ledger-postings-amount-cents", "--by", "Sam Lee", "--project", root)
    assert code == 1 and "--at" in out, "the date is never defaulted"
    code, out = _cli("data", "confirm", "column.ledger-postings-amount-cents", "--at", "2026-10-30", "--by", "", "--project", root)
    assert code == 1 and "--by" in out, "a decision has a name"
    code, out = _cli("audit", "verify", "--project", root)
    assert code == 0, out


def test_no_proposal_can_confirm_and_the_check_refuses_what_is_not_a_draft(described):
    root = described
    code, out = _cli("data", "meaning", "--store", "datastore.ledger", "--at", "2026-10-28", "--project", root)
    assert code == 0, out
    path = _filled(root)
    _gates(root, path, "drafted")
    with open(path, encoding="utf-8") as f:
        proposal = json.load(f)
    proposal["nodes"][0]["attributes"]["description_status"] = "confirmed"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(proposal, f)
    code, out = _cli("data", "meaning", "--check", path, "--project", root)
    assert code == 1 and "confirmed" in out and "oto data confirm" in out, "a proposal drafts; a person confirms"
    code, out = _cli("curate", "start", "--project", root)
    assert code == 0, out
    code, out = _cli("curate", "add", "--from", path, "--project", root)
    assert code == 1 and "supersession" in out, out
    code, out = _cli("curate", "abort", "--project", root)
    assert code == 0, out
    proposal["nodes"][0]["attributes"]["description_status"] = "draft"
    proposal["nodes"].append({"id": "column.ledger-nothing", "type": "Column", "label": "nothing", "attributes": {"description": "x", "description_status": "draft"}})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(proposal, f)
    code, out = _cli("data", "meaning", "--check", path, "--project", root)
    assert code == 1 and "column.ledger-nothing" in out and "graph lacks" in out, out


def test_meaning_refuses_a_store_the_graph_lacks_and_a_vocabulary_without_descriptions(tmp_path, described):
    code, out = _cli("data", "meaning", "--store", "datastore.nope", "--at", "2026-10-28", "--project", described)
    assert code == 1 and "datastore.nope" in out, out
    code, out = _cli("data", "meaning", "--store", "datastore.ledger", "--project", described)
    assert code == 1 and "--at" in out, out
    plain = str(tmp_path / "plain")
    with contextlib.redirect_stdout(io.StringIO()):
        init(plain, slug="plain", name="Plain", ontology="communication")
    code, out = _cli("data", "meaning", "--store", "datastore.ledger", "--at", "2026-10-28", "--project", plain)
    assert code == 1 and "Table" in out, out


# ---- the skill ----

def test_the_data_meaning_skill_names_commands_that_parse_and_the_rule_that_matters():
    with open(SKILL, encoding="utf-8") as f:
        text = f.read()
    assert text.startswith("---\nname: data-meaning\n")
    for needed in ("oto data meaning", "oto data confirm", "oto query ask DT4", "oto curate add", "oto curate check", "oto curate apply", "--check"):
        assert needed in text, needed
    assert "never" in text and "confirm" in text.lower(), "the skill drafts and never confirms"
    from oto.cli import COMMANDS
    known = {}
    for module in COMMANDS:
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        module.register(sub)
        for name, p in sub.choices.items():
            choices = []
            for action in p._actions:
                if action.choices and not action.option_strings:
                    choices = list(action.choices)
            known[name] = choices
    for command, subcommand in set(re.findall(r"`oto ([a-z]+) ([a-z-]+)", text)):
        assert command in known, "the skill names `oto %s`, which the engine does not have" % command
        if known[command]:
            assert subcommand in known[command] or subcommand.startswith("-"), "the skill names `oto %s %s`" % (command, subcommand)
    with open(os.path.join(ROOT, "skills", "README.md"), encoding="utf-8") as f:
        assert "[data-meaning](data-meaning/SKILL.md)" in f.read()
    with open(os.path.join(ROOT, "oto", "ontologies", "data", "README.md"), encoding="utf-8") as f:
        assert "data-meaning" in f.read()


# ---- the data project as a dependency of a concierge (C5) ----

def test_a_concierge_routes_a_question_about_a_table_to_the_data_graph(described, tmp_path):
    data = described
    code, out = _cli("graph", "describe", "--reach", "http://127.0.0.1:1/ledger", "--project", data)
    assert code == 0, out
    descriptor = json.loads(out)
    assert "Table" in descriptor["classes"] and "LoadJob" in descriptor["classes"] and "Column" in descriptor["classes"], descriptor
    path = str(tmp_path / "ledger.descriptor.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    plan, root = str(tmp_path / "plan"), str(tmp_path / "root")
    with contextlib.redirect_stdout(io.StringIO()):
        init(plan, slug="plan", name="The payments plan", ontology="communication")
        init(root, slug="root", name="Concierge", concierge=True)
    code, out = _cli("graph", "describe", "--reach", "http://127.0.0.1:1/plan", "--project", plan)
    assert code == 0, out
    plan_descriptor = str(tmp_path / "plan.descriptor.json")
    with open(plan_descriptor, "w", encoding="utf-8") as f:
        f.write(out)
    for d in (path, plan_descriptor):
        code, out = _cli("graph", "depend", "--on", d, "--by", "Chiheb Dkhil", "--at", "2026-10-28", "--project", root)
        assert code == 0, out
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    engine = _engine(Project.standard(root))
    error, text = _call(engine, "kg_dependencies")
    assert not error and "graph.described" in text and "Table" in text and "LoadJob" in text, text
    error, text = _call(engine, "kg_dependencies", question="which job loads the postings table and from which feed")
    assert not error and text.index("graph.described") < text.index("graph.plan") and "ask graph.described" in text, text
    error, text = _call(engine, "kg_dependencies", question="what is blocked on the settlement work item")
    assert not error and text.index("graph.plan") < text.index("graph.described"), text
