"""The project lock (oto.lock.json): the engine, the plugins Claude Code has for a project and the
ontologies it started from, recorded at init; a machine checked against it; a script that rebuilds it."""
import json
import os
import subprocess

import pytest

from oto.cli import main
from oto.model import lock as lockfile, ontologies
from oto.project import Project
from oto.scaffold import init


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def claude(tmp_path, monkeypatch):
    """A Claude Code profile: a marketplace cloned from git, the engine plugin, a pack, a plugin
    that depends on the engine, a plugin listed from its own repository, and an unrelated one."""
    config = tmp_path / "claude"
    monkeypatch.setenv(ontologies.CLAUDE_CONFIG_ENV, str(config))
    monkeypatch.setenv(ontologies.USER_DIR_ENV, str(tmp_path / "ontologies"))
    monkeypatch.setenv("OTO_PACKS", str(tmp_path / "packs"))
    monkeypatch.delenv("OTO_SOURCE", raising=False)
    market = tmp_path / "market"
    (market / ".claude-plugin").mkdir(parents=True)
    (market / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"name": "acme", "plugins": [
        {"name": "oto", "source": {"source": "github", "repo": "Cynergis/oto"}},
        {"name": "tool", "source": {"source": "github", "repo": "Acme/tool"}, "version": "0.4.0"},
        {"name": "claims", "source": "./packs/claims", "version": "2.0.0"}]}))
    _git(["init", "-q", "-b", "main"], market)
    _git(["-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"], market)
    _git(["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "first"], market)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=market, capture_output=True, text=True).stdout.strip()
    (config / "plugins").mkdir(parents=True)
    (config / "plugins" / "known_marketplaces.json").write_text(json.dumps({
        "acme": {"source": {"source": "github", "repo": "Acme/registry"}, "installLocation": str(market)},
        "other": {"source": {"source": "github", "repo": "Other/market"}, "installLocation": str(tmp_path / "nowhere")}}))

    def plugin(name, version, deps=(), pack=False):
        where = tmp_path / "cache" / name / version
        (where / ".claude-plugin").mkdir(parents=True)
        (where / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": name, "version": version, "dependencies": list(deps)}))
        if pack:
            (where / "ontology").mkdir()
            (where / "manifest.json").write_text("{}")
        return {"scope": "user", "installPath": str(where), "version": version, "gitCommitSha": "c0ffee%s" % version.replace(".", "")}

    installs = {"oto@acme": [plugin("oto", "0.11.10")], "claims@acme": [plugin("claims", "2.0.0", pack=True)],
                "tool@acme": [plugin("tool", "0.4.0", deps=["oto"])], "figma@other": [plugin("figma", "1.0.0")]}
    (config / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": installs}))
    return {"config": config, "commit": commit, "installs": installs, "tmp": tmp_path}


def _install(claude, key, version):
    path = claude["config"] / "plugins" / "installed_plugins.json"
    data = json.loads(path.read_text())
    if version is None:
        data["plugins"].pop(key, None)
    else:
        data["plugins"][key] = [dict(data["plugins"].get(key, [{"scope": "user"}])[0], version=version, gitCommitSha="feed%s" % version)]
    path.write_text(json.dumps(data))


def _project(claude, **kw):
    root = str(claude["tmp"] / "project")
    init(root, slug="p", name="P", ontology="auto-claims", **kw)
    return Project.standard(root)


def test_init_locks_the_engine_the_oto_plugins_and_the_ontology(claude):
    project = _project(claude)
    locked = lockfile.read(project)
    assert locked["engine"]["version"] and locked["engine"]["tag"] == "v%s" % locked["engine"]["version"]
    assert [(p["id"], p["version"]) for p in locked["plugins"]] == [("claims@acme", "2.0.0"), ("oto@acme", "0.11.10"), ("tool@acme", "0.4.0")]
    assert locked["declared_by"] == "the OTO plugins installed for it", "figma is no OTO plugin and is left out"
    assert locked["marketplaces"] == [{"name": "acme", "source": {"source": "github", "repo": "Acme/registry"}, "commit": claude["commit"]}]
    assert locked["ontologies"]["name"] == "auto-claims" and locked["ontologies"]["release"]
    listed = {p["name"]: p["listed_from"] for p in locked["plugins"]}
    assert listed == {"claims": "marketplace", "oto": "Cynergis/oto", "tool": "Acme/tool"}
    assert lockfile.drift(project) == []


def test_the_project_declares_its_plugins_in_its_claude_settings(claude):
    project = _project(claude)
    os.makedirs(os.path.join(project.data, ".claude"))
    with open(os.path.join(project.data, ".claude", "settings.json"), "w") as f:
        json.dump({"enabledPlugins": {"claims@acme": True, "figma@other": True, "tool@acme": False}}, f)
    _path, locked = lockfile.write(project)
    assert locked["declared_by"] == ".claude/settings.json"
    assert [p["id"] for p in locked["plugins"]] == ["claims@acme", "figma@other"]


def test_a_project_scope_install_wins_over_the_users(claude):
    project = _project(claude)
    path = claude["config"] / "plugins" / "installed_plugins.json"
    data = json.loads(path.read_text())
    data["plugins"]["claims@acme"].append(dict(data["plugins"]["claims@acme"][0], scope="project", projectPath=project.data, version="3.0.0"))
    path.write_text(json.dumps(data))
    assert {p["id"]: p["version"] for p in lockfile.make(project)["plugins"]}["claims@acme"] == "3.0.0"


def test_drift_names_every_difference_and_status_and_check_report_it(claude, capsys):
    project = _project(claude)
    _install(claude, "claims@acme", "3.0.0")
    _install(claude, "tool@acme", None)
    _install(claude, "orders@acme", "1.0.0")
    os.makedirs(claude["tmp"] / "cache" / "orders", exist_ok=True)
    data = json.loads((claude["config"] / "plugins" / "installed_plugins.json").read_text())
    data["plugins"]["orders@acme"][0]["installPath"] = data["plugins"]["claims@acme"][0]["installPath"]   # a pack too
    (claude["config"] / "plugins" / "installed_plugins.json").write_text(json.dumps(data))
    locked = lockfile.read(project)
    locked["engine"]["version"] = "0.0.1"
    differences = lockfile.drift(project, locked)
    assert differences[0].startswith("the engine is ") and differences[0].endswith("locked at 0.0.1")
    assert "claims@acme is 3.0.0 here, locked at 2.0.0" in differences
    assert "tool@acme is locked at 0.4.0 and not installed here" in differences
    assert "orders@acme 1.0.0 is used here and not in the lock" in differences
    capsys.readouterr()
    assert main(["lock", "--check", "--project", project.data]) == 1
    out = capsys.readouterr().out
    assert "3 difference(s) from oto.lock.json" in out and "claims@acme is 3.0.0 here" in out
    assert main(["status", "--project", project.data]) == 0
    assert "tools       oto.lock.json" in capsys.readouterr().out
    assert main(["lock", "--project", project.data]) == 0
    assert "wrote" in capsys.readouterr().out
    assert main(["lock", "--check", "--project", project.data]) == 0
    assert "matches this machine" in capsys.readouterr().out


def test_the_restore_script_rebuilds_the_locked_tools(claude, capsys):
    project = _project(claude)
    capsys.readouterr()
    assert main(["lock", "--script", "--project", project.data]) == 0
    script = capsys.readouterr().out
    where = '"$DIR/acme-%s"' % claude["commit"][:12]
    assert "git clone --quiet https://github.com/Acme/registry.git %s" % where in script
    assert "git -C %s checkout --quiet %s" % (where, claude["commit"]) in script
    assert "claude plugin marketplace add %s" % where in script
    for key in ("claims@acme", "oto@acme", "tool@acme"):
        assert "claude plugin install %s" % key in script
    assert 'uv tool install --force "oto-kg[intake] @ git+' in script and "OTO_SOURCE" in script
    notes = lockfile.warnings(lockfile.read(project))
    assert any("tool@acme comes from Acme/tool's default branch" in n for n in notes)
    assert not any("claims@acme" in n for n in notes), "a pack inside the marketplace is pinned with it"


def test_a_directory_marketplace_is_named_as_not_reproducible(claude):
    known = claude["config"] / "plugins" / "known_marketplaces.json"
    data = json.loads(known.read_text())
    data["acme"]["source"] = {"source": "directory", "path": "/somewhere/market"}
    known.write_text(json.dumps(data))
    project = _project(claude)
    locked = lockfile.read(project)
    assert any("a directory on this machine" in n for n in lockfile.warnings(locked))
    assert "# marketplace acme cannot be rebuilt here: not a git source" in lockfile.restore_script(locked)


def test_no_lock_is_said_plainly(claude, capsys):
    project = _project(claude)
    os.remove(lockfile.path(project))
    assert lockfile.drift(project) == ["no oto.lock.json: oto lock writes it"]
    assert main(["lock", "--script", "--project", project.data]) == 1
    assert main(["status", "--project", project.data]) == 0
    assert "tools       not locked" in capsys.readouterr().out


# ---- the project declares the plugins it uses ----

def _installed_pack(claude, key, directory):
    path = claude["config"] / "plugins" / "installed_plugins.json"
    data = json.loads(path.read_text())
    data["plugins"][key] = [{"scope": "user", "installPath": str(directory), "version": "3.0.0", "gitCommitSha": "abc"}]
    path.write_text(json.dumps(data))


def _settings(project):
    with open(os.path.join(project.data, ".claude", "settings.json"), encoding="utf-8") as f:
        return json.load(f)


def test_init_from_an_installed_pack_declares_it_and_the_engine_plugin(claude, capsys):
    assert main(["pack", "new", "arch", "--ontology", "software-architecture", "--to", str(claude["tmp"] / "cache" / "arch")]) == 0
    _installed_pack(claude, "arch@acme", claude["tmp"] / "cache" / "arch" / "arch")
    root = str(claude["tmp"] / "project")
    init(root, slug="p", name="P", pack=str(claude["tmp"] / "cache" / "arch" / "arch"), empty=True)
    assert "wrote: .claude/settings.json (the plugins this project uses: arch@acme, oto@acme)" in capsys.readouterr().out
    project = Project.standard(root)
    settings = _settings(project)
    assert settings == {"enabledPlugins": {"arch@acme": True, "oto@acme": True},
                        "extraKnownMarketplaces": {"acme": {"source": {"source": "github", "repo": "Acme/registry"}}}}
    locked = lockfile.read(project)
    assert locked["declared_by"] == ".claude/settings.json"
    assert [p["id"] for p in locked["plugins"]] == ["arch@acme", "oto@acme"], "only what the project uses, not every OTO plugin here"


def test_an_ontology_an_installed_pack_brought_declares_that_pack(claude):
    from test_pack_ontologies import _pack
    directory = _pack(str(claude["tmp"] / "cache" / "claimsplus"), "pack-claims",
                      {"pack-claims": ("auto-claims", 3), "oto-core": ("oto-core", 5)})
    _installed_pack(claude, "claimsplus@acme", directory)
    root = str(claude["tmp"] / "project")
    init(root, slug="p", name="P", ontology="pack-claims,organization-process", empty=True)
    assert _settings(Project.standard(root))["enabledPlugins"] == {"claimsplus@acme": True, "oto@acme": True}


def test_lock_use_declares_a_tool_and_keeps_the_rest_of_the_settings(claude, capsys):
    project = _project(claude)
    os.makedirs(os.path.join(project.data, ".claude"))
    with open(os.path.join(project.data, ".claude", "settings.json"), "w") as f:
        json.dump({"permissions": {"allow": ["Bash(oto:*)"]}, "enabledPlugins": {"claims@acme": True}}, f)
    capsys.readouterr()
    assert main(["lock", "--use", "tool@acme", "--project", project.data]) == 0
    out = capsys.readouterr().out
    assert "declared in .claude/settings.json: tool@acme, oto@acme" in out
    settings = _settings(project)
    assert settings["permissions"] == {"allow": ["Bash(oto:*)"]}
    assert settings["enabledPlugins"] == {"claims@acme": True, "tool@acme": True, "oto@acme": True}
    assert [p["id"] for p in lockfile.read(project)["plugins"]] == ["claims@acme", "oto@acme", "tool@acme"]
    assert main(["lock", "--use", "nomarket", "--project", project.data]) == 1


def test_without_claude_code_installs_nothing_is_declared(tmp_path, monkeypatch):
    monkeypatch.setenv(ontologies.CLAUDE_CONFIG_ENV, str(tmp_path / "no-claude"))
    root = str(tmp_path / "project")
    init(root, slug="p", name="P", ontology="auto-claims")
    assert not os.path.exists(os.path.join(root, ".claude"))
    assert lockfile.read(Project.standard(root))["plugins"] == []


def test_a_shipped_ontology_with_an_installed_pack_declares_the_pack_for_its_skills(claude):
    """ddd ships with the engine, and the ddd pack brings model-domain: naming it declares the pack."""
    assert main(["pack", "new", "orgs", "--ontology", "organization-process", "--to", str(claude["tmp"] / "cache" / "orgs")]) == 0
    _installed_pack(claude, "orgs@acme", claude["tmp"] / "cache" / "orgs" / "orgs")
    _installed_pack(claude, "orgs@elsewhere", claude["tmp"] / "cache" / "orgs" / "orgs")
    root = str(claude["tmp"] / "project")
    init(root, slug="p", name="P", ontology="organization-process", empty=True)
    assert ontologies.origin("organization-process") == ontologies.BUILTIN
    assert _settings(Project.standard(root))["enabledPlugins"] == {"orgs@acme": True, "oto@acme": True}


def test_the_pack_of_an_ontology_a_named_one_extends_is_declared_too(claude):
    """report under product-report: the report pack brings new-report."""
    from test_pack_ontologies import _pack
    _installed_pack(claude, "claimsplus@acme", _pack(str(claude["tmp"] / "cache" / "claimsplus"), "pack-claims",
                                                     {"pack-claims": ("auto-claims", 3), "oto-core": ("oto-core", 5)}))
    assert main(["pack", "new", "core", "--ontology", "oto-core", "--to", str(claude["tmp"] / "cache" / "core")]) == 0
    _installed_pack(claude, "core@acme", claude["tmp"] / "cache" / "core" / "core")
    root = str(claude["tmp"] / "project")
    init(root, slug="p", name="P", ontology="pack-claims", empty=True)
    assert _settings(Project.standard(root))["enabledPlugins"] == {"claimsplus@acme": True, "core@acme": True, "oto@acme": True}
