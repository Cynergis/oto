"""Running OTO as a platform (docs/plans/people-and-graphs.md, phase 4): a directory of the organisation's graphs in the registry, one view of every
graph's versions and drift, a scheduled pull request when a pack moves, and retiring a graph."""
import base64
import json
import os
import sys

import pytest

from oto import __version__, access, directory, repo
from oto.model import registry
from oto.project import ProjectError
from oto.scaffold import init

from test_gate_and_secrets import _script
from test_route import _cli

FAKE_GH = r'''
import base64, json, os, sys
args = sys.argv[1:]
path = os.environ["FAKE_GH_STATE"]
state = json.load(open(path))
state["calls"].append(args)
json.dump(state, open(path, "w"))
method = args[args.index("--method") + 1] if "--method" in args else "GET"
target = next((a for a in args[1:] if a.startswith(("repos/", "orgs/", "search/")) or a == "user"), "")
def answer(payload="", code=0):
    sys.stdout.write(json.dumps(payload) if not isinstance(payload, str) else payload)
    sys.exit(code)
if target == "user":
    answer({"login": "owner"})
if target.startswith("search/repositories"):
    answer({"items": [{"full_name": name, "archived": info.get("archived", False)} for name, info in sorted(state["graphs"].items())]})
bare = target.split("?")[0]
parts = bare.split("/")
if parts[0] == "orgs" and len(parts) == 2:
    answer({"default_repository_permission": "none"})
if parts[0] == "repos":
    name = "/".join(parts[1:3])
    info = state["graphs"].get(name)
    if info is None:
        print("gh: Not Found (HTTP 404)", file=sys.stderr)
        sys.exit(1)
    rest = parts[3:]
    if rest[:1] == ["contents"]:
        file = "/".join(rest[1:])
        if file not in info.get("files", {}):
            print("gh: Not Found (HTTP 404)", file=sys.stderr)
            sys.exit(1)
        answer({"content": base64.b64encode(info["files"][file].encode()).decode(), "encoding": "base64"})
    if rest == ["actions", "workflows", "oto-deploy.yml", "runs"]:
        answer({"workflow_runs": info.get("runs", [])})
    if rest == ["pulls"]:
        answer(info.get("pulls", []))
    if rest == ["collaborators"]:
        answer(info.get("collaborators", []))
    if rest == ["teams"]:
        answer([])
    if rest == ["topics"]:
        if method == "PUT":
            info["topics_set"] = [args[i + 1].split("=", 1)[1] for i, a in enumerate(args) if a == "-f" and args[i + 1].startswith("names[]=")]
            json.dump(state, open(path, "w"))
            answer("")
        answer({"names": info.get("topics", ["oto-graph"])})
    if rest == [] and method == "PATCH":
        info["archived"] = True
        json.dump(state, open(path, "w"))
        answer("")
    if rest == []:
        answer({"full_name": name, "archived": info.get("archived", False)})
print("fake gh: not expected: %s" % args, file=sys.stderr)
sys.exit(2)
'''


def _graph(slug, pack="garage", release=1, engine="0.20.1", stewards=("dana",), store=None, uri=None, description=None):
    config = {"slug": slug, "name": slug.replace("-", " ").title(), "server_name": slug + "-kg", "ontology": {"name": pack, "release": release, "pack": {"name": pack, "release": release}}}
    if description:
        config["description"] = description
    if uri:
        config["neo4j"] = {"uri": uri, "database": "db1"}
    named = dict({"stewards": list(stewards), "reviewers": [], "contributors": [], "readers": []}, **({"store": store} if store else {}))
    return {"files": {"project.config.json": json.dumps(config), "oto.lock.json": json.dumps({"engine": {"version": engine}}),
                      ".github/oto-access.json": json.dumps(named), ".github/CODEOWNERS": access.code_owners_text(named),
                      "ontology.config.json": json.dumps({"classes": {"Bus": {}, "Garage": {}, "Document": {}}})},
            "runs": [{"conclusion": "success", "updated_at": "2026-11-03T10:00:00Z", "head_sha": "a" * 40}], "pulls": [],
            "collaborators": [{"login": s, "role_name": "admin"} for s in stewards]}


