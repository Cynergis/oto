"""Ontology registries: a git repository with an index, added by URL, ontologies fetched by name
or URL into the user directory with their provenance, pinned versions from tags, and updates.
Every registry here is a local bare repository, so the suite never touches the network."""
import json
import os
import subprocess
import tempfile

import pytest

from oto import gitx
from oto.cli import main
from oto.model import registry as registry, ontologies
from oto.project import Project, ProjectError
from oto.scaffold import init

from test_ontology_contract import WHY, _node, write_ontology


@pytest.fixture
def home(monkeypatch):
    """An isolated user ontology directory and registries file."""
    with tempfile.TemporaryDirectory() as root:
        monkeypatch.setenv(ontologies.USER_DIR_ENV, os.path.join(root, "ontologies"))
        monkeypatch.setenv(registry.REGISTRIES_ENV, os.path.join(root, "registries.json"))
        monkeypatch.delenv(registry.TOKEN_ENV, raising=False)
        yield root


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t",
                            GIT_COMMITTER_EMAIL="t@x", GIT_TERMINAL_PROMPT="0"))


def _claims(work, version, extra_class=None):
    classes = {"Claim": {"definition": "a claim"}}
    if extra_class:
        classes[extra_class] = {"definition": "added in v%d" % version}
    write_ontology(work, "claims", classes, {"about": {"domain": "Claim", "range": "Document", "definition": "about"}},
                   {"nodes": [_node("claim.1", "Claim", "One")], "edges": []},
                   manifest_body={"release": version, "summary": "claims v%d" % version, "extends": ["oto-core"],
                                  "carries": ["vocabulary", "rationale", "sample", "readme"]}, temporal=False)


def make_registry(root, name="acme"):
    """A bare registry repository with `claims` at v1 (tagged) then v2, and `tiny` at v1."""
    bare = os.path.join(root, "%s.git" % name)
    _git(["init", "--quiet", "--bare", "-b", "main", bare], root)
    work = os.path.join(root, "%s-work" % name)
    _git(["clone", "--quiet", bare, work], root)

    def index(version):
        with open(os.path.join(work, "registry.json"), "w", encoding="utf-8") as f:
            json.dump({"name": name, "summary": "test registry",
                       "ontologies": [{"name": "claims", "release": version, "summary": "claims v%d" % version,
                                      "path": "claims", "extends": ["oto-core"]},
                                     {"name": "tiny", "release": 1, "summary": "tiny", "path": "tiny"}]}, f)

    _claims(work, 1)
    write_ontology(work, "tiny", {"Thing": {"definition": "a thing"}}, {"near": {"domain": "Thing", "range": "Thing", "definition": "n"}},
                   {"nodes": [_node("t.1", "Thing", "One")], "edges": []}, manifest_body={"release": 1, "summary": "tiny"})
    index(1)
    _git(["add", "-A"], work); _git(["commit", "-q", "-m", "claims v1"], work)
    _git(["tag", registry.tag_for("claims", 1)], work)
    _claims(work, 2, extra_class="Adjuster")
    index(2)
    _git(["add", "-A"], work); _git(["commit", "-q", "-m", "claims v2"], work)
    _git(["push", "-q", "origin", "main", "--tags"], work)
    return bare, work


# ---- the index ----

def test_index_problems_name_each_fault(tmp_path):
    bad = {"name": "Acme", "ontologies": [{"name": "claims", "release": 0}, {"name": "claims", "release": 1, "path": "nowhere"},
                                          "junk", {"name": "ok", "release": 1, "source": "https://x/y"}]}
    text = "\n".join(registry.index_problems(bad, str(tmp_path)))
    for expected in ("lowercase `name`", "positive integer `release`", "needs a `path`", "listed twice",
                     "no directory 'nowhere'", "entry 3 is not an object"):
        assert expected in text, (expected, text)
    assert registry.index_problems({"name": "acme", "ontologies": []}) == []


