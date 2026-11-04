"""Connections to graphs that live in Neo4j: a person lists the graphs they read, `oto graphs add` writes a
folder holding the graph's address and a server entry mapping that graph's own login onto the names the
engine reads. No password in any file, and a graph with no login can't be read
(docs/plans/people-and-graphs.md, capability 3)."""
import contextlib
import io
import json
import os
import subprocess
import sys

import pytest

from oto import connections
from oto.cli import main

URI = "neo4j+s://abc123.databases.neo4j.io"


def _cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(args))
    return code, out.getvalue(), err.getvalue()


def _json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def folder(tmp_path, monkeypatch):
    for var in ("NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_AUTH", "NEO4J_URI", "NORTHWIND_NEO4J_USER", "NORTHWIND_NEO4J_PASSWORD",
                "ACME_NEO4J_USER", "ACME_NEO4J_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    return str(tmp_path / "my-graphs" / "project")


def _add(folder, name="northwind", *more):
    return _cli("graphs", "add", name, "--uri", URI, "--database", "abc123", "--project", folder, *more)


def test_add_writes_the_graphs_address_and_a_server_that_maps_its_own_login(folder):
    code, out, err = _add(folder, "northwind", "--slug", "northwind-fleet", "--label", "Northwind fleet", "--subject", "Buses and who maintains them")
    assert code == 0, err
    config = _json(os.path.join(folder, "graphs", "northwind", "project.config.json"))
    assert config["slug"] == "northwind-fleet", "the slug is the one the graph was loaded under"
    assert config["name"] == "Northwind fleet" and config["description"] == "Buses and who maintains them"
    assert config["serve"] == {"backend": "neo4j"}, "a connection serves from Neo4j and never falls back on its own"
    assert config["neo4j"] == {"uri": URI, "database": "abc123"}
    assert config["server_name"] == "northwind-kg"
    assert config["login"] == {"user": "NORTHWIND_NEO4J_USER", "password": "NORTHWIND_NEO4J_PASSWORD"}, "the names of the variables, never their values"
    entry = _json(os.path.join(folder, ".mcp.json"))["mcpServers"]["northwind-kg"]
    assert entry["command"] == "oto" and entry["args"] == ["serve", "--project", "graphs/northwind"]
    assert entry["env"]["NEO4J_USER"] == "${NORTHWIND_NEO4J_USER:-}" and entry["env"]["NEO4J_PASSWORD"] == "${NORTHWIND_NEO4J_PASSWORD:-}", \
        "an empty default: one graph's missing login never stops the others' servers"
    assert entry["env"]["NEO4J_URI"] == "" and entry["env"]["NEO4J_AUTH"] == "", \
        "a NEO4J_URI or NEO4J_AUTH in the environment must not send this graph elsewhere or lend it another login"
    assert "NORTHWIND_NEO4J_PASSWORD" in out, "it says which variables to set"


def test_no_password_reaches_any_file(folder, monkeypatch):
    monkeypatch.setenv("NORTHWIND_NEO4J_USER", "a-user-value")
    monkeypatch.setenv("NORTHWIND_NEO4J_PASSWORD", "a-secret-value")
    assert _add(folder)[0] == 0
    for directory, _subdirs, files in os.walk(folder):
        for name in files:
            with open(os.path.join(directory, name), encoding="utf-8") as f:
                text = f.read()
            assert "a-secret-value" not in text and "a-user-value" not in text, name


def test_slug_label_and_database_have_defaults(folder):
    assert _cli("graphs", "add", "acme", "--uri", URI, "--project", folder)[0] == 0
    config = _json(os.path.join(folder, "graphs", "acme", "project.config.json"))
    assert config["slug"] == "acme" and config["name"] == "Acme"
    assert "database" not in config["neo4j"], "left to the engine's default"
    assert "description" not in config


def test_a_second_graph_joins_the_first_and_other_servers_stay(folder):
    os.makedirs(folder)
    with open(os.path.join(folder, ".mcp.json"), "w", encoding="utf-8") as f:
        json.dump({"mcpServers": {"something-else": {"command": "x"}}, "other": 1}, f)
    assert _add(folder, "northwind")[0] == 0
    assert _add(folder, "acme")[0] == 0
    mcp = _json(os.path.join(folder, ".mcp.json"))
    assert set(mcp["mcpServers"]) == {"something-else", "northwind-kg", "acme-kg"} and mcp["other"] == 1
    assert mcp["mcpServers"]["acme-kg"]["env"]["NEO4J_PASSWORD"] == "${ACME_NEO4J_PASSWORD:-}"
    assert [g["name"] for g in connections.listed(folder)] == ["acme", "northwind"]


@pytest.mark.parametrize("name,uri,says", [
    ("Bad Name", URI, "name"),
    ("../up", URI, "name"),
    ("ok", "https://abc123.databases.neo4j.io", "address"),
    ("ok", "neo4j+s://", "address"),
    ("ok", "neo4j+s://someone:hunter2@abc123.databases.neo4j.io", "login"),
])
def test_add_refuses_what_it_cannot_use(folder, name, uri, says):
    code, out, err = _cli("graphs", "add", name, "--uri", uri, "--project", folder)
    assert code != 0 and says in err, err
    assert "hunter2" not in err, "a password typed into an address is never repeated"
    assert not os.path.exists(os.path.join(folder, ".mcp.json"))


def test_add_needs_a_name_and_an_address(folder):
    assert _cli("graphs", "add", "--uri", URI, "--project", folder)[0] != 0
    assert _cli("graphs", "add", "northwind", "--project", folder)[0] != 0


def test_adding_the_same_graph_again_changes_nothing_and_a_different_one_is_refused(folder):
    assert _add(folder)[0] == 0
    code, out, err = _add(folder)
    assert code == 0 and "already" in out, out
    code, out, err = _cli("graphs", "add", "northwind", "--uri", "neo4j+s://other.databases.neo4j.io", "--project", folder)
    assert code != 0 and "oto graphs rm northwind" in err, err
    assert _json(os.path.join(folder, "graphs", "northwind", "project.config.json"))["neo4j"]["uri"] == URI


def test_a_server_of_that_name_that_is_not_the_graphs_is_left_alone(folder):
    os.makedirs(folder)
    with open(os.path.join(folder, ".mcp.json"), "w", encoding="utf-8") as f:
        json.dump({"mcpServers": {"northwind-kg": {"command": "someone-elses"}}}, f)
    code, out, err = _add(folder)
    assert code != 0 and "northwind-kg" in err, err
    assert _json(os.path.join(folder, ".mcp.json"))["mcpServers"]["northwind-kg"] == {"command": "someone-elses"}
    assert not os.path.exists(os.path.join(folder, "graphs", "northwind"))


def test_a_broken_mcp_file_is_refused_not_overwritten(folder):
    os.makedirs(folder)
    with open(os.path.join(folder, ".mcp.json"), "w", encoding="utf-8") as f:
        f.write("{not json")
    code, out, err = _add(folder)
    assert code != 0 and ".mcp.json" in err, err
    with open(os.path.join(folder, ".mcp.json"), encoding="utf-8") as f:
        assert f.read() == "{not json"


def test_list_says_whose_login_is_set_and_never_shows_a_value(folder, monkeypatch):
    assert _add(folder, "northwind")[0] == 0
    assert _add(folder, "acme")[0] == 0
    monkeypatch.setenv("NORTHWIND_NEO4J_USER", "a-user-value")
    monkeypatch.setenv("NORTHWIND_NEO4J_PASSWORD", "a-secret-value")
    code, out, err = _cli("graphs", "list", "--project", folder)
    assert code == 0 and "northwind" in out and "acme" in out and URI in out
    assert "ACME_NEO4J_PASSWORD" in out, "it names what is missing"
    assert "a-secret-value" not in out and "a-user-value" not in out
    code, out, err = _cli("graphs", "list", "--project", folder, "--json")
    found = {g["name"]: g for g in json.loads(out)["graphs"]}
    assert found["northwind"]["login"] is True and found["acme"]["login"] is False
    assert found["northwind"]["server"] == "northwind-kg" and found["northwind"]["slug"] == "northwind"
    assert "a-secret-value" not in out


def test_list_is_the_default_and_says_when_there_are_none(folder):
    code, out, err = _cli("graphs", "--project", folder)
    assert code == 0 and "oto graphs add" in out, out


def test_rm_takes_the_graph_out_and_keeps_the_others(folder):
    assert _add(folder, "northwind")[0] == 0
    assert _add(folder, "acme")[0] == 0
    os.makedirs(os.path.join(folder, "graphs", "acme", "build"))           # what a query leaves behind
    code, out, err = _cli("graphs", "rm", "acme", "--project", folder)
    assert code == 0, err
    assert not os.path.exists(os.path.join(folder, "graphs", "acme"))
    assert set(_json(os.path.join(folder, ".mcp.json"))["mcpServers"]) == {"northwind-kg"}
    assert [g["name"] for g in connections.listed(folder)] == ["northwind"]


def test_rm_of_a_graph_that_is_not_there_says_so(folder):
    code, out, err = _cli("graphs", "rm", "nothing", "--project", folder)
    assert code != 0 and "nothing" in err, err


def test_rm_never_deletes_what_it_did_not_write(folder):
    assert _add(folder)[0] == 0
    kept = os.path.join(folder, "graphs", "northwind", "notes.md")
    with open(kept, "w", encoding="utf-8") as f:
        f.write("mine")
    code, out, err = _cli("graphs", "rm", "northwind", "--project", folder)
    assert code == 0 and "notes.md" in out, out
    assert os.path.exists(kept)
    assert "northwind-kg" not in _json(os.path.join(folder, ".mcp.json"))["mcpServers"]
    assert connections.listed(folder) == []


def test_logins_name_each_graphs_variables_and_the_rule_for_its_host(folder):
    assert _add(folder, "northwind")[0] == 0
    assert _cli("graphs", "add", "own", "--uri", "bolt://db.internal:7700", "--project", folder)[0] == 0
    found = {g["name"]: g for g in connections.logins(folder)}
    assert found["northwind"]["variables"] == ["NORTHWIND_NEO4J_USER", "NORTHWIND_NEO4J_PASSWORD"]
    assert found["northwind"]["rule"] == "**.neo4j.io:7687", \
        "Aura's driver is routed on to servers whose names change, under neo4j.io: naming one goes stale"
    assert found["own"]["rule"] == "db.internal:7700"


def test_a_project_that_serves_from_neo4j_passes_the_engines_own_names(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (root / "project.config.json").write_text(json.dumps({"slug": "p", "name": "P", "serve": {"backend": "neo4j"}, "neo4j": {"uri": URI}}))
    found = connections.logins(str(root))
    assert [g["variables"] for g in found] == [["NEO4J_USER", "NEO4J_PASSWORD"]] and found[0]["rule"] == "**.neo4j.io:7687"


def test_a_folder_with_no_graphs_needs_no_login(tmp_path):
    assert connections.logins(str(tmp_path)) == [] and connections.logins(str(tmp_path / "missing")) == []
    (tmp_path / "project.config.json").write_text(json.dumps({"slug": "p", "name": "P"}))
    assert connections.logins(str(tmp_path)) == [], "a project on its local build"


# ---- oto status ----

def test_status_on_a_connection_says_what_it_is_instead_of_crashing(folder):
    assert _add(folder, "northwind", "--label", "Northwind fleet")[0] == 0
    code, out, err = _cli("status", "--project", os.path.join(folder, "graphs", "northwind"))
    assert code == 0, err
    assert "Northwind fleet" in out and "connection" in out and "Neo4j" in out
    code, out, err = _cli("status", "--project", os.path.join(folder, "graphs", "northwind"), "--json")
    found = json.loads(out)
    assert code == 0 and found["kind"] == "connection" and found["backend"] == "neo4j" and found["neo4j"]["uri"] == URI


def test_status_on_a_folder_of_connections_lists_them(folder, monkeypatch):
    assert _add(folder, "northwind")[0] == 0
    assert _add(folder, "acme")[0] == 0
    monkeypatch.setenv("NORTHWIND_NEO4J_PASSWORD", "a-secret-value")
    monkeypatch.setenv("NORTHWIND_NEO4J_USER", "a-user-value")
    code, out, err = _cli("status", "--project", folder)
    assert code == 0, err
    assert "northwind" in out and "acme" in out and "ACME_NEO4J_PASSWORD" in out
    assert "a-secret-value" not in out
    code, out, err = _cli("status", "--project", folder, "--json")
    found = json.loads(out)
    assert found["kind"] == "connections" and {g["name"] for g in found["graphs"]} == {"northwind", "acme"}


def test_status_elsewhere_still_says_it_is_not_a_project(tmp_path):
    code, out, err = _cli("status", "--project", str(tmp_path))
    assert code != 0 and "not an OTO project" in err, err


# ---- the servers ----

def _ask(root, *requests, env=None):
    """What `oto serve` answers over stdio, run as a host runs it. The engine reads its config once, at import."""
    payload = "".join(json.dumps(dict(r, jsonrpc="2.0")) + "\n" for r in requests)
    done = subprocess.run([sys.executable, "-m", "oto.cli", "serve", "--project", root], input=payload, capture_output=True,
                          text=True, timeout=120, env=dict(os.environ, **(env or {})))
    return [json.loads(line) for line in done.stdout.splitlines() if line.strip()], done.stderr


INITIALIZE = {"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
TOOLS = {"id": 2, "method": "tools/list"}


def test_the_plugins_server_stays_out_of_the_way_in_a_folder_of_connections(folder):
    assert _add(folder, "northwind")[0] == 0
    assert _add(folder, "acme")[0] == 0
    (first, second), err = _ask(folder, INITIALIZE, TOOLS)
    assert second["result"]["tools"] == [], "22 tools that answer nothing would only crowd the graphs' own"
    assert "acme-kg" in first["result"]["instructions"] and "northwind-kg" in first["result"]["instructions"]


def test_a_folder_with_nothing_in_it_keeps_offering_the_tools(tmp_path):
    (first, second), err = _ask(str(tmp_path), INITIALIZE, TOOLS)
    assert second["result"]["tools"], "they start answering the moment a project is built here"
    assert "instructions" not in first["result"]


def test_a_connections_server_says_what_its_graph_holds(folder):
    assert _add(folder, "northwind", "--label", "Northwind fleet", "--subject", "Buses and who maintains them")[0] == 0
    (first,), err = _ask(os.path.join(folder, "graphs", "northwind"), INITIALIZE)
    assert first["result"]["serverInfo"]["name"] == "northwind-kg"
    assert first["result"]["instructions"] == "Northwind fleet: Buses and who maintains them"


def test_a_graph_with_no_login_cannot_be_read(folder):
    assert _add(folder)[0] == 0
    call = {"id": 2, "method": "tools/call", "params": {"name": "kg_count", "arguments": {}}}
    env = {"NEO4J_USER": "", "NEO4J_PASSWORD": "", "NEO4J_AUTH": "", "NEO4J_URI": ""}
    (_first, second), err = _ask(os.path.join(folder, "graphs", "northwind"), INITIALIZE, call, env=env)
    assert second["result"]["isError"] is True
    text = second["result"]["content"][0]["text"]
    assert "cannot right now" in text, text


# ---- the skills say it ----

def _skill(name):
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", name, "SKILL.md"), encoding="utf-8") as f:
        return f.read()


def test_the_query_skill_asks_each_graph_and_answers_graph_by_graph():
    text = _skill("query-knowledge")
    assert "## When several graphs answer here" in text
    assert "graph by graph" in text and "never merge" in text


def test_the_sandbox_skill_keeps_the_password_out_of_the_conversation():
    text = _skill("sandbox")
    assert "## A sandbox that reads graphs live" in text and "oto graphs add" in text
    assert "never in this conversation" in text, "the person sets their logins in their own terminal"
