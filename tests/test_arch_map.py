"""The code map and compile on merge (roadmap Epic H, H2).

`oto arch map --repo <path> --repository repo.<id> --at <date>` scans a code repository by a
declared convention (`oto.codemap.json` at its root, or the default: every directory under `src/`
is a module of the component named after it) into a code-map document and a proposal: a
`CodeModule` per module with its path and language, `located_in` the repository the estate declares,
`implemented_by` from the component the convention names when the graph holds it (and a gap, never
an invented component, when it does not: AR9 lists the untraced module), and the last `Commit`
that `touches` each module when the repository is a git checkout. `oto arch compile` runs the
imports and the map the project config declares, takes them through the gates and builds, which
is what the `oto architecture` workflow does on every merge to main."""
import contextlib
import io
import json
import os
import subprocess

import pytest

from oto import arch, repo as _repo
from oto.cli import main
from oto.curate import session
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INVOICE = os.path.join(ROOT, "tests", "fixtures", "arch", "invoice-platform.model.json")   # the plain framework's model: the reified model as a file


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


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=Sam Lee", "-c", "user.email=sam@example.com", "-c", "commit.gpgsign=false"] + list(args),
                          cwd=cwd, check=True, capture_output=True, text=True).stdout


def _tree(path, files):
    for relative, text in files.items():
        full = os.path.join(path, relative)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)


@pytest.fixture
def code(tmp_path):
    """A git repository with three modules under src/, a shared library, and two commits."""
    path = str(tmp_path / "invoice-platform")
    _tree(path, {"src/intake/app.py": "print('intake')\n", "src/intake/model.py": "x = 1\n", "src/intake/README.md": "# intake\n",
                 "src/scheduler/main.py": "print('scheduler')\n", "src/legacy/old.js": "console.log(1)\n", "src/legacy/older.js": "\n",
                 "lib/shared/util.py": "def f(): pass\n", "node_modules/x/index.js": "\n", "README.md": "# platform\n"})
    _git(path, "init", "-q", "-b", "main")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "intake: validate supplier IBAN before storing", "--date", "2026-10-18T10:00:00+00:00")
    with open(os.path.join(path, "src/scheduler/main.py"), "a", encoding="utf-8") as f:
        f.write("# schedule\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "scheduler: read through the intake API", "--date", "2026-10-20T10:00:00+00:00")
    return path


@pytest.fixture
def described(tmp_path, plain_framework):
    """An architecture project with the invoice model applied through a framework adapter (the `plain`
    one the tests carry: the engine ships none, ADR-0008): the components the code implements exist."""
    root = str(tmp_path / "arch")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="arch", name="Architecture", ontology="architecture", empty=True)
    seed = os.path.join(root, "seed.json")
    with open(seed, "w", encoding="utf-8") as f:
        json.dump({"source_doc": "estate", "as_of": "2026-10-01", "nodes": [
            {"id": "environment.production", "type": "Environment", "label": "Production", "attributes": {}},
            {"id": "repo.invoice-platform", "type": "Repository", "label": "invoice-platform", "attributes": {"owner": "acme", "name": "invoice-platform"}}],
            "edges": []}, f)
    _gates(root, seed, "the estate")
    code, out = _cli("arch", "import", "--framework", "plain", "--file", INVOICE, "--at", "2026-10-27", "--environment", "environment.production", "--project", root)
    assert code == 0, out
    with open(os.path.join(root, "proposals", "invoice-platform.json"), encoding="utf-8") as f:
        proposal = json.load(f)
    proposal["nodes"] = [n for n in proposal["nodes"] if n["id"] != "component.reporting-lake"]
    proposal["edges"] = [e for e in proposal["edges"] if "component.reporting-lake" not in (e["from"], e["to"])]
    with open(os.path.join(root, "proposals", "invoice-platform.json"), "w", encoding="utf-8") as f:
        json.dump(proposal, f)
    _gates(root, os.path.join(root, "proposals", "invoice-platform.json"), "the model")
    return root


# ---- the convention and the scan, as functions ----

def test_the_default_convention_maps_src_directories_to_components(code):
    found = arch.scan(code, arch.DEFAULT_CONVENTION)
    assert [m["path"] for m in found["modules"]] == ["src/intake", "src/legacy", "src/scheduler"], "every directory under src/, in order"
    by_path = {m["path"]: m for m in found["modules"]}
    assert by_path["src/intake"]["component"] == "component.intake" and by_path["src/intake"]["language"] == "python"
    assert by_path["src/legacy"]["language"] == "javascript" and by_path["src/scheduler"]["component"] == "component.scheduler"
    assert by_path["src/intake"]["commit"]["sha"] and by_path["src/intake"]["commit"]["author"] == "Sam Lee" and by_path["src/intake"]["commit"]["committed_on"] == "2026-10-18"
    assert by_path["src/intake"]["commit"]["message"] == "intake: validate supplier IBAN before storing"
    assert by_path["src/scheduler"]["commit"]["committed_on"] == "2026-10-20", "the last commit that touched the module"
    assert found["git"] is True