@pytest.fixture
def github(tmp_path, monkeypatch):
    state_file = tmp_path / "gh.json"
    state_file.write_text(json.dumps({"calls": [], "graphs": {}}))
    gh = tmp_path / "gh"
    _script(str(gh), "#!%s\n%s" % (sys.executable, FAKE_GH))
    monkeypatch.setenv("OTO_GH", str(gh))
    monkeypatch.setenv("FAKE_GH_STATE", str(state_file))

    class GitHub(object):
        def read(self):
            return json.loads(state_file.read_text())

        def graphs(self, **graphs):
            state = self.read()
            state["graphs"] = {"acme/" + k.replace("_", "-"): v for k, v in graphs.items()}
            state_file.write_text(json.dumps(state))
    return GitHub()


@pytest.fixture
def checkout(tmp_path):
    """A registry's checkout."""
    root = tmp_path / "registry"
    root.mkdir()
    (root / "registry.json").write_text(json.dumps({"name": "acme", "summary": "", "engine": "https://github.com/Cynergis/oto", "ontologies": [],
                                                    "packs": [{"name": "garage", "release": 3, "summary": "Buses", "path": "packs/garage"}]}))
    return str(root)


# ---- the directory ----

def test_scan_reads_each_repository_carrying_the_topic(github):
    github.graphs(northwind_fleet=_graph("northwind-fleet", description="Northwind's buses", uri="neo4j+s://x.databases.neo4j.io", store="acme/northwind-fleet-store"), acme_fleet=_graph("acme-fleet"))
    entries = directory.scan("acme")
    by_slug = {e["slug"]: e for e in entries}
    north = by_slug["northwind-fleet"]
    assert north["id"] == "graph.northwind-fleet" and north["label"] == "Northwind Fleet"
    assert north["subject"] == "Northwind Fleet: Northwind's buses" and north["reach"] == "northwind-fleet-kg"
    assert north["repository"] == "acme/northwind-fleet" and north["store"] == "acme/northwind-fleet-store" and north["owners"] == ["dana"]
    assert north["pack"] == "garage" and north["pack_release"] == 1 and north["engine"] == "0.20.1"
    assert north["neo4j"] == {"uri": "neo4j+s://x.databases.neo4j.io", "database": "db1"}
    assert "Bus" in north["classes"] and "Document" not in north["classes"][:2]
    query = next(c for c in github.read()["calls"] if c[1].startswith("search/repositories"))[1]
    assert "org:acme" in query and "topic:oto-graph" in query


def test_scan_skips_an_archived_graph_and_a_repository_that_is_no_graph(github):
    github.graphs(old=dict(_graph("old"), archived=True), notes={"files": {}})
    assert directory.scan("acme") == []


def test_the_registry_holds_the_directory_and_validates_it(github, checkout):
    github.graphs(fleet=_graph("fleet"))
    code, out = _cli("registry", "graphs", checkout, "--org", "acme")
    assert code == 0, out
    index = registry.read_index(checkout)
    assert [g["slug"] for g in index["graphs"]] == ["fleet"]
    assert not [p for p in registry.index_problems(index) if "graph" in p]
    assert os.path.exists(os.path.join(checkout, ".github", "workflows", "oto-graphs.yml")), "a scheduled job keeps it, so no graph needs a token that can write here"


def test_two_graphs_with_one_slug_are_refused_and_nothing_is_written(github, checkout):
    github.graphs(one=_graph("same"), two=_graph("same"))
    before = open(os.path.join(checkout, "registry.json"), encoding="utf-8").read()
    code, out = _cli("registry", "graphs", checkout, "--org", "acme")
    assert code != 0 and "same" in out and "acme/one" in out and "acme/two" in out, "they would overwrite each other in one Neo4j database: %s" % out
    assert open(os.path.join(checkout, "registry.json"), encoding="utf-8").read() == before


def test_the_index_check_finds_two_graphs_with_one_slug():
    index = {"name": "acme", "ontologies": [], "packs": [], "graphs": [{"slug": "same", "repository": "acme/one"}, {"slug": "same", "repository": "acme/two"}]}
    assert any("same" in p for p in registry.index_problems(index))


def test_the_workflow_fills_the_directory_on_a_schedule_with_a_read_token():
    text = directory.WORKFLOW
    assert "schedule:" in text and "oto registry graphs . --org" in text and "secrets.OTO_DIRECTORY_TOKEN" in text and "contents: write" in text


