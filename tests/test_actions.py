"""Actions, phase 1: the action file and its checks, the Action node at build time, the
`intended` status through the model and the tools, and the overdue-intent policy."""
import json
import os
import tempfile

import pytest

from oto.actions import model as _actions
from oto.builder import build
from oto.cli import main
from oto.curate import diff as _diff
from oto.project import Project
from oto.reason import engine as _engine, match as _match, rules as _rules
from oto.scaffold import init
from oto.serve.store import SqliteStore

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GOOD = {
    "id": "action.check-repository",
    "label": "Check that a repository exists",
    "description": "Reads the repository's metadata and records whether it exists.",
    "subject": "Repository",
    "executed_by": "team.payments",
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
    "inputSchema": {"type": "object", "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}},
                    "required": ["owner", "repo"]},
    "bind": {"owner": "$attr.owner", "repo": "$attr.name"},
    "when": [{"node": "r", "type": "Repository", "where": {"status": "intended"}}],
    "invoke": {"transport": "mcp", "server": "github", "tool": "get_repository"},
    "needs": ["GITHUB_TOKEN"],
    "result": {"kind": "proposal", "then": {"node": "$subject", "status": "current",
                                            "attributes": {"default_branch": "$response.default_branch"}}},
    "schedule": "daily",
}


def _project(root):
    """A software-architecture project (the ontology ships Repository, implemented_by, a current
    sample repository `repo.billing` and three actions) with the shipped actions removed, so
    each test declares exactly the actions it means to."""
    import shutil
    init(root, slug="acme", name="Acme", ontology="software-architecture")
    project = Project.standard(root)
    shutil.rmtree(project.layout.actions)
    os.makedirs(project.layout.actions)
    return project


def _write_action(project, action, name=None):
    os.makedirs(_actions.directory(project), exist_ok=True)
    with open(os.path.join(_actions.directory(project), (name or action["id"]) + ".json"), "w", encoding="utf-8") as f:
        json.dump(action, f, indent=2)


def _vocabulary(project):
    with open(project.ontology_config_path, encoding="utf-8") as f:
        return json.load(f)


# ---- the action file ----