def test_a_declared_convention_names_components_ignores_paths_and_leaves_shared_code_untraced(code):
    convention = {"modules": [{"path": "src/*", "component": "component.invoice-{name}", "except": ["src/legacy"]},
                              {"path": "src/legacy", "component": "component.payment-scheduler"},
                              {"path": "lib/*", "component": None}],
                  "ignore": ["node_modules"]}
    found = arch.scan(code, convention)
    by_path = {m["path"]: m for m in found["modules"]}
    assert set(by_path) == {"src/intake", "src/scheduler", "src/legacy", "lib/shared"}
    assert by_path["src/intake"]["component"] == "component.invoice-intake" and by_path["src/legacy"]["component"] == "component.payment-scheduler"
    assert by_path["lib/shared"]["component"] is None, "shared code implements no component"
    assert "node_modules" not in json.dumps(found)
    with open(os.path.join(code, "oto.codemap.json"), "w", encoding="utf-8") as f:
        json.dump(convention, f)
    assert arch.convention_for(code) == convention, "oto.codemap.json at the repository root is the convention"
    assert arch.convention_for(str(os.path.dirname(code))) == arch.DEFAULT_CONVENTION
    with pytest.raises(arch.ArchError):
        arch.scan(code, {"modules": [{"component": "x"}]})
    with pytest.raises(arch.ArchError):
        arch.scan(code, {"modules": "src/*"})


def test_a_tree_that_is_not_a_git_checkout_maps_without_commits(tmp_path):
    path = str(tmp_path / "plain")
    _tree(path, {"src/a/x.go": "package a\n"})
    found = arch.scan(path, arch.DEFAULT_CONVENTION)
    assert found["git"] is False and found["modules"][0]["commit"] is None and found["modules"][0]["language"] == "go"


# ---- the command ----

def test_map_writes_the_document_and_a_proposal_cited_to_it_and_names_what_the_graph_lacks(described, code):
    root = described
    with open(os.path.join(code, "oto.codemap.json"), "w", encoding="utf-8") as f:
        json.dump({"modules": [{"path": "src/*", "component": "component.invoice-{name}", "except": ["src/legacy", "src/scheduler"]},
                               {"path": "src/scheduler", "component": "component.payment-scheduler"},
                               {"path": "src/legacy", "component": "component.lost-and-found"},
                               {"path": "lib/*", "component": None}], "ignore": ["node_modules"]}, f)
    code_, out = _cli("arch", "map", "--repo", code, "--repository", "repo.invoice-platform", "--at", "2026-10-27", "--project", root)
    assert code_ == 0, out
    assert "4 module(s)" in out and "2 commit(s)" in out and "codemap-invoice-platform" in out and "curate add" in out, out
    assert "component.lost-and-found" in out and "graph lacks" in out, "the convention names a component the graph does not hold: the module is proposed untraced"
    text = open(os.path.join(root, "build", "documents", "codemap-invoice-platform.md"), encoding="utf-8").read()
    assert text.startswith("# Code map of invoice-platform") and "oto.codemap.json" in text
    assert "- src/intake (python): component.invoice-intake" in text and "- lib/shared (python): no component" in text
    assert "  - " in text and "2026-10-18 Sam Lee: intake: validate supplier IBAN before storing" in text
    assert os.path.exists(os.path.join(root, "archive", "codemap-invoice-platform.md"))
    with open(os.path.join(root, "proposals", "codemap-invoice-platform.json"), encoding="utf-8") as f:
        proposal = json.load(f)
    assert proposal["source_doc"] == "codemap-invoice-platform" and proposal["as_of"] == "2026-10-27"
    nodes = {n["id"]: n for n in proposal["nodes"]}
    intake = nodes["codemodule.invoice-platform-src-intake"]
    assert intake["type"] == "CodeModule" and intake["label"] == "src/intake" and intake["attributes"] == {"path": "src/intake", "language": "python"}
    assert intake["evidence"] == [{"doc": "codemap-invoice-platform", "where": "modules", "quote": "src/intake (python)"}]
    assert "lib/shared" in intake["summary"] or "invoice-platform" in intake["summary"]
    commits = [n for n in proposal["nodes"] if n["type"] == "Commit"]
    assert len(commits) == 2 and all(len(c["attributes"]["sha"]) == 40 and c["attributes"]["committed_on"] and c["attributes"]["author"] == "Sam Lee" for c in commits)
    first = next(c for c in commits if c["attributes"]["committed_on"] == "2026-10-18")
    assert first["attributes"]["message"] == "intake: validate supplier IBAN before storing" and first["id"] == "commit.%s" % first["attributes"]["sha"][:12]
    assert nodes["document.codemap-invoice-platform"]["attributes"] == {"kind": "architecture"}
    edges = {(e["from"], e["rel"], e["to"]) for e in proposal["edges"]}
    assert ("codemodule.invoice-platform-src-intake", "located_in", "repo.invoice-platform") in edges
    assert ("component.invoice-intake", "implemented_by", "codemodule.invoice-platform-src-intake") in edges
    assert ("component.payment-scheduler", "implemented_by", "codemodule.invoice-platform-src-scheduler") in edges
    assert not any(to == "codemodule.invoice-platform-src-legacy" and rel == "implemented_by" for _f, rel, to in edges), "untraced, not invented"
    assert not any(to == "codemodule.invoice-platform-lib-shared" and rel == "implemented_by" for _f, rel, to in edges)
    assert (first["id"], "touches", "codemodule.invoice-platform-src-intake") in edges and (first["id"], "touches", "codemodule.invoice-platform-lib-shared") in edges, "one commit, every module it touched"
    assert not any(n["type"] in ("Component", "Repository") for n in proposal["nodes"]), "the estate's own, never invented"