def test_the_catalog_lists_the_graphs(github, checkout):
    from oto import catalog
    github.graphs(fleet=_graph("fleet", description="The fleet's buses"))
    assert _cli("registry", "graphs", checkout, "--org", "acme")[0] == 0
    index = registry.read_index(checkout)
    index["packs"] = []
    with open(os.path.join(checkout, "registry.json"), "w", encoding="utf-8") as f:
        json.dump(index, f)
    out, report = catalog.write(checkout, out=os.path.join(checkout, "site"))
    with open(os.path.join(out, "index.html"), encoding="utf-8") as f:
        page = f.read()
    assert "Graphs" in page and "The fleet&#x27;s buses" in page or "The fleet's buses" in page
    assert "acme/fleet" in page


def test_graphs_add_resolves_through_the_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "load_registries", lambda: [{"name": "acme", "index": {"graphs": [
        {"slug": "fleet", "label": "The Fleet", "subject": "The Fleet: buses", "repository": "acme/fleet", "neo4j": {"uri": "neo4j+s://x.databases.neo4j.io", "database": "db1"}},
        {"slug": "local", "label": "Local", "repository": "acme/local"}]}}])
    folder = str(tmp_path / "project")
    code, out = _cli("graphs", "add", "fleet", "--project", folder)
    assert code == 0, out
    with open(os.path.join(folder, "graphs", "fleet", "project.config.json"), encoding="utf-8") as f:
        config = json.load(f)
    assert config["neo4j"] == {"uri": "neo4j+s://x.databases.neo4j.io", "database": "db1"} and config["slug"] == "fleet" and config["name"] == "The Fleet"
    code, out = _cli("graphs", "add", "local", "--project", folder)
    assert code != 0 and "Neo4j" in out, "the directory has no address for it: %s" % out
    code, out = _cli("graphs", "add", "nowhere", "--project", folder)
    assert code != 0 and "--uri" in out, out


# ---- the fleet ----

def test_one_view_shows_every_graphs_versions_and_drift(github, checkout):
    github.graphs(fleet=_graph("fleet", release=1, engine="0.19.0"),
                  current=_graph("current", release=3, engine=__version__),
                  drifted=dict(_graph("drifted", release=3, engine=__version__), collaborators=[{"login": "dana", "role_name": "admin"}, {"login": "intruder", "role_name": "write"}]),
                  stale=dict(_graph("stale", release=3, engine=__version__), runs=[{"conclusion": "failure", "updated_at": "2026-10-01T10:00:00Z", "head_sha": "b" * 40}],
                             pulls=[{"number": 9, "created_at": "2026-01-01T00:00:00Z", "title": "old"}, {"number": 10, "created_at": "2026-11-03T00:00:00Z", "title": "new"}]))
    assert _cli("registry", "graphs", checkout, "--org", "acme")[0] == 0
    code, out = _cli("registry", "fleet", checkout, "--json", "--now", "2026-11-04T00:00:00Z")
    assert code == 0, out
    rows = {r["slug"]: r for r in json.loads(out)["graphs"]}
    assert rows["fleet"]["pack_release"] == 1 and rows["fleet"]["pack_latest"] == 3 and rows["fleet"]["pack_behind"] is True
    assert rows["fleet"]["engine"] == "0.19.0" and rows["fleet"]["engine_behind"] is True
    assert rows["current"]["pack_behind"] is False and rows["current"]["engine_behind"] is False and rows["current"]["drift"] == []
    assert any("intruder" in line for line in rows["drifted"]["drift"])
    assert rows["stale"]["last_deploy"]["conclusion"] == "failure" and rows["stale"]["stale_pull_requests"] == [9]
    code, out = _cli("registry", "fleet", checkout, "--now", "2026-11-04T00:00:00Z")
    assert code == 0, out
    for word in ("fleet", "drifted", "intruder", "0.19.0", "@1", "@3", "failure"):
        assert word in out, word


def test_a_graph_the_fleet_cant_read_says_so_and_the_others_still_show(github, checkout):
    github.graphs(fleet=_graph("fleet"))
    assert _cli("registry", "graphs", checkout, "--org", "acme")[0] == 0
    github.graphs(other=_graph("other"))
    code, out = _cli("registry", "fleet", checkout, "--json")
    assert code == 0, out
    row = json.loads(out)["graphs"][0]
    assert row["slug"] == "fleet" and row["problem"], row


