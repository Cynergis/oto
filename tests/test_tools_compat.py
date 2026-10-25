"""Actions became Tools (roadmap L2), and nothing that used the old name breaks: a project that still
declares `Action` and keeps its files under `actions/` builds, lists and answers as before; a project
that upgrades sees a rename, not a removal, and its old nodes read as the new class; the old command,
the old query and the old MCP tool still answer and say what they are now called; the old IRI stays
resolvable in the export, mapped to the new one."""
import glob
import io
import json
import os
import contextlib

import pytest

from oto.cli import main
from oto.project import Project
from oto.scaffold import init


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _rewrite(path, fn):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data = fn(data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _as_action_vocabulary(config):
    """The vocabulary as a project wrote it before the rename: the class is `Action`, nothing says `was`."""
    classes = config["classes"]
    classes["Action"] = {k: v for k, v in classes.pop("Tool").items() if k != "was"}
    for spec in config["properties"].values():
        for end in ("domain", "range"):
            if spec.get(end):
                spec[end] = "|".join("Action" if x == "Tool" else x for x in spec[end].split("|"))
    for section in ("attributes",):
        if "Tool" in (config.get(section) or {}):
            config[section]["Action"] = config[section].pop("Tool")
    return config


@pytest.fixture
def legacy(tmp_path):
    """A software-architecture project exactly as one made before the rename: `Action` in its vocabulary,
    rationale and questions; its definitions under actions/ with `action.` ids."""
    root = str(tmp_path / "legacy")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="legacy", name="Legacy", ontology="software-architecture")
    _rewrite(os.path.join(root, "ontology.config.json"), _as_action_vocabulary)
    _rewrite(os.path.join(root, "ontology.rationale.json"),
             lambda r: dict(r, classes={("Action" if k == "Tool" else k): v for k, v in r["classes"].items()}))

    def questions(q):
        text = json.dumps(q).replace('"type": "Tool"', '"type": "Action"')
        return json.loads(text)
    _rewrite(os.path.join(root, "questions.json"), questions)
    os.rename(os.path.join(root, "tools"), os.path.join(root, "actions"))
    for path in glob.glob(os.path.join(root, "actions", "tool.*.json")):
        _rewrite(path, lambda a: dict(a, id=a["id"].replace("tool.", "action.", 1)))
        os.rename(path, path.replace("tool.", "action.", 1))
    return root


def test_a_project_made_before_the_rename_checks_lists_builds_and_answers_unchanged(legacy):
    code, out = _cli("actions", "check", "--project", legacy)
    assert code == 0 and "3 tool(s) usable" in out and "action.check-repository" in out
    assert "oto tools" in out, "the old command says its new name"
    code, out = _cli("tools", "list", "--project", legacy)
    assert code == 0 and "action.check-repository" in out
    code, out = _cli("build", "--project", legacy)
    assert code == 0, out
    code, out = _cli("query", "--project", legacy, "entity", "action.check-repository")
    assert code == 0 and "[Action" in out, "its own vocabulary still calls the class Action"
    for route in ("actions", "tools"):
        code, out = _cli("query", "--project", legacy, route, "--on", "repo.payment-api")
        assert code == 0 and "action.check-repository" in out, route


def test_a_fresh_project_gets_tools_and_tool_ids(tmp_path):
    root = str(tmp_path / "fresh")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="fresh", name="Fresh", ontology="software-architecture")
    assert sorted(os.listdir(os.path.join(root, "tools"))) == ["tool.check-repository.json", "tool.create-repository.json",
                                                                "tool.probe-interface.json"]
    assert not os.path.exists(os.path.join(root, "actions"))
    with open(os.path.join(root, "ontology.config.json"), encoding="utf-8") as f:
        config = json.load(f)
    assert "Tool" in config["classes"] and "Action" not in config["classes"]
    assert config["classes"]["Tool"]["was"] == ["Action"]
    code, out = _cli("tools", "check", "--project", root)
    assert code == 0 and "3 tool(s) usable" in out


def test_an_upgraded_project_sees_a_rename_not_a_removal_and_its_old_nodes_read_as_the_new_class(tmp_path):
    root = str(tmp_path / "up")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="up", name="Up", ontology="software-architecture")
    project = Project.standard(root)
    questions_path = os.path.join(root, "questions.json")
    new_config = open(project.ontology_config_path, encoding="utf-8").read()
    new_questions = open(questions_path, encoding="utf-8").read()
    _rewrite(project.ontology_config_path, _as_action_vocabulary)
    _rewrite(questions_path, lambda q: json.loads(json.dumps(q).replace('"type": "Tool"', '"type": "Action"')))
    code, out = _cli("ontology", "accept", "--project", root)
    assert code == 0, out
    for path, text in ((project.ontology_config_path, new_config), (questions_path, new_questions)):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    code, out = _cli("ontology", "check", "--project", root)
    assert code == 0 and "class renamed" in out and "Action" in out and "Tool" in out, out
    assert "class removed" not in out and "breaking" not in out.lower().replace("no breaking", ""), out

    def old_node(graph):
        graph["nodes"].append({"id": "action.legacy-ping", "type": "Action", "label": "Legacy ping", "aliases": [],
                               "summary": "Recorded before the rename.", "attributes": {}, "tags": [], "as_of": "2026-01-01",
                               "valid_from": "2026-01-01", "source_doc": "sample", "sources": ["sample"], "status": "current"})
        return graph
    _rewrite(project.graph_path, old_node)
    code, out = _cli("curate", "start", "--project", root)
    assert code == 0
    code, out = _cli("curate", "check", "--project", root)
    assert "type 'Action' is not declared" not in out, "a former name of a declared class is that class"
    _cli("curate", "abort", "--project", root)
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    assert "Action" in out and "Tool" in out and "former" in out, "the build says what it read the old name as"
    code, out = _cli("query", "--project", root, "entity", "action.legacy-ping")
    assert code == 0 and "[Tool" in out
    code, out = _cli("query", "--project", root, "define", "Action")
    assert code == 0 and "Tool" in out and "formerly" in out.lower()
    ttl = "".join(open(p, encoding="utf-8").read() for p in glob.glob(os.path.join(project.layout.ontology, "*.ttl")))
    assert "oto-core:Action" in ttl and "owl:equivalentClass oto-core:Tool" in ttl and "owl:deprecated true" in ttl


def test_the_old_mcp_tool_is_kept_one_release_and_says_its_new_name():
    from oto.serve import engine
    names = {t["name"]: t for t in engine.TOOLS}
    assert "kg_tools" in names and "kg_actions" in names
    assert "kg_tools" in names["kg_actions"]["description"] and "old name" in names["kg_actions"]["description"]
    assert "action" not in names["kg_tools"]["description"].lower().replace("transaction", ""), "no Action left in the new tool"