def test_the_map_goes_through_the_gates_and_grows_with_the_commits(described, code):
    root = described
    with open(os.path.join(code, "oto.codemap.json"), "w", encoding="utf-8") as f:
        json.dump({"modules": [{"path": "src/intake", "component": "component.invoice-intake"}, {"path": "src/scheduler", "component": "component.payment-scheduler"},
                               {"path": "src/legacy", "component": None}, {"path": "lib/*", "component": None}], "ignore": ["node_modules"]}, f)
    code_, out = _cli("arch", "map", "--repo", code, "--repository", "repo.invoice-platform", "--at", "2026-10-27", "--project", root)
    assert code_ == 0, out
    _gates(root, os.path.join(root, "proposals", "codemap-invoice-platform.json"), "the code map")
    code_, out = _cli("query", "--project", root, "ask", "AR5", "NODE=component.invoice-intake")
    assert code_ == 0 and "status: answered" in out and "src/intake" in out and "Sam Lee" in out and "2026-10-18" in out, out
    code_, out = _cli("query", "--project", root, "ask", "AR9")
    assert code_ == 0 and "status: answered" in out and "src/legacy" in out and "lib/shared" in out and "src/intake" not in out and "src/scheduler" not in out, \
        "the modules the convention leaves to no component: untraced"
    code_, out = _cli("ontology", "check", "--project", root)
    assert code_ == 0 and "every node satisfies them" in out, out
    before = session.live(Project.standard(root))
    with open(os.path.join(code, "src/intake/app.py"), "a", encoding="utf-8") as f:
        f.write("# again\n")
    _git(code, "add", "-A")
    _git(code, "commit", "-q", "-m", "intake: log the IBAN check", "--date", "2026-10-28T10:00:00+00:00")
    code_, out = _cli("arch", "map", "--repo", code, "--repository", "repo.invoice-platform", "--at", "2026-10-28", "--project", root)
    assert code_ == 0, out
    _gates(root, os.path.join(root, "proposals", "codemap-invoice-platform.json"), "the code map again")
    after = session.live(Project.standard(root))
    assert len(after["nodes"]) == len(before["nodes"]) + 1, "one new commit; the modules are the same facts"
    assert sum(1 for n in after["nodes"] if n["type"] == "Commit") == 3
    code_, out = _cli("query", "--project", root, "ask", "AR5", "NODE=component.invoice-intake")
    assert code_ == 0 and "2026-10-28" in out and "2026-10-18" in out, "the history of the module's commits, not only the last"


def test_map_refuses_what_it_cannot_cite(described, code, tmp_path):
    root = described
    code_, out = _cli("arch", "map", "--repo", str(tmp_path / "nowhere"), "--repository", "repo.invoice-platform", "--at", "2026-10-27", "--project", root)
    assert code_ == 1 and "nowhere" in out, out
    code_, out = _cli("arch", "map", "--repo", code, "--repository", "repo.nope", "--at", "2026-10-27", "--project", root)
    assert code_ == 1 and "repo.nope" in out and "estate" in out, "the repository is the estate's to declare"
    code_, out = _cli("arch", "map", "--repo", code, "--repository", "repo.invoice-platform", "--project", root)
    assert code_ == 1 and "--at" in out, "the date is never defaulted"
    code_, out = _cli("arch", "map", "--repo", code, "--at", "2026-10-27", "--project", root)
    assert code_ == 1 and "--repository" in out, out
    with open(os.path.join(code, "oto.codemap.json"), "w", encoding="utf-8") as f:
        f.write("{not json")
    code_, out = _cli("arch", "map", "--repo", code, "--repository", "repo.invoice-platform", "--at", "2026-10-27", "--project", root)
    assert code_ == 1 and "oto.codemap.json" in out and "JSON" in out, out
    os.remove(os.path.join(code, "oto.codemap.json"))
    plain = str(tmp_path / "plain")
    with contextlib.redirect_stdout(io.StringIO()):
        init(plain, slug="plain", name="Plain", ontology="organization-process")
    code_, out = _cli("arch", "map", "--repo", code, "--repository", "repo.invoice-platform", "--at", "2026-10-27", "--project", plain)
    assert code_ == 1 and "CodeModule" in out, out
    assert not os.path.exists(os.path.join(root, "proposals", "codemap-nope.json"))