def test_registry_check_compares_the_index_with_the_directories(home, capsys):
    bare, work = make_registry(home)
    assert main(["registry", "check", work]) == 0
    assert "index matches the directories" in capsys.readouterr().out
    with open(os.path.join(work, "claims", "manifest.json"), encoding="utf-8") as f:
        m = json.load(f)
    m["release"] = 9
    with open(os.path.join(work, "claims", "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(m, f)
    assert main(["registry", "check", work]) == 1
    assert "the index says release 2, the manifest says 9" in capsys.readouterr().out


# ---- registries ----

def test_add_list_refresh_and_remove_a_registry(home, capsys):
    bare, _work = make_registry(home)
    assert main(["registry", "add", bare]) == 0
    out = capsys.readouterr().out
    assert "registry acme: 2 ontologies" in out and "claims                 @2" in out
    records = registry.load_registries()
    assert [r["name"] for r in records] == ["acme"] and records[0]["url"] == bare and records[0]["commit"]
    assert os.path.exists(registry.registries_path())
    assert main(["registry", "list"]) == 0
    assert "acme" in capsys.readouterr().out
    # the listing shows what a registry offers but this machine lacks
    assert main(["ontology", "list"]) == 0
    out = capsys.readouterr().out
    assert "in a registry, not on this machine" in out and "claims                 @2   claims v2  [acme]" in out
    assert main(["registry", "refresh"]) == 0
    assert "refreshed acme" in capsys.readouterr().out
    other, _w = make_registry(home, name="other")
    with pytest.raises(ProjectError, match="already registered"):
        registry.add_registry(other, name="acme")
    registry.add_registry(other)                                  # under its own name it is fine
    assert [r["name"] for r in registry.load_registries()] == ["acme", "other"]
    assert main(["registry", "remove", "acme"]) == 0
    assert [r["name"] for r in registry.load_registries()] == ["other"]
    assert main(["registry", "remove", "acme"]) == 1
    registry.remove_registry("other")
    assert main(["registry", "list"]) == 0
    assert "no registries" in capsys.readouterr().out


def test_a_registry_whose_index_lies_is_refused(home):
    bare, work = make_registry(home)
    with open(os.path.join(work, "registry.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "acme", "ontologies": [{"name": "claims", "release": 2, "path": "gone"}]}, f)
    _git(["add", "-A"], work); _git(["commit", "-q", "-m", "broken index"], work); _git(["push", "-q"], work)
    with pytest.raises(ProjectError, match="no directory 'gone'"):
        registry.add_registry(bare)
    plain = os.path.join(home, "plain")
    os.makedirs(plain)
    _git(["init", "--quiet", "-b", "main"], plain)
    with open(os.path.join(plain, "README.md"), "w") as f:
        f.write("not a registry\n")
    _git(["add", "-A"], plain); _git(["commit", "-q", "-m", "x"], plain)
    with pytest.raises(ProjectError, match="not an ontology registry"):
        registry.add_registry(plain)
    with pytest.raises(ProjectError, match="git clone failed"):
        registry.add_registry(os.path.join(home, "missing.git"))


# ---- fetching ----

def test_add_by_name_fetches_with_provenance_and_init_uses_it(home, capsys):
    bare, _work = make_registry(home)
    registry.add_registry(bare)
    assert main(["ontology", "add", "claims"]) == 0
    out = capsys.readouterr().out
    assert "added claims @2" in out and "from registry acme" in out
    dest = ontologies.dir_for("claims")
    assert dest and dest.startswith(os.path.join(home, "ontologies"))
    manifest = ontologies.manifest_for("claims")
    assert manifest["registry"] == "acme" and manifest["source"] == bare and manifest["path"] == "claims"
    assert manifest["commit"] and manifest["fetched_at"] and manifest["release"] == 2
    assert ontologies.origin("claims") == ontologies.FETCHED
    assert not os.path.exists(os.path.join(dest, ".git"))
    assert ontologies.self_check("claims") == []
    assert "Adjuster" in ontologies.load("claims")[0]["classes"], "composed over the built-in oto-core"
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="KB", ontology="claims@2")
        record = json.load(open(os.path.join(root, "project.config.json"), encoding="utf-8"))["ontology"]
        assert record["release"] == 2 and record["origin"] == ontologies.FETCHED and record["commit"] == manifest["commit"]
        assert record["source"] == bare and record["registry"] == "acme"
        from oto.builder import build
        build(Project.standard(root))


def test_init_points_at_the_registry_and_refuses_a_wrong_pin(home):
    bare, _work = make_registry(home)
    registry.add_registry(bare)
    with tempfile.TemporaryDirectory() as root, pytest.raises(ValueError, match="not on this machine.*oto ontology add claims"):
        init(root, slug="kb", name="KB", ontology="claims")
    registry.fetch("claims")
    with tempfile.TemporaryDirectory() as root, pytest.raises(ValueError, match="at release 2 on this machine, not 1: oto ontology add claims@1"):
        init(root, slug="kb", name="KB", ontology="claims@1")


def test_a_pinned_older_version_comes_from_its_tag(home):
    bare, _work = make_registry(home)
    registry.add_registry(bare)
    dest, manifest = registry.fetch("claims", release=1)
    assert manifest["release"] == 1 and manifest["ref"] == "claims/v1"
    assert "Adjuster" not in ontologies.load("claims")[0]["classes"]
    with pytest.raises(ProjectError, match="has no tag claims/v7"):
        registry.fetch("claims", release=7)
    with pytest.raises(ProjectError, match="no registry lists an ontology named 'nope'"):
        registry.fetch("nope")


def test_add_by_url_with_a_path_and_a_registry_is_told_apart(home, capsys):
    bare, _work = make_registry(home)
    assert main(["ontology", "add", bare, "--path", "tiny"]) == 0
    assert "added tiny @1" in capsys.readouterr().out
    manifest = ontologies.manifest_for("tiny")
    assert manifest.get("registry") is None
    assert manifest["source"] == bare and manifest["path"] == "tiny"
    assert main(["ontology", "add", bare]) == 1
    assert "is a registry, not an ontology" in capsys.readouterr().err
    assert main(["ontology", "add", bare, "--path", "nowhere"]) == 1


def test_a_ontology_of_your_own_is_not_overwritten_without_force(home):
    bare, _work = make_registry(home)
    registry.add_registry(bare)
    write_ontology(os.path.join(home, "ontologies"), "claims", {"Mine": {"definition": "mine"}}, {"r": {"domain": "Mine", "range": "Mine", "definition": "r"}},
                   {"nodes": [_node("m.1", "Mine", "M")], "edges": []})
    with pytest.raises(ProjectError, match="an ontology of your own named 'claims'"):
        registry.fetch("claims")
    registry.fetch("claims", force=True)
    assert "Claim" in ontologies.load("claims")[0]["classes"]


def test_update_refetches_when_the_registry_moves_on(home, capsys):
    bare, work = make_registry(home)
    registry.add_registry(bare)
    registry.fetch("claims")
    assert registry.update() == []
    _claims(work, 3, extra_class="Reserve")
    with open(os.path.join(work, "registry.json"), encoding="utf-8") as f:
        index = json.load(f)
    index["ontologies"][0]["release"] = 3
    with open(os.path.join(work, "registry.json"), "w", encoding="utf-8") as f:
        json.dump(index, f)
    _git(["add", "-A"], work); _git(["commit", "-q", "-m", "claims v3"], work); _git(["push", "-q"], work)
    assert main(["ontology", "update"]) == 0
    assert "updated claims @2 -> @3" in capsys.readouterr().out
    assert ontologies.manifest_for("claims")["release"] == 3 and "Reserve" in ontologies.load("claims")[0]["classes"]
    assert main(["ontology", "update", "tiny"]) == 1, "never fetched, nothing to update"


# ---- transport ----

def test_tokens_go_into_https_urls_only(monkeypatch):
    assert gitx.with_token("https://github.com/o/r", "tok") == "https://x-access-token:tok@github.com/o/r"
    assert gitx.with_token("git@github.com:o/r.git", "tok") == "git@github.com:o/r.git"
    assert gitx.with_token("/tmp/r.git", "tok") == "/tmp/r.git"
    assert gitx.with_token("https://github.com/o/r", None) == "https://github.com/o/r"
    from oto import publish
    assert publish._with_token is gitx.with_token, "one implementation for every transport"


def test_a_failed_clone_names_git_and_not_the_token(home, monkeypatch):
    monkeypatch.setenv(registry.TOKEN_ENV, "s3cret-token")
    with pytest.raises(ProjectError) as exc:
        registry.add_registry(os.path.join(home, "does-not-exist.git"))
    assert "git clone failed" in str(exc.value) and "s3cret-token" not in str(exc.value)


# ---- publishing ----

def _empty_registry(root, name="fresh"):
    bare = os.path.join(root, "%s.git" % name)
    _git(["init", "--quiet", "--bare", "-b", "main", bare], root)
    return bare


def _log(bare):
    return subprocess.run(["git", "--git-dir", bare, "log", "--oneline", "main"], capture_output=True, text=True).stdout.splitlines()


def _tags(bare):
    return subprocess.run(["git", "--git-dir", bare, "tag"], capture_output=True, text=True).stdout.split()


def test_publish_from_a_project_creates_the_registry_bumps_versions_and_tags(home, capsys):
    bare = _empty_registry(home)
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="src", name="Source", ontology="organization-process")
        assert main(["ontology", "publish", "--project", root, "--to", bare, "--name", "org-kb",
                     "--summary", "an org", "--note", "first cut", "--registry-name", "fresh"]) == 0
        out = capsys.readouterr().out
        assert "published org-kb @1" in out and "tagged org-kb/v1" in out
        assert _tags(bare) == ["org-kb/v1"] and len(_log(bare)) == 1
        registry.add_registry(bare)
        _reg, entry = registry.find("org-kb")
        assert entry["release"] == 1 and entry["summary"] == "an org" and entry["path"] == "org-kb"
        # a second publish is v2, keeps v1's changelog line, refreshes the cached index
        assert main(["ontology", "publish", "--project", root, "--to", bare, "--name", "org-kb", "--note", "second"]) == 0
        assert "published org-kb @2" in capsys.readouterr().out
        assert sorted(_tags(bare)) == ["org-kb/v1", "org-kb/v2"]
        _reg, entry = registry.find("org-kb")
        assert entry["release"] == 2, "the local cache was refreshed after the publish"
        dest, manifest = registry.fetch("org-kb")
        assert manifest["release"] == 2 and [e["note"] for e in manifest["changelog"]] == ["second", "first cut"]
        assert "registry" in manifest and "source" in manifest, "fetched copies carry provenance"
        dest, manifest = registry.fetch("org-kb", release=1)
        assert manifest["release"] == 1 and manifest["ref"] == "org-kb/v1"


def test_publish_a_ontology_from_this_machine_and_refuse_an_unpublishable_one(home, monkeypatch, capsys):
    bare = _empty_registry(home)
    assert main(["ontology", "publish", "--from", "software-architecture", "--to", bare, "--registry-name", "fresh"]) == 0
    assert "published software-architecture @1" in capsys.readouterr().out
    registry.add_registry(bare)
    _reg, entry = registry.find("software-architecture")
    assert entry["extends"] == ["product"]
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="leak", name="Leak", ontology="organization-process")
        cfg = json.load(open(os.path.join(root, "ontology.config.json"), encoding="utf-8"))
        cfg["classes"]["Unit"] = {"definition": "A unit at AcmeCorp."}
        json.dump(cfg, open(os.path.join(root, "ontology.config.json"), "w", encoding="utf-8"))
        monkeypatch.setenv("OTO_DENY_TERMS", "acmecorp")
        assert main(["ontology", "publish", "--project", root, "--to", bare, "--name", "leaky"]) == 1
        err = capsys.readouterr().err
        assert "not publishable (nothing was pushed)" in err and "deny term (acmecorp)" in err
        assert _tags(bare) == ["software-architecture/v1"], "nothing was pushed"


# ---- diff and the status advisory ----

def test_diff_reports_what_the_upstream_ontology_changed_since(home, capsys):
    bare, work = make_registry(home)
    registry.add_registry(bare)
    registry.fetch("claims", release=1)
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="KB", ontology="claims@1")
        before = open(os.path.join(root, "project.config.json"), "rb").read()
        assert main(["ontology", "diff", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "started from release 1" in out and "holds release 2" in out and "against the release this project started from (tag claims/v1)" in out
        assert "[additive] class added Adjuster" in out and "[additive] question added: Q-Adjuster" in out and "2 additive" in out
        # the registry moves on with a breaking change: Claim is gone, and the project holds one
        write_ontology(work, "claims", {"Case": {"definition": "a case"}}, {"about": {"domain": "Case", "range": "Document", "definition": "about"}},
                       {"nodes": [_node("case.1", "Case", "One")], "edges": []},
                       manifest_body={"release": 3, "summary": "claims v3", "extends": ["oto-core"],
                                      "carries": ["vocabulary", "rationale", "sample", "readme"],
                                      "changelog": [{"release": 3, "at": "2026-09-19", "note": "Claim became Case."}]}, temporal=False)
        index = json.load(open(os.path.join(work, "registry.json"), encoding="utf-8"))
        index["ontologies"][0]["release"] = 3
        json.dump(index, open(os.path.join(work, "registry.json"), "w", encoding="utf-8"))
        _git(["add", "-A"], work); _git(["commit", "-q", "-m", "v3"], work); _git(["push", "-q"], work)
        registry.refresh()
        from oto.cli.status import gather
        s = gather(Project.standard(root))
        assert s["ontology"]["release"] == 1 and s["ontology"]["available"] == 3
        assert main(["status", "--project", root]) == 0
        assert "ontology    claims @1 from acme; @3 available: oto ontology diff" in capsys.readouterr().out
        report = registry.diff_project(Project.standard(root))
        assert report["current"] == 3 and report["basis"] == "tag"
        assert [e["note"] for e in report["changelog"]] == ["Claim became Case."]
        removed = [c for c in report["changes"] if c.kind == "class removed" and c.subject == "Claim"]
        assert removed and removed[0].affected == 1, "the project's own claim.1 would be orphaned"
        assert open(os.path.join(root, "project.config.json"), "rb").read() == before, "diff never writes"


def test_diff_against_a_built_in_ontology_and_a_merge(home, capsys):
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="a", name="A", ontology="software-architecture")
        assert main(["ontology", "diff", "--project", root]) == 0
        assert "holds the same release" in capsys.readouterr().out
        from oto.cli.status import gather
        assert gather(Project.standard(root))["ontology"]["available"] is None
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="b", name="B", ontology="software-architecture,organization-process")
        assert main(["ontology", "diff", "--project", root]) == 1
        assert "no upstream to diff against" in capsys.readouterr().err