def test_the_fleet_with_no_directory_says_how_to_make_one(checkout):
    code, out = _cli("registry", "fleet", checkout)
    assert code == 0 and "oto registry graphs" in out, out


# ---- a new pack release reaches each graph as a pull request ----

def test_a_scheduled_workflow_opens_the_update_as_a_pull_request():
    text = repo.files("acme", "Acme")[os.path.join(".github", "workflows", "oto-pack-update.yml")]
    assert "schedule:" in text and "workflow_dispatch" in text
    assert "oto ontology diff" in text and "oto ontology update" in text and "gh pr create" in text
    assert "oto/pack-update" in text and "--force-with-lease" in text or "--force" in text
    assert "if [ -z \"$(git status --porcelain" in text, "nothing changed means no pull request"
    assert "contents: write" in text and "pull-requests: write" in text


# ---- retiring a graph ----

@pytest.fixture
def retiring(github, tmp_path):
    github.graphs(fleet=_graph("fleet", store="acme/fleet-store"), fleet_store={"files": {}})
    root = str(tmp_path / "fleet")
    init(root, slug="fleet", name="Fleet", repo=True)
    access.write(root, {"stewards": ["dana"], "reviewers": [], "contributors": [], "readers": [], "store": "acme/fleet-store"})
    return root


def test_retire_archives_both_repositories_and_leaves_the_directory(retiring, github):
    code, out = _cli("repo", "retire", "--repo", "acme/fleet", "--confirm", "acme/fleet", "--project", retiring)
    assert code == 0, out
    graphs = github.read()["graphs"]
    assert graphs["acme/fleet"]["archived"] is True and graphs["acme/fleet-store"]["archived"] is True
    assert graphs["acme/fleet"]["topics_set"] == [], "off the topic, so the directory drops it"
    calls = [" ".join(c) for c in github.read()["calls"]]
    assert calls.index(next(c for c in calls if "/topics" in c and "PUT" in c)) < calls.index(next(c for c in calls if "PATCH" in c)), "an archived repository can't change its topics"
    assert not [c for c in calls if "DELETE" in c], "archived, never deleted: the record stays"
    assert "Neo4j" in out, "it says what's left"


def test_retire_needs_the_name_typed(retiring, github):
    code, out = _cli("repo", "retire", "--repo", "acme/fleet", "--project", retiring)
    assert code != 0 and "--confirm" in out, out
    code, out = _cli("repo", "retire", "--repo", "acme/fleet", "--confirm", "acme/other", "--project", retiring)
    assert code != 0 and not github.read()["graphs"]["acme/fleet"].get("archived"), out


def test_retire_can_delete_the_graphs_nodes_from_neo4j(retiring, github, monkeypatch):
    from oto.targets import neo4j as target
    seen = {}

    class FakeDriver(object):
        def close(self):
            seen["closed"] = True

    def delete(driver, database, slug):
        seen.update(database=database, slug=slug)
        return 121
    monkeypatch.setattr(target, "open_driver", lambda conf: FakeDriver())
    monkeypatch.setattr(target, "delete_project", delete)
    monkeypatch.setenv("NEO4J_PASSWORD", "a-secret-value")
    config_path = os.path.join(retiring, "project.config.json")
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    config["neo4j"] = {"uri": "neo4j+s://x.databases.neo4j.io", "database": "db1"}
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f)
    code, out = _cli("repo", "retire", "--repo", "acme/fleet", "--confirm", "acme/fleet", "--neo4j", "--project", retiring)
    assert code == 0, out
    assert seen == {"database": "db1", "slug": "fleet", "closed": True} and "121" in out and "a-secret-value" not in out


def test_delete_project_touches_only_that_graph():
    from oto.targets import neo4j as target
    ran = []

    class Driver(object):
        def execute_query(self, query, params=None, database_=None, **kw):
            ran.append((query, params, database_))

            class Summary(object):
                class counters(object):
                    nodes_deleted = 7
            return [], Summary(), []
    assert target.delete_project(Driver(), "db1", "fleet") == 7
    assert ran[0][1] == {"project": "fleet", "batch": target.DELETE_BATCH} and ran[0][2] == "db1" and "{project: $project}" in ran[0][0]
    with pytest.raises(ProjectError):
        target.delete_project(Driver(), "db1", "")


# ---- a graph on a pack really sees a new release: real runs found it never did ----

