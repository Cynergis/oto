"""An ontology embedded in an installed pack resolves by name: a machine that installed the pack
needs nothing else to start a project from it, or to name it beside another pack."""
import json
import os
import shutil

import pytest

from oto.model import ontologies
from oto.project import Project
from oto.scaffold import init


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A machine with no ontologies of its own, an empty packs directory and an empty Claude Code."""
    monkeypatch.setenv(ontologies.USER_DIR_ENV, str(tmp_path / "ontologies"))
    monkeypatch.setenv("OTO_PACKS", str(tmp_path / "packs"))
    monkeypatch.setenv(ontologies.CLAUDE_CONFIG_ENV, str(tmp_path / "claude"))
    return tmp_path


def _pack(directory, embeds, carries):
    """A pack at `directory` embedding `embeds`; `carries` maps each ontology it holds to
    (the shipped ontology it copies, its release)."""
    for name, (copy_of, release) in carries.items():
        target = os.path.join(directory, "ontology", name)
        shutil.copytree(ontologies.dir_for(copy_of), target)
        path = os.path.join(target, "manifest.json")
        manifest = json.load(open(path, encoding="utf-8"))
        manifest.update(name=name, release=release,
                        changelog=[e for e in manifest.get("changelog") or [] if e.get("release", 0) <= release])
        json.dump(manifest, open(path, "w", encoding="utf-8"), indent=1)
    json.dump({"name": os.path.basename(directory), "release": 1, "summary": "A test pack.",
               "ontology": {"name": embeds, "release": carries[embeds][1], "registry": None,
                            "source": "https://example.org/claims-ontology", "commit": "abc1234"}},
              open(os.path.join(directory, "manifest.json"), "w", encoding="utf-8"))
    return directory


def _installed_by_claude(machine, *directories):
    """Claude Code's list of installed plugins, naming each directory as one plugin's install."""
    os.makedirs(machine / "claude" / "plugins", exist_ok=True)
    plugins = {"p%d@market" % i: [{"scope": "user", "installPath": str(d), "version": "1.0.0"}]
               for i, d in enumerate(directories)}
    (machine / "claude" / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": plugins}))


def test_an_ontology_in_a_pack_under_the_packs_directory_resolves_by_name(machine):
    _pack(str(machine / "packs" / "claims"), "pack-claims", {"pack-claims": ("auto-claims", 3), "oto-core": ("oto-core", 5)})
    path = ontologies.dir_for("pack-claims")
    assert path == str(machine / "packs" / "claims" / "ontology" / "pack-claims")
    assert ontologies.origin("pack-claims") == ontologies.PACK
    assert "pack-claims" in ontologies.available()
    assert ontologies.self_check("pack-claims") == []


def test_an_ontology_in_a_plugin_claude_code_installed_resolves_by_name(machine):
    plugin = _pack(str(machine / "cache" / "claims" / "1.0.0"), "pack-claims",
                   {"pack-claims": ("auto-claims", 3), "oto-core": ("oto-core", 5)})
    assert ontologies.dir_for("pack-claims") is None
    _installed_by_claude(machine, plugin)
    assert ontologies.dir_for("pack-claims") == os.path.join(plugin, "ontology", "pack-claims")
    assert ontologies.origin("pack-claims") == ontologies.PACK


def test_a_plugin_that_is_not_a_pack_and_a_broken_plugin_list_are_ignored(machine):
    plain = machine / "cache" / "tool" / "1.0.0"
    os.makedirs(plain / "skills")
    _installed_by_claude(machine, str(plain))
    assert ontologies.dir_for("tool") is None
    (machine / "claude" / "plugins" / "installed_plugins.json").write_text("{not json")
    assert ontologies.dir_for("anything") is None
    assert "auto-claims" in ontologies.available()


def test_a_pack_copy_never_shadows_a_shipped_ontology_or_yours(machine):
    _pack(str(machine / "packs" / "claims"), "auto-claims", {"auto-claims": ("auto-claims", 99), "oto-core": ("oto-core", 99)})
    assert ontologies.origin("auto-claims") == ontologies.BUILTIN
    assert ontologies.manifest_for("oto-core")["release"] == 6
    assert ontologies.available().count("auto-claims") == 1


def test_when_two_packs_carry_an_ontology_the_higher_release_wins(machine):
    _pack(str(machine / "packs" / "old"), "pack-claims", {"pack-claims": ("auto-claims", 2), "oto-core": ("oto-core", 5)})
    newer = _pack(str(machine / "cache" / "new" / "1.0.0"), "pack-claims",
                  {"pack-claims": ("auto-claims", 4), "oto-core": ("oto-core", 5)})
    _pack(str(machine / "packs" / "older"), "pack-claims", {"pack-claims": ("auto-claims", 1), "oto-core": ("oto-core", 5)})
    _installed_by_claude(machine, newer)
    assert ontologies.manifest_for("pack-claims")["release"] == 4
    assert ontologies.dir_for("pack-claims").startswith(newer)


def test_an_ontology_found_in_a_pack_composes_with_the_bases_that_pack_carries(machine):
    """The pack was checked with its own copies; a name found there must not pick another's."""
    directory = _pack(str(machine / "packs" / "claims"), "pack-claims",
                      {"pack-claims": ("auto-claims", 3), "oto-core": ("oto-core", 5)})
    core = os.path.join(directory, "ontology", "oto-core", "ontology.config.json")
    config = json.load(open(core, encoding="utf-8"))
    config["classes"]["PackOnlyThing"] = {"definition": "Only in the pack's copy of oto-core."}
    json.dump(config, open(core, "w", encoding="utf-8"))
    assert "PackOnlyThing" in ontologies.composed("pack-claims")["config"]["classes"]
    assert "PackOnlyThing" not in ontologies.composed("auto-claims")["config"]["classes"]
    assert ontologies.dir_for("oto-core") != os.path.dirname(core)


def test_init_starts_a_project_from_a_pack_ontology_and_remembers_the_pack(machine):
    _pack(str(machine / "packs" / "claims"), "pack-claims", {"pack-claims": ("auto-claims", 3), "oto-core": ("oto-core", 5)})
    root = str(machine / "project")
    init(root, slug="c", name="C", ontology="pack-claims")
    record = Project.standard(root).config()["ontology"]
    assert record["name"] == "pack-claims" and record["release"] == 3
    assert record["source"] == "https://example.org/claims-ontology" and record["commit"] == "abc1234"
    assert record["pack"]["name"] == "claims"


def test_init_merges_a_pack_ontology_named_beside_another(machine):
    _pack(str(machine / "packs" / "claims"), "pack-claims", {"pack-claims": ("auto-claims", 3), "oto-core": ("oto-core", 5)})
    root = str(machine / "project")
    init(root, slug="m", name="M", ontology="pack-claims,organization-process")
    record = Project.standard(root).config()["ontology"]
    assert [part["name"] for part in record["parts"]] == ["pack-claims", "organization-process"]
    assert record["parts"][0]["pack"]["name"] == "claims"
    assert record["parts"][1]["origin"] == ontologies.BUILTIN