# ---- compile on merge ----

def test_compile_runs_what_the_config_declares_through_the_gates_and_builds(described, code):
    root = described
    model = os.path.join(root, "architecture", "invoice.model.json")
    os.makedirs(os.path.dirname(model), exist_ok=True)
    with open(INVOICE, encoding="utf-8") as f:
        m = json.load(f)
    m["proposal"]["nodes"] = [n for n in m["proposal"]["nodes"] if n["id"] != "component.reporting-lake"]
    m["proposal"]["edges"] = [e for e in m["proposal"]["edges"] if "component.reporting-lake" not in (e["from"], e["to"])]
    with open(model, "w", encoding="utf-8") as f:
        json.dump(m, f)
    config_path = os.path.join(root, "project.config.json")
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    config["arch"] = {"plain": ["architecture/invoice.model.json"], "environment": "environment.production",
                      "codemap": {"repo": os.path.relpath(code, root), "repository": "repo.invoice-platform"}}
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    code_, out = _cli("arch", "compile", "--at", "2026-10-28", "--by", "oto architecture", "--note", "compiled from abc123", "--project", root)
    assert code_ == 0, out
    assert "invoice" in out and "codemap-invoice-platform" in out and "applied" in out and "built" in out, out
    graph = session.live(Project.standard(root))
    assert any(n["type"] == "CodeModule" for n in graph["nodes"]) and any(n["type"] == "Relationship" for n in graph["nodes"])
    code_, out = _cli("audit", "log", "--project", root)
    assert code_ == 0 and "compiled from abc123" in out, out
    code_, out = _cli("audit", "verify", "--project", root)
    assert code_ == 0, out
    code_, out = _cli("arch", "compile", "--at", "2026-10-29", "--by", "oto architecture", "--note", "compiled again", "--project", root)
    assert code_ == 0 and "applied" in out, "the same sources again: re-attested, nothing duplicated"
    assert sum(1 for n in session.live(Project.standard(root))["nodes"] if n["type"] == "CodeModule") == 3


def test_compile_refuses_at_the_gate_and_leaves_no_candidate(described, code):
    root = described
    config_path = os.path.join(root, "project.config.json")
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    config["arch"] = {"plain": [os.path.relpath(INVOICE, root)]}     # the lakehouse composed in nothing, deployed nowhere
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    code_, out = _cli("arch", "compile", "--at", "2026-10-28", "--by", "oto architecture", "--project", root)
    assert code_ == 1 and "reporting-lake" in out and "blocking" in out, out
    assert not session.exists(Project.standard(root)), "a refused compile leaves no candidate behind"
    config["arch"] = {}
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    code_, out = _cli("arch", "compile", "--at", "2026-10-28", "--by", "oto architecture", "--project", root)
    assert code_ == 1 and "arch" in out and "project.config.json" in out, "nothing declared: nothing to compile"
    code_, out = _cli("arch", "compile", "--by", "oto architecture", "--project", root)
    assert code_ == 1 and "--at" in out


def test_the_repository_gains_the_architecture_workflow():
    files = _repo.files("acme", "Acme")
    text = files[os.path.join(".github", "workflows", "oto-architecture.yml")]
    assert text.startswith("name: oto architecture")
    assert 'pip install "oto-kg[intake] @ git+${ENGINE}"' in text and "vars.OTO_ENGINE || '%s'" % _repo.ENGINE in text
    assert 'OTO_ENGINE_TOKEN: ${{ secrets.OTO_ENGINE_TOKEN }}' in text and 'insteadOf "https://github.com/"' in text
    assert "on:\n  push:\n    branches: [ main ]" in text and "workflow_dispatch" in text
    assert "oto arch compile --project ." in text and '--by "oto architecture"' in text and "github.sha" in text
    assert "github.event.head_commit.author.name != 'oto architecture'" in text, "its own commit never compiles again"
    assert "git add -A graph.json" in text and "git push" in text
    assert "compiled from" in text
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        assert "oto arch map" in f.read()