@pytest.fixture
def released(tmp_path, monkeypatch):
    """A pack published to a registry, and a project started from it by name."""
    from test_ontology_as_code import _add_term
    from test_pack_workspace import _cli as _pack_cli, _fill
    monkeypatch.setenv("OTO_REGISTRIES", str(tmp_path / "registries.json"))
    monkeypatch.setenv("OTO_PACKS", str(tmp_path / "packs"))
    monkeypatch.setenv("OTO_ONTOLOGIES", str(tmp_path / "ontologies"))
    code, out = _pack_cli("pack", "new", "garage", "--to", str(tmp_path / "ws"), "--maintainer", "Test Driver", "--summary", "Buses")
    assert code == 0, out
    workspace = str(tmp_path / "ws" / "garage")
    _fill(workspace)
    registry_url = str(tmp_path / "registry.git")
    import subprocess
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", registry_url], check=True)
    code, out = _pack_cli("pack", "publish", "--from", workspace, "--to", registry_url, "--note", "first", "--registry-name", "acme")
    assert code == 0, out
    code, out = _pack_cli("registry", "add", registry_url)
    assert code == 0, out
    code, out = _pack_cli("pack", "add", "garage")
    assert code == 0, out
    root = str(tmp_path / "team")
    code, out = _pack_cli("init", "--name", "Team", "--slug", "team", "--project", root, "--pack", "garage")
    assert code == 0, out

    def release():
        _add_term(workspace, "Depot", "kept_at", "depot-of-a-bus")
        assert _pack_cli("pack", "format", workspace)[0] == 0
        code, out = _pack_cli("pack", "publish", "--from", workspace, "--to", registry_url, "--note", "Depots")
        assert code == 0, out
        assert _pack_cli("registry", "refresh")[0] == 0
    return root, release, _pack_cli


def test_a_bare_pack_name_is_never_taken_for_a_folder_of_that_name(tmp_path, monkeypatch, released):
    root, _release, cli = released
    (tmp_path / "here" / "garage").mkdir(parents=True)
    monkeypatch.chdir(tmp_path / "here")
    other = str(tmp_path / "other")
    code, out = cli("init", "--name", "Other", "--slug", "other", "--project", other, "--pack", "garage")
    assert code == 0, out
    with open(os.path.join(other, "project.config.json"), encoding="utf-8") as f:
        assert json.load(f)["vocabulary"] == "derived", "a folder here called garage made the project keep its own copy, cut off from the pack"


def test_status_and_diff_see_a_new_release_of_the_pack_and_update_takes_it(released):
    root, release, cli = released
    with open(os.path.join(root, "project.config.json"), encoding="utf-8") as f:
        assert json.load(f)["vocabulary"] == "derived"
    code, out = cli("ontology", "diff", "--project", root)
    assert code == 0 and "Nothing upstream to take" in out, out
    release()
    code, out = cli("status", "--project", root)
    assert code == 0 and "@2 available" in out, out
    assert cli("pack", "add", "garage", "--force")[0] == 0
    code, out = cli("ontology", "diff", "--project", root)
    assert code == 0 and "Depot" in out and "kept_at" in out and "release 2" in out, out
    assert "oto ontology update" in out and "can be copied" not in out, "this text is the update pull request's description, and the vocabulary here comes from the pack"
    code, out = cli("ontology", "update", "--project", root)
    assert code == 0, out
    with open(os.path.join(root, "ontology.config.json"), encoding="utf-8") as f:
        assert "Depot" in json.load(f)["classes"]
    with open(os.path.join(root, "project.config.json"), encoding="utf-8") as f:
        assert json.load(f)["ontology"]["pack"]["release"] == 2, "or the next run offers the same release again"
    code, out = cli("ontology", "diff", "--project", root)
    assert code == 0 and "Nothing upstream to take" in out, out
    code, out = cli("status", "--project", root)
    assert "@2 available" not in out, out
    assert cli("build", "--project", root)[0] == 0


def test_the_update_pull_request_says_its_checks_need_a_person_to_start_them():
    """GitHub starts no workflow for what the Actions token does, so the gate never runs on this pull request until someone reopens it."""
    text = repo.files("acme", "Acme")[os.path.join(".github", "workflows", "oto-pack-update.yml")]
    assert "close it and reopen it" in text
    assert text.index("close it and reopen it") < text.index("gh pr create")