# ---- publishing scaffolds the registry ----

def test_publish_scaffolds_the_registry_and_carries_the_domain(home, capsys):
    bare = _empty_registry(home, name="market")
    assert main(["ontology", "publish", "--from", "oto-core", "--to", bare, "--registry-name", "market"]) == 0
    out = capsys.readouterr().out
    assert "the registry was created" in out
    assert main(["ontology", "publish", "--from", "software-architecture", "--to", bare,
                 "--engine", "https://example.com/engine"]) == 0
    work = os.path.join(home, "market-check")
    _git(["clone", "--quiet", bare, work], home)
    index = json.load(open(os.path.join(work, "registry.json"), encoding="utf-8"))
    assert {e["name"]: e.get("domain") for e in index["ontologies"]} == {"oto-core": None, "software-architecture": "software"}
    assert not os.path.exists(os.path.join(work, "software-architecture", ".claude-plugin")), "an ontology carries no plugin"
    assert not os.path.exists(os.path.join(work, "software-architecture", "skills"))
    workflow = open(os.path.join(work, ".github", "workflows", "oto-registry-check.yml"), encoding="utf-8").read()
    assert "oto registry check ." in workflow and "https://example.com/engine" not in workflow, \
        "the workflow is written once, at creation, with the engine known then"
    assert "Cynergis/oto" in workflow
    assert "OTO ontologies" in open(os.path.join(work, "README.md"), encoding="utf-8").read()
    assert main(["registry", "check", work]) == 0
