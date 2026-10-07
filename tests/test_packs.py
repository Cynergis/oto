# -*- coding: utf-8 -*-
"""Packs: the extension a person installs. `new` embeds an ontology with its bases, `check`
validates the whole thing, `refresh` re-embeds, the plugin files come from the manifest, and a
view a pack ships is found by name."""
import json
import os
import shutil
import subprocess
import tempfile

import pytest

from oto.apps import manifest as apps
from oto.cli import main
from oto.model import ontologies, ontology_manifest, packs

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "apps")


@pytest.fixture
def home(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        monkeypatch.setenv(packs.USER_DIR_ENV, os.path.join(root, "packs"))
        monkeypatch.setenv(ontologies.USER_DIR_ENV, os.path.join(root, "ontologies"))
        monkeypatch.setenv("OTO_REGISTRIES", os.path.join(root, "registries.json"))
        yield root


def test_new_embeds_the_ontology_and_its_bases_and_generates_the_plugin_files(home, capsys):
    assert main(["pack", "new", "arch", "--ontology", "software-architecture@9", "--maintainer", "Cynergis"]) == 0
    out = capsys.readouterr().out
    assert "embeds the ontology software-architecture@9 (built-in)" in out and "check clean" in out
    directory = packs.dir_for("arch")
    assert directory == os.path.join(home, "packs", "arch")
    # the ontology and what it extends, under their own names, so the pack composes on its own
    assert sorted(os.listdir(packs.embedded_root(directory))) == ["oto-core", "product", "software-architecture"]
    assert packs.embedded_name(directory) == "software-architecture"
    assert not os.path.exists(os.path.join(packs.embedded_dir(directory), ".claude-plugin"))
    manifest = packs.read(directory)
    assert manifest["release"] == 1 and manifest["domain"] == "software" and manifest["maintainer"] == "Cynergis"
    assert manifest["ontology"]["name"] == "software-architecture" and manifest["ontology"]["release"] == 9
    assert manifest["ontology"]["source"] == "built-in" and manifest["ontology"]["embedded_at"]
    assert manifest["engine"].startswith(">=")
    plugin = json.load(open(os.path.join(directory, ".claude-plugin", "plugin.json"), encoding="utf-8"))
    assert plugin["name"] == "arch" and plugin["version"] == "1.0.0" and plugin["dependencies"] == ["oto"]
    assert plugin["author"]["name"] == "Cynergis" and "software" in plugin["keywords"]
    skill = open(os.path.join(directory, "skills", "start", "SKILL.md"), encoding="utf-8").read()
    assert skill.startswith("---\nname: start\n")
    assert 'oto init --name "<project name>" --pack "${CLAUDE_PLUGIN_ROOT}"' in skill
    assert "software-architecture" in skill and "- **System**" in skill and "## The actions it ships" in skill
    assert "## The guide" in skill, "the embedded guide is quoted"
    assert os.path.exists(os.path.join(directory, "README.md"))
    assert packs.check(directory) == []
    assert packs.summary("arch")["ontology"] == "software-architecture" and packs.summary("arch")["skills"] == ["start"]
    # the same name again is refused without --force
    assert main(["pack", "new", "arch", "--ontology", "software-architecture"]) == 1
    assert "already exists" in capsys.readouterr().err
    assert main(["pack", "new", "arch", "--ontology", "software-architecture", "--force"]) == 0


def test_new_refuses_a_bad_name_an_unknown_ontology_and_a_wrong_pin(home, capsys):
    assert main(["pack", "new", "Bad Name", "--ontology", "auto-claims"]) == 1
    assert "lowercase" in capsys.readouterr().err
    assert main(["pack", "new", "x", "--ontology", "no-such"]) == 1
    assert "unknown ontology" in capsys.readouterr().err
    assert main(["pack", "new", "x", "--ontology", "auto-claims@9"]) == 1
    assert "at release 5 on this machine, not 9" in capsys.readouterr().err
    assert main(["pack", "new", "x"]) == 1
    assert packs.available() == []


def test_a_new_domain_is_noted_never_refused(home, capsys):
    assert main(["pack", "new", "kyc", "--ontology", "auto-claims", "--domain", "banking"]) == 0
    out = capsys.readouterr().out
    assert "note: domain 'banking' is new to this engine" in out and "check clean" in out
    assert packs.read(packs.dir_for("kyc"))["domain"] == "banking"
    assert ontology_manifest.domain_problems("Not A Slug") and ontology_manifest.domain_problems(None) == []
    assert ontology_manifest.domain_note("insurance") is None
    assert main(["pack", "new", "bad", "--ontology", "auto-claims", "--domain", "Not Slug"]) == 1


def test_check_names_what_is_wrong(home, capsys):
    assert main(["pack", "new", "arch", "--ontology", "software-architecture"]) == 0
    directory = packs.dir_for("arch")
    # a view against the embedded vocabulary: a good one passes, a broken one is named
    shutil.copytree(os.path.join(FIXTURES, "globals-site"), os.path.join(directory, "views", "globals-site"))
    assert packs.check(directory) == []
    assert packs.views(directory) == {"globals-site": os.path.join(directory, "views", "globals-site")}
    with open(os.path.join(directory, "views", "globals-site", "app.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "globals-site", "entry": "index.html",
                   "data": [{"file": "d.js", "format": "js-globals", "globals": {"X": {"$nodes": "Ghost"}}}]}, f)
    problems = packs.check(directory)
    assert any(p.startswith("view globals-site: projection names class 'Ghost'") for p in problems)
    os.makedirs(os.path.join(directory, "views", "empty"))
    assert "views/empty has no app.json" in packs.check(directory)
    # a skill without frontmatter, a directory without a skill
    os.makedirs(os.path.join(directory, "skills", "other"))
    assert "skills/other has no SKILL.md" in packs.check(directory)
    with open(os.path.join(directory, "skills", "other", "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("# no frontmatter\n")
    assert "skills/other/SKILL.md must start with frontmatter naming it `other`" in packs.check(directory)
    # the plugin manifest out of step with the release
    manifest = packs.read(directory); manifest["release"] = 4; packs.write(directory, manifest)
    assert any("plugin.json version '1.0.0' is not release 4" in p for p in packs.check(directory))
    # the manifest and the embedded copy disagree
    manifest["ontology"]["release"] = 10; packs.write(directory, manifest)
    assert any("says ontology release 10 but ontology/ is at release 9" in p for p in packs.check(directory))
    assert main(["pack", "check", directory]) == 1
    out = capsys.readouterr().out
    assert "problem(s):" in out and "view globals-site" in out
    # not a pack at all
    assert main(["pack", "check", home]) == 1
    assert "is not a pack" in capsys.readouterr().err


def test_check_runs_from_inside_the_pack_and_the_deny_terms_apply(home, monkeypatch, capsys):
    assert main(["pack", "new", "arch", "--ontology", "software-architecture"]) == 0
    directory = packs.dir_for("arch")
    cwd = os.getcwd()
    try:
        os.chdir(directory)
        assert main(["pack", "check"]) == 0
        assert "check clean" in capsys.readouterr().out
    finally:
        os.chdir(cwd)
    with open(os.path.join(directory, "README.md"), "a", encoding="utf-8") as f:
        f.write("\nMade for Globex.\n")
    monkeypatch.setenv("OTO_DENY_TERMS", "globex")
    problems = packs.check(directory)
    assert any(p.startswith("README.md names a deny term (globex)") for p in problems)


def test_refresh_re_embeds_a_newer_ontology_and_regenerates(home, capsys):
    # an ontology of the user's own, at release 1, wrapped in a pack
    src = os.path.join(home, "ontologies", "mine")
    shutil.copytree(ontologies.dir_for("auto-claims"), src)
    m = ontologies.manifest_dir(src); m["name"] = "mine"; m["release"] = 1; m["changelog"] = []
    ontology_manifest.write(src, m)
    assert main(["pack", "new", "claims", "--ontology", "mine"]) == 0
    directory = packs.dir_for("claims")
    assert packs.read(directory)["ontology"]["release"] == 1 and packs.read(directory)["ontology"]["source"] == "user"
    assert packs.notes(directory) == []
    # the ontology moves on, on this machine
    m["release"] = 2; m["summary"] = "Claims, second release."
    ontology_manifest.write(src, m)
    assert any("release 2 upstream" in n and "embeds release 1" in n for n in packs.notes(directory))
    assert any("oto pack refresh" in p for p in packs.check(directory)) is False, "advisory, not a problem"
    skill_before = open(os.path.join(directory, "skills", "start", "SKILL.md"), encoding="utf-8").read()
    assert main(["pack", "refresh", directory]) == 0
    assert "at release 2 (was 1)" in capsys.readouterr().out
    assert packs.read(directory)["ontology"]["release"] == 2
    assert ontologies.manifest_dir(packs.embedded_dir(directory))["release"] == 2
    assert "(release 2)" in open(os.path.join(directory, "skills", "start", "SKILL.md"), encoding="utf-8").read()
    assert skill_before != open(os.path.join(directory, "skills", "start", "SKILL.md"), encoding="utf-8").read()
    assert packs.check(directory) == [] and packs.notes(directory) == []


def test_a_view_a_pack_ships_is_found_by_name(home):
    assert main(["pack", "new", "arch", "--ontology", "software-architecture"]) == 0
    directory = packs.dir_for("arch")
    shutil.copytree(os.path.join(FIXTURES, "globals-site"), os.path.join(directory, "views", "globals-site"))
    assert apps.resolve("globals-site") == os.path.join(directory, "views", "globals-site")
    assert ("globals-site", os.path.join(directory, "views", "globals-site"), "pack arch") in apps.available()
    assert apps.resolve("explorer").endswith(os.path.join("ui", "explorer")), "the built-ins are still found"


def test_an_ontology_carries_no_views_plugin_or_skills_any_more(home):
    base = os.path.join(home, "ontologies", "arch-with-app")
    shutil.copytree(ontologies.dir_for("software-architecture"), base)
    m = ontologies.manifest_dir(base); m["name"] = "arch-with-app"
    ontology_manifest.write(base, m)
    shutil.copytree(os.path.join(FIXTURES, "globals-site"), os.path.join(base, "views", "globals-site"))
    os.makedirs(os.path.join(base, ".claude-plugin"))
    assert ontologies.self_check("arch-with-app") == [], "extra directories are ignored, not validated"
    assert "views" not in ontologies.composed("arch-with-app")
    assert "views" not in ontology_manifest.CARRIES and "plugin" not in ontology_manifest.CARRIES
    with pytest.raises(SystemExit):
        main(["ontology", "plugin", "arch-with-app"])


def test_the_shipped_ontologies_declare_a_domain_and_the_listing_groups_by_it(capsys):
    for name, domain in (("auto-claims", "insurance"), ("organization-process", "organization"),
                         ("professional-services", "professional-services"), ("software-architecture", "software")):
        assert ontologies.summary(name)["domain"] == domain and domain in ontology_manifest.DOMAINS
    assert ontologies.summary("oto-core")["domain"] is None
    assert main(["ontology", "list"]) == 0
    out = capsys.readouterr().out
    assert out.index("insurance:") < out.index("auto-claims") < out.index("software:") < out.index("software-architecture")
    assert out.index("no domain:") > out.index("software:") and "oto-core" in out.split("no domain:")[1]
    assert main(["ontology", "show", "auto-claims"]) == 0
    assert "domain:   insurance" in capsys.readouterr().out


# ---- the registry side: publish, add, update, list, show ----

from test_registry import _empty_registry, _git  # noqa: E402


def test_publish_a_pack_creates_the_registry_with_the_engine_first_in_the_marketplace(home, capsys):
    from oto.model import registry
    bare = _empty_registry(home, name="market")
    assert main(["pack", "new", "arch", "--ontology", "software-architecture", "--maintainer", "Cynergis"]) == 0
    assert main(["pack", "publish", "--from", "arch", "--to", bare, "--registry-name", "market", "--note", "first",
                 "--engine", "https://github.com/Cynergis/oto"]) == 0
    out = capsys.readouterr().out
    assert "published pack arch @1" in out and "tagged arch--v1.0.0" in out and "the registry was created" in out
    assert "marketplace lists the engine plugin and 1 pack(s): arch" in out
    work = os.path.join(home, "market-check")
    _git(["clone", "--quiet", bare, work], home)
    index = json.load(open(os.path.join(work, "registry.json"), encoding="utf-8"))
    assert index["ontologies"] == [] and index["engine"] == "https://github.com/Cynergis/oto"
    assert index["packs"] == [{"name": "arch", "release": 1, "summary": index["packs"][0]["summary"], "path": "packs/arch",
                               "ontology": {"name": "software-architecture", "release": 9}, "domain": "software"}]
    published = packs.read(os.path.join(work, "packs", "arch"))
    assert published["release"] == 1 and published["changelog"][0]["note"] == "first" and "fetched_at" not in published
    plugin = json.load(open(os.path.join(work, "packs", "arch", ".claude-plugin", "plugin.json"), encoding="utf-8"))
    assert plugin["version"] == "1.0.0" and plugin["dependencies"] == ["oto"]
    market = json.load(open(os.path.join(work, ".claude-plugin", "marketplace.json"), encoding="utf-8"))
    assert [p["name"] for p in market["plugins"]] == ["oto", "arch"]
    assert market["plugins"][0]["source"] == {"source": "github", "repo": "Cynergis/oto"}
    assert market["plugins"][1] == {"name": "arch", "source": "./packs/arch", "description": published["summary"],
                                    "version": "1.0.0", "category": "software"}
    workflow = open(os.path.join(work, ".github", "workflows", "oto-registry-check.yml"), encoding="utf-8").read()
    assert "packs.check(entry" in workflow and "oto registry check ." in workflow
    assert "ontologies and packs" in open(os.path.join(work, "README.md"), encoding="utf-8").read()
    assert main(["registry", "check", work]) == 0
    assert "0 ontologies, 1 pack, index matches" in capsys.readouterr().out
    assert "arch--v1.0.0" in subprocess.run(["git", "tag"], cwd=work, capture_output=True, text=True).stdout
    # a second publish bumps the release, the plugin version follows, the changelog accumulates
    assert main(["pack", "publish", "--from", "arch", "--to", bare, "--note", "again"]) == 0
    _git(["pull", "-q"], work)
    published = packs.read(os.path.join(work, "packs", "arch"))
    assert published["release"] == 2 and [e["note"] for e in published["changelog"]] == ["again", "first"]
    plugin = json.load(open(os.path.join(work, "packs", "arch", ".claude-plugin", "plugin.json"), encoding="utf-8"))
    assert plugin["version"] == "2.0.0"
    assert json.load(open(os.path.join(work, ".claude-plugin", "marketplace.json"), encoding="utf-8"))["plugins"][1]["version"] == "2.0.0"
    # an ontology published into the same registry keeps the packs list and the marketplace
    assert main(["ontology", "publish", "--from", "oto-core", "--to", bare]) == 0
    _git(["pull", "-q"], work)
    index = json.load(open(os.path.join(work, "registry.json"), encoding="utf-8"))
    assert [e["name"] for e in index["ontologies"]] == ["oto-core"] and [e["name"] for e in index["packs"]] == ["arch"]
    assert [p["name"] for p in json.load(open(os.path.join(work, ".claude-plugin", "marketplace.json"), encoding="utf-8"))["plugins"]] == ["oto", "arch"]
    assert main(["registry", "check", work]) == 0


def test_publish_refuses_an_unpublishable_pack_and_pushes_nothing(home, monkeypatch, capsys):
    bare = _empty_registry(home, name="market")
    assert main(["pack", "new", "arch", "--ontology", "software-architecture"]) == 0
    with open(os.path.join(packs.dir_for("arch"), "README.md"), "a", encoding="utf-8") as f:
        f.write("\nFor Globex.\n")
    monkeypatch.setenv("OTO_DENY_TERMS", "globex")
    assert main(["pack", "publish", "--from", "arch", "--to", bare, "--registry-name", "market"]) == 1
    assert "not publishable (nothing was pushed)" in capsys.readouterr().err
    assert main(["pack", "publish", "--from", "no-such", "--to", bare]) == 1
    assert main(["pack", "publish", "--from", "arch"]) == 1


def test_add_update_list_and_show_from_a_registry(home, capsys):
    from oto.model import registry
    bare = _empty_registry(home, name="market")
    assert main(["pack", "new", "arch", "--ontology", "software-architecture", "--domain", "software"]) == 0
    assert main(["pack", "publish", "--from", "arch", "--to", bare, "--registry-name", "market"]) == 0
    shutil.rmtree(packs.dir_for("arch"))
    assert packs.available() == []
    assert main(["registry", "add", bare]) == 0
    out = capsys.readouterr().out
    assert "0 ontologies, 1 pack" in out and "pack      arch" in out
    # listed, not here
    assert main(["pack", "list"]) == 0
    out = capsys.readouterr().out
    assert "no packs on this machine" in out and "in a registry, not on this machine" in out and "arch" in out
    # fetched with provenance
    assert main(["pack", "add", "arch"]) == 0
    out = capsys.readouterr().out
    assert "added pack arch @1" in out and "embeds the ontology software-architecture@9" in out and "registry market" in out
    manifest = packs.read(packs.dir_for("arch"))
    assert manifest["registry"] == "market" and manifest["source"] == bare and manifest["path"] == "packs/arch" and manifest["commit"]
    assert packs.origin("arch") == packs.FETCHED and packs.check(packs.dir_for("arch")) == []
    assert main(["pack", "list"]) == 0
    out = capsys.readouterr().out
    assert "software:" in out and "arch" in out and "(fetched)" in out and "in a registry, not on this machine" not in out
    assert main(["pack", "show", "arch"]) == 0
    out = capsys.readouterr().out
    assert "arch @1  (fetched)" in out and "ontology: software-architecture@9" in out and "skills:   start" in out \
        and "check: clean" in out and "fetched:  from market" in out
    # a pinned older release comes from its tag; a wrong pin is refused
    assert main(["pack", "publish", "--from", "arch", "--to", bare, "--note", "second"]) == 0
    assert main(["pack", "add", "arch@1", "--force"]) == 0
    assert packs.read(packs.dir_for("arch"))["release"] == 1
    with pytest.raises(registry.ProjectError, match="has no tag arch--v7.0.0"):
        registry.fetch("arch", release=7, kind="pack")
    # update re-fetches the newer release
    assert main(["pack", "update"]) == 0
    assert "updated pack arch @1 -> @2" in capsys.readouterr().out
    assert packs.read(packs.dir_for("arch"))["release"] == 2
    assert main(["pack", "update"]) == 0
    assert "every fetched pack is at its registry's current release" in capsys.readouterr().out
    # add by url with a path, and a registry is told apart from a pack
    assert main(["pack", "add", bare, "--path", "packs/arch", "--force"]) == 0
    assert main(["pack", "add", bare]) == 1
    assert "is a registry, not a pack" in capsys.readouterr().err
    assert main(["pack", "add", "no-such"]) == 1
    assert main(["pack", "show", "no-such"]) == 1


# ---- starting a project from a pack ----

def test_init_from_a_pack_installs_its_ontology_and_views_and_records_the_pack(home, capsys):
    from oto.builder import build
    from oto.project import Project
    from oto.scaffold import init
    assert main(["pack", "new", "arch", "--ontology", "software-architecture"]) == 0
    directory = packs.dir_for("arch")
    shutil.copytree(os.path.join(FIXTURES, "globals-site"), os.path.join(directory, "views", "globals-site"))
    with tempfile.TemporaryDirectory() as root:
        assert main(["init", "--name", "KB", "--slug", "kb", "--project", root, "--pack", "arch"]) == 0
        out = capsys.readouterr().out
        assert "pack: arch @1" in out and "ontology: software-architecture @9 (extends oto-core, product)" in out
        assert "wrote: views/globals-site" in out and "wrote: GUIDE.md" in out and "actions/action.check-repository.json" in out
        config = json.load(open(os.path.join(root, "project.config.json"), encoding="utf-8"))
        record = config["ontology"]
        assert record["name"] == "software-architecture" and record["release"] == 9 and record["origin"] == "built-in"
        assert record["pack"] == {"name": "arch", "release": 1, "registry": None, "source": None}
        assert record["extends"] == ["oto-core", "product"]
        assert os.path.exists(os.path.join(root, "views", "globals-site", "app.json"))
        assert apps.resolve("globals-site", root) == os.path.join(root, "views", "globals-site")
        build(Project.standard(root))
        assert main(["status", "--project", root]) == 0
        assert "ontology    software-architecture @9 (built-in) via pack arch @1" in capsys.readouterr().out
        assert main(["ontology", "diff", "--project", root]) == 0
        assert "the engine holds the same release" in capsys.readouterr().out
        assert main(["build", "--project", root, "--target", "site", "--view", "globals-site"]) == 0
    # the same, by directory, as the starter skill does with ${CLAUDE_PLUGIN_ROOT}
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb2", name="KB2", pack=directory)
        assert json.load(open(os.path.join(root, "project.config.json"), encoding="utf-8"))["ontology"]["pack"]["name"] == "arch"
    # refusals: both flags, an unknown pack, a pack that fails its check
    with tempfile.TemporaryDirectory() as root:
        with pytest.raises(ValueError, match="not both"):
            init(root, slug="x", name="X", pack="arch", ontology="auto-claims")
        with pytest.raises(ValueError, match="unknown pack 'nope'"):
            init(root, slug="x", name="X", pack="nope")
        os.makedirs(os.path.join(directory, "skills", "broken"))
        with pytest.raises(ValueError, match="not usable"):
            init(root, slug="x", name="X", pack="arch")


def test_init_from_a_fetched_pack_keeps_the_registry_provenance(home, capsys):
    from oto.scaffold import init
    bare = _empty_registry(home, name="market")
    assert main(["pack", "new", "arch", "--ontology", "software-architecture"]) == 0
    assert main(["pack", "publish", "--from", "arch", "--to", bare, "--registry-name", "market"]) == 0
    shutil.rmtree(packs.dir_for("arch"))
    assert main(["registry", "add", bare]) == 0 and main(["pack", "add", "arch"]) == 0
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="KB", pack="arch")
        record = json.load(open(os.path.join(root, "project.config.json"), encoding="utf-8"))["ontology"]
        assert record["origin"] == "built-in", "the pack embedded the engine's copy; that is what the project records"
        assert record["pack"]["registry"] == "market" and record["pack"]["source"] == bare


def test_a_pack_installed_by_claude_code_sits_under_a_version_directory(home, tmp_path, capsys):
    """Claude Code installs a plugin at <marketplace>/<plugin>/<version>/, and the pack's start
    skill passes that directory as ${CLAUDE_PLUGIN_ROOT}. The name check reads the parent then."""
    assert main(["pack", "new", "arch", "--ontology", "software-architecture"]) == 0
    installed = os.path.join(str(tmp_path), "cache", "cynergis", "arch", "1.0.0")
    shutil.copytree(packs.dir_for("arch"), installed)
    assert packs.check(installed) == []
    assert main(["init", "--name", "Try", "--pack", installed, "--project", os.path.join(str(tmp_path), "try")]) == 0
    assert "pack: arch @1" in capsys.readouterr().out
    # a version directory whose parent is not the pack is still wrong, and so is any other name
    elsewhere = os.path.join(str(tmp_path), "cache", "cynergis", "other", "1.0.0")
    shutil.copytree(packs.dir_for("arch"), elsewhere)
    assert any("names 'arch' but the directory is '1.0.0'" in p for p in packs.check(elsewhere))
    renamed = os.path.join(str(tmp_path), "renamed")
    shutil.copytree(packs.dir_for("arch"), renamed)
    assert any("names 'arch' but the directory is 'renamed'" in p for p in packs.check(renamed))