def test_a_good_action_checks_clean_and_the_command_lists_it(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        assert os.path.isdir(project.layout.actions), "oto init makes the directory"
        _write_action(project, GOOD)
        assert _actions.problems(_actions.load(project), _vocabulary(project)) == []
        assert main(["actions", "check", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "1 action(s) usable" in out and "action.check-repository" in out and "read" in out and "mcp" in out
        assert main(["actions", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "read-only" in out and "on Repository" in out and "by team.payments" in out and "schedule: daily" in out
        assert main(["actions", "list", "--project", root, "--json"]) == 0
        assert json.loads(capsys.readouterr().out)[0]["name"] == "action.check-repository"


def test_every_mistake_in_an_action_file_is_named():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        bad = dict(GOOD, id="check-repo", subject="Nope", annotations={"foo": 1}, bind={"owner": "$out.owned_by.label", "zzz": "$id"},
                   when=[{"edge": ["a", "part_of", "b"]}], invoke={"transport": "ftp"}, needs=["lower"],
                   result={"kind": "email"}, schedule="monthly")
        _write_action(project, bad, name="check-repo")
        with open(os.path.join(_actions.directory(project), "action.broken.json"), "w", encoding="utf-8") as f:
            f.write("{")
        problems = "\n".join(_actions.problems(_actions.load(project), _vocabulary(project)))
        for expected in ("`id` must look like action.<kebab-name>", "subject class 'Nope' is not declared",
                         "annotation 'foo' is not one of", "annotations must say readOnlyHint",
                         "bind names input 'zzz', which inputSchema does not declare",
                         "bind for 'owner' must be $id, $label or $attr.<name>",
                         "the first `when` pattern must be", "`invoke.transport` must be one of mcp, cli, http, script",
                         "`needs` must list environment variable names", "`result.kind` must be document or proposal",
                         "schedule must be one of hourly, daily, weekly", "not JSON"):
            assert expected in problems, (expected, problems)
        # a schedule on an action that changes the world; a when clause over an undeclared class
        changer = dict(GOOD, annotations={"readOnlyHint": False, "destructiveHint": True},
                       when=[{"node": "r", "type": "Repository"}, {"edge": ["r", "nope_rel", "x"]}])
        _write_action(project, changer)
        os.remove(os.path.join(_actions.directory(project), "check-repo.json"))
        os.remove(os.path.join(_actions.directory(project), "action.broken.json"))
        problems = "\n".join(_actions.problems(_actions.load(project), _vocabulary(project)))
        assert "only a read-only action (readOnlyHint true) may carry a schedule" in problems
        assert "relation 'nope_rel' is not declared" in problems
        # a project whose vocabulary predates the core's Action class is told what to add
        vocabulary = _vocabulary(project)
        del vocabulary["classes"]["Action"]
        del vocabulary["properties"]["executed_by"]
        problems = "\n".join(_actions.problems(_actions.load(project), vocabulary))
        assert "class 'Action' is not declared" in problems and "relation 'executed_by' is not declared" in problems


def test_check_says_so_when_nothing_is_declared(capsys):
    with tempfile.TemporaryDirectory() as root:
        _project(root)
        assert main(["actions", "check", "--project", root]) == 0
        assert "no actions declared" in capsys.readouterr().out


# ---- the node at build time ----

def test_an_action_becomes_a_node_at_build_time_with_its_file_as_source():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _write_action(project, GOOD)
        build(project)
        with open(project.graph_path, encoding="utf-8") as f:
            assert not any(n["type"] == "Action" for n in json.load(f)["nodes"]), "graph.json is never written"
        store = SqliteStore(project.layout.database)
        try:
            node = store.node("action.check-repository")
            assert node["type"] == "Action" and node["source_doc"] == "actions/action.check-repository.json"
            attrs = json.loads(node["attributes"])
            assert attrs["subject"] == "Repository" and attrs["read_only"] is True and attrs["transport"] == "mcp"
            assert attrs["needs"] == ["GITHUB_TOKEN"] and attrs["schedule"] == "daily" and attrs["result"] == "proposal"
            assert [e["dst"] for e in store.edges_out("action.check-repository", "executed_by")] == ["team.payments"]
            assert any(r["type"] == "Action" for r in store.types_current())
        finally:
            store.close()
        assert os.path.exists(os.path.join(project.layout.entities, "action__check-repository.md"))


# ---- the intended status ----

def _intended_repo(as_of="2026-01-01"):
    return {"id": "repo.billing", "type": "Repository", "label": "billing-api", "aliases": [], "summary": "Planned.",
            "attributes": {"owner": "acme", "name": "billing-api"}, "tags": [], "as_of": as_of, "valid_from": as_of,
            "source_doc": "plan", "status": "intended", "sources": ["plan"],
            "evidence": [{"doc": "plan", "where": "p.2", "quote": "The API will live in acme/billing-api."}]}


def test_intended_is_a_valid_status_that_never_answers_what_is(capsys):
    assert "intended" in _diff.VALID_STATUS
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        with open(project.graph_path, encoding="utf-8") as f:
            graph = json.load(f)
        graph["nodes"].append(_intended_repo())
        graph["edges"].append({"from": "component.payment-api", "rel": "implemented_by", "to": "repo.billing"})
        with open(project.graph_path, "w", encoding="utf-8") as f:
            json.dump(graph, f)
        build(project)
        store = SqliteStore(project.layout.database)
        try:
            assert store.node("repo.billing")["status"] == "intended"
            assert {r["status"]: r["c"] for r in store.status_counts()}["intended"] == 1
            assert {r["type"]: r["c"] for r in store.types_current()}["Repository"] == 1, "the sample's current one; not the intended one"
            assert not any(r["id"] == "repo.billing" for r in store.hubs(100))
        finally:
            store.close()
        card = open(os.path.join(project.layout.entities, "repo__billing.md"), encoding="utf-8").read()
        assert "INTENDED" in card and "not yet observed" in card
        assert main(["query", "--project", root, "entity", "repo.billing"]) == 0
        out = capsys.readouterr().out
        assert "status=intended" in out and "INTENDED: asserted as a plan" in out
        assert main(["query", "--project", root, "neighbors", "component.payment-api", "implemented_by"]) == 0
        assert "[intended]" in capsys.readouterr().out, "a neighbour that is only intended says so"
        # a stale intent is a policy finding from the core's rule; a fresh one is not
        assert main(["query", "--project", root, "policy"]) == 0
        out = capsys.readouterr().out
        assert "intended-fact-overdue" in out and "repo.billing" in out
        graph["nodes"][-1]["as_of"] = "2026-09-20"
        with open(project.graph_path, "w", encoding="utf-8") as f:
            json.dump(graph, f)
        os.environ["OTO_TODAY"] = "2026-09-21"
        try:
            build(project)
        finally:
            del os.environ["OTO_TODAY"]
        assert main(["query", "--project", root, "policy"]) == 0
        assert "intended-fact-overdue" not in capsys.readouterr().out
        # curate accepts it as a status, and the candidate check treats it like any other
        assert main(["curate", "start", "--project", root]) == 0
        assert main(["curate", "check", "--project", root]) == 0


def test_rules_see_intended_facts_in_policies_only_and_where_may_name_the_nodes_own_fields():
    nodes = [{"id": "a", "type": "T", "status": "current", "as_of": "2026-01-01"},
             {"id": "b", "type": "T", "status": "intended", "as_of": "2026-06-01"},
             {"id": "c", "type": "T", "status": "superseded", "as_of": "2025-01-01"}]
    edges = [{"from": "a", "rel": "near", "to": "b"}, {"from": "a", "rel": "near", "to": "a"}]
    vocabulary = {"classes": {"T": {"definition": "t"}}, "properties": {"near": {"domain": "T", "range": "T", "definition": "n"}, "far": {"domain": "T", "range": "T", "definition": "f"}}}
    rules = [{"id": "derive-far", "kind": "derive", "when": [{"edge": ["x", "near", "y"]}], "then": {"edge": ["x", "far", "y"]},
              "why": "w", "validated_by": ""},
             {"id": "stale", "kind": "policy", "severity": "warn",
              "when": [{"node": "n", "where": {"status": "intended", "as_of": {"<": "$today-30d"}}}],
              "then": {"flag": "stale intent"}, "why": "w", "validated_by": ""},
             {"id": "any-intended", "kind": "policy", "severity": "warn", "when": [{"node": "n", "type": "T", "where": {"status": "intended"}}],
              "then": {"flag": "an intent"}, "why": "w", "validated_by": ""}]
    assert _rules.problems(rules, vocabulary) == []
    os.environ["OTO_TODAY"] = "2026-09-21"
    try:
        assert _match.resolve("$today") == "2026-09-21" and _match.resolve("$today-30d") == "2026-08-22" and _match.resolve("x") == "x"
        result = _engine.run(rules, nodes, edges)
    finally:
        del os.environ["OTO_TODAY"]
    assert [(e["from"], e["to"]) for e in result["edges"]] == [("a", "a")], "a derivation never rests on an intended fact"
    assert {(f["rule"], f["node"]) for f in result["findings"]} == {("stale", "b"), ("any-intended", "b")}
    bad = [{"id": "r", "kind": "policy", "severity": "warn", "when": [{"node": "n", "type": "T", "where": {"as_of": {"~": "x"}}}],
            "then": {"flag": "f"}, "why": "w"}]
    assert any("operator '~'" in p for p in _rules.problems(bad, vocabulary))


# ---- phase 2: the catalog ----

def _catalog_project(root):
    """A project with an intended repository, a current one, and two actions: a read-only check
    on intended repositories and a change bound to a team."""
    project = _project(root)
    with open(project.graph_path, encoding="utf-8") as f:
        graph = json.load(f)
    graph["nodes"].append(_intended_repo())
    graph["nodes"].append(dict(_intended_repo(), id="repo.ledger", label="ledger", status="current",
                               attributes={"owner": "acme", "name": "ledger", "default_branch": "main"}))
    graph["edges"].append({"from": "component.payment-api", "rel": "implemented_by", "to": "repo.billing"})
    with open(project.graph_path, "w", encoding="utf-8") as f:
        json.dump(graph, f)
    _write_action(project, GOOD)
    create = dict(GOOD, id="action.create-repository", label="Create the repository", schedule=None,
                  annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
                  inputSchema={"type": "object", "properties": {"owner": {"type": "string"}, "name": {"type": "string"},
                                                                "visibility": {"type": "string"}},
                               "required": ["owner", "name", "visibility"]},
                  bind={"owner": "$attr.owner", "name": "$attr.name"},
                  invoke={"transport": "mcp", "server": "github", "tool": "create_repository"})
    del create["schedule"]
    _write_action(project, create)
    archive = dict(create, id="action.archive-repository", label="Archive a repository", subject="Repository",
                   when=[{"node": "r", "type": "Repository", "where": {"status": "current"}},
                         {"edge": ["x", "implemented_by", "r"]}],
                   bind={"owner": "$attr.owner", "name": "$attr.name", "visibility": "$attr.visibility"})
    _write_action(project, archive)
    retire = dict(archive, id="action.retire-repository", label="Retire a repository",
                  when=[{"node": "r", "type": "Repository", "where": {"status": "superseded"}}])
    _write_action(project, retire)
    return project


def test_readiness_bindings_and_the_tool_shape():
    from oto.actions import catalog as _catalog
    with tempfile.TemporaryDirectory() as root:
        project = _catalog_project(root)
        assert main(["actions", "check", "--project", root]) == 0
        loaded = [a for _r, a, e in _actions.load(project) if not e]
        with open(project.graph_path, encoding="utf-8") as f:
            graph = json.load(f)
        nodes, edges = graph["nodes"], graph["edges"]
        by_id = {a["id"]: a for a in loaded}
        assert _catalog.readiness(by_id["action.check-repository"], nodes, edges) == (["repo.billing"], "")
        assert _catalog.readiness(by_id["action.archive-repository"], nodes, edges) == (["repo.payment-api"], ""), \
            "the sample's current repository has a component; the ledger has none, the intended one is not current"
        ready, reason = _catalog.readiness(by_id["action.retire-repository"], nodes, edges)
        assert ready == [] and reason.startswith("3 Repository, none meet:") and "superseded" in reason
        ready, reason = _catalog.readiness(dict(GOOD, subject="Runbook", when=[{"node": "r", "type": "Runbook", "where": {"status": "intended"}}]), nodes, edges)
        assert ready == [] and "1 Runbook, none meet" in reason
        assert _catalog.readiness(dict(GOOD, subject="Zebra", when=[{"node": "z", "type": "Zebra"}]), nodes, edges) == ([], "no Zebra in the graph")
        repo = next(n for n in nodes if n["id"] == "repo.billing")
        assert _catalog.bind(by_id["action.check-repository"], repo) == ({"owner": "acme", "repo": "billing-api"}, [])
        inputs, missing = _catalog.bind(by_id["action.create-repository"], repo)
        assert inputs == {"owner": "acme", "name": "billing-api"} and missing == ["visibility"], "what is not bound is asked of the caller"
        d = _catalog.tool_definition(by_id["action.check-repository"], nodes, edges, on=repo)
        assert d["name"] == "action.check-repository" and d["annotations"]["readOnlyHint"] is True and d["inputSchema"]["required"] == ["owner", "repo"]
        assert d["oto"]["ready"] is True and d["oto"]["inputs"] == {"owner": "acme", "repo": "billing-api"} and d["oto"]["invoke"]["tool"] == "get_repository"
        assert d["oto"]["needs"] == ["GITHUB_TOKEN"] and d["oto"]["result"]["kind"] == "proposal"
        listed = _catalog.catalog(loaded, nodes, edges, ready_only=True)
        assert [x["name"] for x in listed] == ["action.archive-repository", "action.check-repository", "action.create-repository"]
        on_repo = _catalog.for_entity(loaded, nodes, edges, repo)
        assert [(x["name"], x["oto"]["ready"]) for x in on_repo] == [("action.check-repository", True), ("action.create-repository", True),
                                                                      ("action.archive-repository", False), ("action.retire-repository", False)]
        text = _catalog.text(on_repo, heading="h")
        assert "READY" in text and "the caller must supply: visibility" in text and "not ready" in text and "invoke: mcp" in text


def test_the_commands_and_the_tool_answer_the_catalog(capsys):
    from test_apps import _engine, _get
    from oto.serve import http as _http
    with tempfile.TemporaryDirectory() as root:
        project = _catalog_project(root)
        assert main(["actions", "list", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "4 action(s)" in out and "ready on 1: repo.billing" in out and "ready on 1: repo.payment-api" in out and "not ready: 3 Repository" in out
        assert main(["actions", "list", "--project", root, "--ready", "--json"]) == 0
        assert [d["name"] for d in json.loads(capsys.readouterr().out)] == ["action.archive-repository", "action.check-repository", "action.create-repository"]
        assert main(["actions", "show", "action.create-repository", "--on", "repo.billing", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "the invocation the caller performs" in out and '"owner": "acme"' in out and "the caller must supply: visibility" in out
        assert main(["actions", "show", "action.create-repository", "--on", "team.payments", "--project", root]) == 1
        assert "acts on Repository" in capsys.readouterr().err
        assert main(["actions", "show", "action.nope", "--project", root]) == 1
        # built: the store carries the definitions, so the tool answers from either store
        build(project)
        engine = _engine(project)
        assert any(t["name"] == "kg_actions" for t in engine.TOOLS)
        text = engine.actions_text()
        assert "4 action(s)" in text and "ready on 1: repo.billing" in text
        assert "READY" in engine.actions_text(on="repo.billing") and "the caller must supply: visibility" in engine.actions_text(on="repo.billing")
        assert "none: no action declares" in engine.actions_text(on="team.payments")
        assert engine.actions_text(on="nothing-like-this") .startswith("No entity matched")
        assert "No action 'action.nope'" in engine.actions_text(action="action.nope")
        assert "action.retire-repository" not in engine.actions_text(ready=True) and "action.archive-repository" in engine.actions_text(ready=True)
        data = engine.actions_data(on="repo.billing")
        assert data["on"] == "repo.billing" and data["actions"][0]["oto"]["inputs"] == {"owner": "acme", "repo": "billing-api"}
        assert main(["query", "--project", root, "actions", "--on", "repo.billing"]) == 0
        assert "READY" in capsys.readouterr().out
        server = _http.Server(engine, "127.0.0.1", 0, project_root=root, identity=project.config()).start()
        try:
            status, _c, body = _get(server.url + "/api/actions?on=repo.billing")
            payload = json.loads(body)
            assert status == 200 and payload["data"]["actions"][0]["annotations"]["readOnlyHint"] is True
            status, _c, body = _get(server.url + "/api/actions?ready=true")
            assert [d["name"] for d in json.loads(body)["data"]["actions"]] == ["action.archive-repository", "action.check-repository", "action.create-repository"]
        finally:
            server.stop()


# ---- phase 3: the evidence loop ----

RESPONSE = {"id": 42, "full_name": "acme/payment-api", "default_branch": "main", "pushed_at": "2026-09-22T10:00:00Z",
            "owner": {"login": "acme"}, "topics": ["payments", "api"]}


def _response_file(root, payload):
    path = os.path.join(root, "response.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return path


def test_response_paths_and_the_rendered_then():
    from oto.actions import runs as _runs
    assert _runs.response_path(RESPONSE, "$response.default_branch") == "main"
    assert _runs.response_path(RESPONSE, "$response.owner.login") == "acme"
    assert _runs.response_path(RESPONSE, "$response.topics.1") == "api"
    assert _runs.response_path(RESPONSE, "$response.nope.deeper") is None and _runs.response_path(RESPONSE, "$attr.x") is None
    assert _runs.response_path(RESPONSE, "$response") == RESPONSE
    action = dict(GOOD, result={"kind": "proposal", "then": {"node": "$subject", "status": "current",
                                                             "attributes": {"default_branch": "$response.default_branch",
                                                                            "github_id": "$response.id", "missing": "$response.nope",
                                                                            "checked": "yes"}}})
    proposal, unresolved = _runs.render_then(action, _intended_repo(), RESPONSE, "2026-09-22", "doc-slug")
    node = proposal["nodes"][0]
    assert node["id"] == "repo.billing" and node["status"] == "current" and node["valid_from"] == "2026-09-22", "the plan became real that day"
    assert node["attributes"] == {"default_branch": "main", "github_id": 42, "checked": "yes"} and unresolved == ["$response.nope"]
    assert node["source_doc"] == "doc-slug" and node["evidence"][0]["doc"] == "doc-slug" and "main" in node["evidence"][0]["quote"]
    assert proposal["source_doc"] == "doc-slug" and proposal["edges"] == []


def test_a_recorded_run_realises_an_intended_fact_through_the_gates_with_the_run_as_evidence(capsys):
    from oto.actions import runs as _runs
    from test_apps import _engine
    with tempfile.TemporaryDirectory() as root:
        project = _catalog_project(root)
        response = _response_file(root, RESPONSE)
        # refusals first: no --by, wrong class, text for a proposal result
        assert main(["actions", "record", "action.check-repository", "--on", "repo.billing", "--response", response, "--project", root]) == 1
        assert "--by is required" in capsys.readouterr().err
        assert main(["actions", "record", "action.check-repository", "--on", "team.payments", "--by", "Chiheb", "--response", response, "--project", root]) == 1
        assert "acts on Repository" in capsys.readouterr().err
        with open(os.path.join(root, "text.txt"), "w") as f:
            f.write("just text")
        assert main(["actions", "record", "action.check-repository", "--on", "repo.billing", "--by", "Chiheb", "--response", os.path.join(root, "text.txt"), "--project", root]) == 1
        assert "must be a JSON object" in capsys.readouterr().err
        assert main(["actions", "runs", "--project", root]) == 0 and "no runs recorded" in capsys.readouterr().out
        # the run
        assert main(["actions", "record", "action.check-repository", "--on", "repo.billing", "--by", "Chiheb",
                     "--at", "2026-09-22", "--response", response, "--note", "first check", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "recorded action.check-repository on repo.billing by Chiheb at 2026-09-22" in out and "proposal: proposals/action.check-repository.2026-09-22.json" in out
        run_dir = os.path.join(root, "runs", "actions", "action.check-repository", "2026-09-22")
        rec = json.load(open(os.path.join(run_dir, "run.json"), encoding="utf-8"))
        assert rec["ready"] is True and rec["inputs"] == {"owner": "acme", "repo": "billing-api"} and rec["needs"] == ["GITHUB_TOKEN"]
        assert rec["response_sha256"] and rec["result_kind"] == "proposal" and rec["note"] == "first check"
        assert json.load(open(os.path.join(run_dir, "response.json"), encoding="utf-8")) == RESPONSE
        assert "GITHUB_TOKEN=" not in open(os.path.join(run_dir, "run.json"), encoding="utf-8").read(), "names only, never values"
        doc = open(os.path.join(root, rec["document"]), encoding="utf-8").read()
        assert doc.startswith("# Run of Check that a repository exists on billing-api") and '"default_branch": "main"' in doc and "first check" in doc
        proposal = json.load(open(os.path.join(root, rec["proposal"]), encoding="utf-8"))
        assert proposal["nodes"][0]["attributes"] == {"default_branch": "main"} and proposal["nodes"][0]["status"] == "current"
        assert proposal["source_doc"] == rec["document_slug"]
        # the document is a source once ingested; the proposal goes through the gates
        assert main(["ingest", "--project", root]) == 0
        capsys.readouterr()
        assert os.path.exists(os.path.join(project.layout.corpus, rec["document_slug"] + ".md"))
        assert main(["curate", "start", "--project", root]) == 0
        assert main(["curate", "add", "--project", root, "--from", os.path.join(root, rec["proposal"]), "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "updated" in out and "repo.billing" in out and "conflict" not in out.lower()
        assert main(["curate", "add", "--project", root, "--from", os.path.join(root, rec["proposal"])]) == 0
        capsys.readouterr()
        assert main(["curate", "check", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "contradiction" not in out.lower() or "repo.billing" not in out.split("contradiction")[1][:200], "a plan becoming real is a recorded change"
        assert main(["curate", "apply", "--project", root, "--by", "Chiheb", "--note", "the repository exists now"]) == 0
        capsys.readouterr()
        with open(project.graph_path, encoding="utf-8") as f:
            repo = next(n for n in json.load(f)["nodes"] if n["id"] == "repo.billing")
        assert repo["status"] == "current" and repo["valid_from"] == "2026-09-22" and repo["attributes"]["default_branch"] == "main"
        assert repo["attributes"]["owner"] == "acme", "what the plan said is kept"
        assert rec["document_slug"] in repo["sources"] and any(e["doc"] == rec["document_slug"] for e in repo["evidence"])
        assert main(["vet", "--project", root]) == 0, "every citation, the run's included, resolves to a document"
        capsys.readouterr()
        # built: the action acts_on the repository, carries its last run, and the tool says so
        build(project)
        store = SqliteStore(project.layout.database)
        try:
            assert [e["dst"] for e in store.edges_out("action.check-repository", "acts_on")] == ["repo.billing"]
            attrs = json.loads(store.node("action.check-repository")["attributes"])
            assert attrs["last_run"]["at"] == "2026-09-22" and attrs["last_run"]["by"] == "Chiheb" and attrs["runs"] == 1
            assert store.node("repo.billing")["status"] == "current"
            assert any(r["type"] == "Repository" for r in store.types_current()), "now part of what is"
        finally:
            store.close()
        engine = _engine(project)
        text = engine.actions_text(action="action.check-repository")
        assert "last run: 2026-09-22 on repo.billing by Chiheb" in text
        assert "not ready: 3 Repository" in text, "realised, so the check's precondition (intended) no longer holds"
        assert main(["actions", "runs", "--project", root]) == 0
        assert "action.check-repository" in capsys.readouterr().out
        assert main(["actions", "list", "--project", root]) == 0
        assert "last run: 2026-09-22" in capsys.readouterr().out
        assert main(["query", "--project", root, "neighbors", "repo.billing"]) == 0
        assert "→ acts on" in capsys.readouterr().out, "the relation reads as the vocabulary labels it"
        assert main(["query", "--project", root, "neighbors", "repo.billing", "acts on"]) == 0
        assert "→ acts on" in capsys.readouterr().out, "a relation filter takes the label too"
        # a second run whose response contradicts what the graph now holds is refused at merge
        response2 = _response_file(root, dict(RESPONSE, default_branch="develop"))
        assert main(["actions", "record", "action.check-repository", "--on", "repo.billing", "--by", "Chiheb",
                     "--at", "2026-09-23", "--response", response2, "--project", root]) == 0
        out = capsys.readouterr().out
        assert "preconditions did not hold" in out
        assert main(["curate", "start", "--project", root]) == 0
        assert main(["curate", "add", "--project", root, "--from", os.path.join(root, "proposals", "action.check-repository.2026-09-23.json"), "--dry-run"]) == 1
        out = capsys.readouterr().out
        assert "would refuse" in out and "attributes" in out, "a changed value needs supersession, not a silent overwrite"
        assert len(_runs.all_runs(project)) == 2 and _runs.last_runs(project)["action.check-repository"]["runs"] == 2


def test_a_document_result_goes_to_the_inbox_only(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _catalog_project(root)
        doc_action = dict(GOOD, id="action.read-readme", label="Read the README", result={"kind": "document"},
                          invoke={"transport": "http", "method": "GET", "url": "https://raw.example/{owner}/{repo}/README.md"})
        del doc_action["schedule"]
        _write_action(project, doc_action)
        with open(os.path.join(root, "readme.txt"), "w", encoding="utf-8") as f:
            f.write("# payment-api\n\nBills customers.\n")
        assert main(["actions", "record", "action.read-readme", "--on", "repo.billing", "--by", "Chiheb", "--at", "2026-09-22",
                     "--response", os.path.join(root, "readme.txt"), "--project", root]) == 0
        out = capsys.readouterr().out
        assert "proposal:" not in out and "author the proposal from the document" in out
        rec = json.load(open(os.path.join(root, "runs", "actions", "action.read-readme", "2026-09-22", "run.json"), encoding="utf-8"))
        assert rec["proposal"] is None and rec["response_file"] == "response.txt"
        assert "Bills customers." in open(os.path.join(root, rec["document"]), encoding="utf-8").read()
        assert not os.listdir(os.path.join(root, "proposals")) if os.path.isdir(os.path.join(root, "proposals")) else True


# ---- phase 5: schedules, the due filter, and the workflow's invoke script ----

def test_due_is_read_only_scheduled_and_older_than_the_interval():
    import datetime
    from oto.actions import catalog as _catalog
    daily = dict(GOOD)
    assert _catalog.due(daily) == (True, "never run")
    at = datetime.datetime(2026, 9, 23, 12, 0, tzinfo=datetime.timezone.utc)
    recent = dict(daily, _last_run={"at": "2026-09-23", "recorded_at": "2026-09-23T06:00:00+00:00"})
    assert _catalog.due(recent, at)[0] is False and "next after 2026-09-24T06:00:00" in _catalog.due(recent, at)[1]
    old = dict(daily, _last_run={"at": "2026-09-21", "recorded_at": "2026-09-21T06:00:00+00:00"})
    assert _catalog.due(old, at) == (True, "last run 2026-09-21, 54h ago")
    hourly = dict(daily, schedule="hourly", _last_run={"at": "2026-09-23", "recorded_at": "2026-09-23T10:30:00+00:00"})
    assert _catalog.due(hourly, at)[0] is True
    weekly = dict(daily, schedule="weekly", _last_run={"at": "2026-09-20"})           # date only: midnight
    assert _catalog.due(weekly, at)[0] is False
    changer = dict(daily, annotations={"readOnlyHint": False})
    assert _catalog.due(changer) == (False, "not read-only: never runs unattended")
    assert _catalog.due({k: v for k, v in daily.items() if k != "schedule"}) == (False, "no schedule")
    os.environ["OTO_TODAY"] = "2026-09-23"
    try:
        assert _catalog.now().isoformat() == "2026-09-23T00:00:00+00:00"
    finally:
        del os.environ["OTO_TODAY"]


def test_the_due_filter_in_the_command_and_the_tool_and_the_timeout_check(capsys):
    from test_apps import _engine
    with tempfile.TemporaryDirectory() as root:
        project = _catalog_project(root)                         # check-repository is daily, ready on repo.billing
        _write_action(project, dict(GOOD, timeout=0))
        assert main(["actions", "check", "--project", root]) == 1
        assert "`timeout` must be a number of seconds" in capsys.readouterr().out
        _write_action(project, dict(GOOD, timeout=30))
        assert main(["actions", "list", "--project", root, "--due", "--json"]) == 0
        due = json.loads(capsys.readouterr().out)
        assert [d["name"] for d in due] == ["action.check-repository"] and due[0]["oto"]["due"] is True and due[0]["oto"]["timeout"] == 30
        assert main(["actions", "list", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "schedule: daily · DUE (never run)" in out and "timeout: 30s" in out
        # recorded today: no longer due, and the tool agrees from the store
        os.environ["OTO_TODAY"] = "2026-09-23"
        try:
            response = _response_file(root, RESPONSE)
            assert main(["actions", "record", "action.check-repository", "--on", "repo.billing", "--by", "Chiheb", "--at", "2026-09-23",
                         "--response", response, "--project", root]) == 0
            capsys.readouterr()
            assert main(["actions", "list", "--project", root, "--due"]) == 0
            assert "No scheduled read-only action is due" in capsys.readouterr().out
            build(project)
            engine = _engine(project)
            assert "No scheduled read-only action is due" in engine.actions_text(due=True)
            assert "not due (ran 2026-09-23" in engine.actions_text(action="action.check-repository")
        finally:
            del os.environ["OTO_TODAY"]


def test_the_invoke_script_calls_the_declared_transport_and_records(capsys):
    """The script repository mode installs: it invokes http, cli and script actions that are due,
    skips mcp and a missing variable, and records through the engine. Run here against a local
    server, with the engine as `python -m oto.cli`."""
    import http.server
    import subprocess
    import sys
    import threading
    from oto import repo as _repo

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"path": self.path, "auth": self.headers.get("Authorization", ""), "ok": True}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d" % server.server_address[1]
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        with open(project.graph_path, encoding="utf-8") as f:
            graph = json.load(f)
        for n in graph["nodes"]:
            if n["id"] == "interface.payments-v2":
                n["attributes"]["url"] = url + "/payments/v2"
        graph["nodes"].append(_intended_repo())
        with open(project.graph_path, "w", encoding="utf-8") as f:
            json.dump(graph, f)
        base = {"subject": "Interface", "executed_by": "team.payments",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
                "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}, "label": {"type": "string"}}, "required": ["url"]},
                "bind": {"url": "$attr.url", "label": "$label"}, "when": [{"node": "i", "type": "Interface"}],
                "needs": [], "result": {"kind": "document"}, "schedule": "daily", "timeout": 10}
        _write_action(project, dict(base, id="action.probe", label="Probe", description="GET the interface.",
                                    invoke={"transport": "http", "method": "GET", "url": "{url}?q={label}", "headers": {"Authorization": "PROBE_TOKEN"}},
                                    needs=["PROBE_TOKEN"]))
        _write_action(project, dict(base, id="action.echo", label="Echo", description="Echo the label.",
                                    invoke={"transport": "cli", "command": "echo probed {label}"}))
        script = os.path.join(project.layout.actions, "reply.sh")
        with open(script, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\nread line\necho \"{\\\"got\\\": $line}\"\n")
        os.chmod(script, 0o755)
        _write_action(project, dict(base, id="action.reply", label="Reply", description="A script answers.",
                                    invoke={"transport": "script", "path": "reply.sh"}))
        _write_action(project, dict(base, id="action.ask-agent", label="Ask an agent", description="Needs an MCP server.",
                                    invoke={"transport": "mcp", "server": "x", "tool": "y"}))
        _write_action(project, dict(base, id="action.no-token", label="No token", description="Needs a secret nobody set.",
                                    invoke={"transport": "http", "method": "GET", "url": "{url}"}, needs=["NOBODY_SET_THIS"]))
        _write_action(project, dict(GOOD, schedule="daily"))     # mcp, ready on the intended repository
        assert main(["actions", "check", "--project", root]) == 0
        capsys.readouterr()
        script_path = os.path.join(root, "invoke.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(_repo.files("acme", "Acme")[os.path.join(".github", "scripts", "oto-actions-invoke.py")])
        env = dict(os.environ, PYTHONPATH=REPO_ROOT, PROBE_TOKEN="Bearer s3cret", OTO_DENY_TERMS=os.environ.get("OTO_DENY_TERMS", ""))
        env.pop("NOBODY_SET_THIS", None)
        r = subprocess.run([sys.executable, script_path, "--project", root, "--oto", "%s -m oto.cli" % sys.executable,
                            "--by", "the workflow", "--at", "2026-09-23", "--summary", os.path.join(root, "summary.json")],
                           capture_output=True, text=True, env=env, timeout=300, cwd=REPO_ROOT)
        assert r.returncode == 0, r.stderr[-2000:]
        summary = json.loads(open(os.path.join(root, "summary.json"), encoding="utf-8").read())
        invoked = {(i["action"], i["on"]): i for i in summary["invoked"]}
        assert set(invoked) == {("action.probe", "interface.payments-v2"), ("action.echo", "interface.payments-v2"), ("action.reply", "interface.payments-v2")}
        skipped = {s["action"]: s["why"] for s in summary["skipped"]}
        assert "MCP tool needs an agent" in skipped["action.ask-agent"]
        assert skipped["action.check-repository"] == "environment variable(s) not set: GITHUB_TOKEN", "a missing variable is judged before the transport"
        assert skipped["action.no-token"] == "environment variable(s) not set: NOBODY_SET_THIS" and summary["failed"] == []
        assert "s3cret" not in r.stdout and "s3cret" not in open(os.path.join(root, "summary.json")).read(), "values never printed"
        from oto.actions import runs as _runs
        records = {rec["action"]: rec for _rel, rec in _runs.all_runs(project)}
        probe = json.loads(open(os.path.join(root, records["action.probe"]["directory"] if "directory" in records["action.probe"] else
                                              os.path.join("runs", "actions", "action.probe", "2026-09-23"), "response.json")).read())
        assert probe["path"] == "/payments/v2?q=Payments%20API%20v2" and probe["auth"] == "Bearer s3cret" and probe["ok"] is True
        assert records["action.probe"]["by"] == "the workflow" and records["action.probe"]["note"] == "invoked by the actions workflow"
        echo = open(os.path.join(root, "runs", "actions", "action.echo", "2026-09-23", "response.txt")).read()
        assert echo.strip() == "probed Payments API v2"
        reply = json.loads(open(os.path.join(root, "runs", "actions", "action.reply", "2026-09-23", "response.json")).read())
        assert reply["got"]["url"].endswith("/payments/v2")
        assert len(os.listdir(project.layout.inbox)) == 3, "three run documents wait for ingest"
    server.shutdown()


def test_repository_mode_installs_the_actions_workflow_and_the_script():
    from oto import repo as _repo
    files = _repo.files("acme", "Acme")
    workflow = files[os.path.join(".github", "workflows", "oto-actions.yml")]
    script = files[os.path.join(".github", "scripts", "oto-actions-invoke.py")]
    assert "cron:" in workflow and "workflow_dispatch" in workflow
    assert "python .github/scripts/oto-actions-invoke.py --project ." in workflow
    assert "oto actions list --due" in script and "oto ingest --project ." in workflow and "oto curate check --project ." in workflow
    assert 'oto curate apply --project . --by "oto actions workflow"' in workflow and "gh pr create" in workflow
    assert "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in workflow and "OTO_ENGINE_TOKEN: ${{ secrets.OTO_ENGINE_TOKEN }}" in workflow
    assert "Nothing that changes the world is ever due" in workflow
    assert "mcp" in script and "needs an agent" in script


def test_a_response_that_does_not_confirm_the_fact_writes_no_proposal(capsys):
    """A repository check that answers "not found" records the run and withholds the proposal:
    a missing `require` path must never realise an intended fact."""
    with tempfile.TemporaryDirectory() as root:
        project = _catalog_project(root)
        guarded = dict(GOOD, result=dict(GOOD["result"], require=["$response.html_url"]))
        _write_action(project, guarded)
        assert main(["actions", "check", "--project", root]) == 0
        not_found = _response_file(root, {"message": "Not Found", "status": "404"})
        assert main(["actions", "record", "action.check-repository", "--on", "repo.billing", "--by", "Chiheb", "--at", "2026-09-23",
                     "--response", not_found, "--project", root]) == 0
        out = capsys.readouterr().out
        assert "no proposal: the response does not confirm the fact: $response.html_url not present" in out and "proposal:" not in out.replace("no proposal:", "")
        rec = json.load(open(os.path.join(root, "runs", "actions", "action.check-repository", "2026-09-23", "run.json"), encoding="utf-8"))
        assert rec["proposal"] is None and "html_url" in rec["withheld"]
        assert not os.path.exists(os.path.join(root, "proposals")) or not os.listdir(os.path.join(root, "proposals"))
        with open(project.graph_path, encoding="utf-8") as f:
            assert next(n for n in json.load(f)["nodes"] if n["id"] == "repo.billing")["status"] == "intended"
        found = _response_file(root, dict(RESPONSE, html_url="https://github.com/acme/billing-api"))
        assert main(["actions", "record", "action.check-repository", "--on", "repo.billing", "--by", "Chiheb", "--at", "2026-09-24",
                     "--response", found, "--project", root]) == 0
        assert "proposal: proposals/action.check-repository.2026-09-24.json" in capsys.readouterr().out
        bad = dict(guarded, result=dict(guarded["result"], require="$response.html_url"))
        _write_action(project, bad)
        assert main(["actions", "check", "--project", root]) == 1
        assert "result.require must list" in capsys.readouterr().out


def test_the_scenario_script_builds_the_sandbox(capsys):
    """tools/actions-scenario.py setup: a project with an intended repository the payment API is
    implemented_by and a demo interface, through the gates, built, with the create action ready."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("scenario", os.path.join(REPO_ROOT, "tools", "actions-scenario.py"))
    scenario = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scenario)
    with tempfile.TemporaryDirectory() as root:
        target = os.path.join(root, "demo")
        assert scenario.main(["setup", target, "--owner", "cynergis", "--port", "8797"]) == 0
        capsys.readouterr()
        project = Project.standard(target)
        with open(project.graph_path, encoding="utf-8") as f:
            nodes = {n["id"]: n for n in json.load(f)["nodes"]}
        assert nodes["repo.oto-actions-demo"]["status"] == "intended" and nodes["repo.oto-actions-demo"]["attributes"]["owner"] == "cynergis"
        assert nodes["repo.oto-actions-demo"]["source_doc"].endswith("-the-plan") and os.path.exists(
            os.path.join(project.layout.corpus, nodes["repo.oto-actions-demo"]["source_doc"] + ".md")), "the plan is an ingested source"
        assert nodes["interface.demo-health"]["attributes"]["url"] == "http://127.0.0.1:8797/payments/v2"
        assert os.path.exists(project.layout.database)
        assert main(["actions", "list", "--project", target]) == 0
        out = capsys.readouterr().out
        assert "ready on 1: repo.oto-actions-demo" in out and "ready on 2: interface.demo-health, interface.payments-v2" in out
        assert scenario.main(["setup", target]) == 1, "refuses to overwrite a project"
