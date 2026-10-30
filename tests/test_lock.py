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
    """organization-process ships with the engine, and a pack that embeds it brings its skills: naming it declares the pack."""
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


# ---- what the project's plugins offer: oto status and the concierge ----

def test_status_lists_the_projects_packs_with_their_skills_and_views(claude, capsys):
    claims = claude["installs"]["claims@acme"][0]["installPath"]
    for skill, text in (("model-claims", "Model a claim from first notice to settlement: the parties. Use when"),
                        ("start", "Start a project from this pack.")):
        os.makedirs(os.path.join(claims, "skills", skill))
        with open(os.path.join(claims, "skills", skill, "SKILL.md"), "w") as f:
            f.write("---\nname: %s\ndescription: >-\n  %s\n---\n\n# x\n" % (skill, text))
    os.makedirs(os.path.join(claims, "views", "claims-map"))
    with open(os.path.join(claims, "views", "claims-map", "app.json"), "w") as f:
        f.write("{}")
    project = _project(claude)
    os.makedirs(os.path.join(project.data, ".claude"))
    with open(os.path.join(project.data, ".claude", "settings.json"), "w") as f:
        json.dump({"enabledPlugins": {"claims@acme": True, "oto@acme": True, "orders@acme": True}}, f)
    capsys.readouterr()
    assert main(["status", "--project", project.data]) == 0
    out = capsys.readouterr().out
    assert "packs       2, declared in .claude/settings.json" in out
    assert "claims 2.0.0" in out and "model-claims; view claims-map" in out and "start" not in out.split("packs")[1].split("\n")[1]
    assert "orders" in out and "NOT INSTALLED here: claude plugin install orders@acme" in out
    assert main(["status", "--json", "--project", project.data]) == 0
    offered = json.loads(capsys.readouterr().out)["packs"]
    claims_entry = [p for p in offered["plugins"] if p["name"] == "claims"][0]
    assert {"name": "model-claims", "summary": "Model a claim from first notice to settlement",
            "command": "/claims:model-claims"} in claims_entry["skills"]
    assert claims_entry["pack"] is True and claims_entry["views"] == ["claims-map"]
    assert all(p["name"] != "oto" for p in offered["plugins"]), "the engine's own skills are the concierge's table"


def test_status_says_when_the_project_uses_no_pack(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(ontologies.CLAUDE_CONFIG_ENV, str(tmp_path / "no-claude"))
    root = str(tmp_path / "project")
    init(root, slug="p", name="P", ontology="auto-claims")
    capsys.readouterr()
    assert main(["status", "--project", root]) == 0
    assert "packs       none for this project" in capsys.readouterr().out


def test_the_concierge_routes_to_the_projects_packs_first():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(root, "skills", "concierge", "SKILL.md"), encoding="utf-8").read()
    assert "`packs` lists plugins" in text and "The project's packs come first" in text
    assert "Read the engine; tell it in plain words" in text and "Quote the engine" not in text
    assert "NOT INSTALLED" in text and "oto status --json" in text


# ---- the views of every declared pack ----

def _with_view(directory, name, summary):
    view = os.path.join(str(directory), "views", name)
    os.makedirs(view)
    with open(os.path.join(view, "app.json"), "w") as f:
        json.dump({"name": name, "summary": summary, "entry": "index.html",
                   "data": [{"file": "data.js", "format": "js-globals", "globals": {"__X__": {"$const": 1}}}]}, f)
    with open(os.path.join(view, "index.html"), "w") as f:
        f.write("<title>%s</title>" % name)


def test_init_installs_the_views_of_every_declared_pack(claude, capsys):
    from test_pack_ontologies import _pack
    directory = _pack(str(claude["tmp"] / "cache" / "claimsplus"), "pack-claims",
                      {"pack-claims": ("auto-claims", 3), "oto-core": ("oto-core", 5)})
    _with_view(directory, "claims-map", "Where each claim stands.")
    _with_view(directory, "workbench", "A pack view named like the built-in.")
    _installed_pack(claude, "claimsplus@acme", directory)
    root = str(claude["tmp"] / "project")
    init(root, slug="p", name="P", ontology="pack-claims", empty=True)
    out = capsys.readouterr().out
    assert "wrote: views/claims-map (from claimsplus@acme)" in out
    assert os.path.exists(os.path.join(root, "views", "claims-map", "app.json"))
    from oto.apps import manifest as apps
    assert [name for name, _d in apps.project_views(root)] == ["claims-map", "workbench"]
    assert apps.project_views(root)[1][1] == os.path.join(root, "views", "workbench"), "a project view wins over the built-in"
    assert apps.default_view(root) == apps.ALL


def test_lock_use_installs_the_views_of_the_tool_it_declares(claude, capsys):
    project = _project(claude)
    _with_view(claude["installs"]["tool@acme"][0]["installPath"], "tool-board", "The tool's board.")
    capsys.readouterr()
    assert main(["lock", "--use", "tool@acme", "--project", project.data]) == 0
    assert "installed views/tool-board (from tool@acme)" in capsys.readouterr().out
    assert os.path.isdir(os.path.join(project.data, "views", "tool-board"))


def test_a_project_without_views_of_its_own_keeps_the_workbench(tmp_path):
    from oto.apps import manifest as apps
    assert apps.default_view(str(tmp_path)) == "workbench"
    assert apps.project_views(str(tmp_path)) == [("workbench", os.path.join(apps.UI_DIR, "workbench"))]


def test_status_marks_the_projects_pattern_packs(claude, capsys):
    claims = claude["installs"]["claims@acme"][0]["installPath"]
    with open(os.path.join(claims, "manifest.json"), "w") as f:
        json.dump({"name": "claims", "pattern": {"of": "software-architecture", "for": "a claims part", "skill": "model-claims"}}, f)
    project = _project(claude)
    capsys.readouterr()
    assert main(["status", "--project", project.data]) == 0
    assert "(pattern of software-architecture)" in capsys.readouterr().out
    assert main(["status", "--json", "--project", project.data]) == 0
    offered = {p["name"]: p for p in json.loads(capsys.readouterr().out)["packs"]["plugins"]}
    assert offered["claims"]["pattern"]["skill"] == "model-claims" and offered["tool"]["pattern"] is None


def test_status_marks_the_projects_playbook(claude, capsys):
    claims = claude["installs"]["claims@acme"][0]["installPath"]
    with open(os.path.join(claims, "manifest.json"), "w") as f:
        json.dump({"name": "claims", "playbook": {"for": "a claim, from first notice to settlement", "skill": "lead-claim"}}, f)
    project = _project(claude)
    capsys.readouterr()
    assert main(["status", "--project", project.data]) == 0
    assert "(playbook: lead-claim)" in capsys.readouterr().out
    assert main(["status", "--json", "--project", project.data]) == 0
    offered = {p["name"]: p for p in json.loads(capsys.readouterr().out)["packs"]["plugins"]}
    assert offered["claims"]["playbook"]["for"] == "a claim, from first notice to settlement"


def test_status_marks_the_projects_binding(claude, capsys):
    claims = claude["installs"]["claims@acme"][0]["installPath"]
    with open(os.path.join(claims, "manifest.json"), "w") as f:
        json.dump({"name": "claims", "binding": {"of": "software-architecture", "for": "where each part runs", "skill": "bind-platform"}}, f)
    project = _project(claude)
    capsys.readouterr()
    assert main(["status", "--project", project.data]) == 0
    assert "(binding of software-architecture)" in capsys.readouterr().out
    assert main(["status", "--json", "--project", project.data]) == 0
    offered = {p["name"]: p for p in json.loads(capsys.readouterr().out)["packs"]["plugins"]}
    assert offered["claims"]["binding"]["skill"] == "bind-platform" and offered["tool"]["binding"] is None


def test_lock_sandbox_writes_the_projects_docker_sandbox_and_lock_keeps_it_current(claude, capsys):
    """sbxenv.yaml names the sandbox and pins the engine; .sandbox/setup.sh restores the locked tools inside it,
    with what Docker's Claude image lacks. A plain `oto lock` rewrites both while they are its own."""
    project = _project(claude)
    capsys.readouterr()
    assert main(["lock", "--sandbox", "--project", project.data]) == 0
    out = capsys.readouterr().out
    assert "wrote .sandbox/setup.sh and sbxenv.yaml: the Docker sandbox oto-p" in out and "sbx env run" in out
    env = open(os.path.join(project.data, "sbxenv.yaml"), encoding="utf-8").read()
    pin = lockfile.engine_pin(lockfile.read(project))
    assert "name: oto-p\nagent: claude\nworkspace: .\n" in env
    assert 'OTO_SOURCE: "%s"' % pin.replace("[intake]", "") in env
    assert 'command: sbx exec "$SBX_SANDBOX_NAME" -- sh "$SBX_WORKSPACE/.sandbox/setup.sh"' in env, "whatever name it is created under"
    setup_path = os.path.join(project.data, ".sandbox", "setup.sh")
    setup = open(setup_path, encoding="utf-8").read()
    assert os.access(setup_path, os.X_OK)
    for needed in ("libreoffice-writer-nogui", "exec uv tool run", 'insteadOf git@github.com:', "claude plugin install oto@acme",
                   'uv tool install --force "%s"' % pin, "playwright install --with-deps chromium", "oto lock --check --project ."):
        assert needed in setup, needed
    assert setup.index("claude plugin marketplace add") < setup.index("claude plugin install"), "the marketplace comes first"
    subprocess.run(["sh", "-n", setup_path], check=True)

    _install(claude, "tool@acme", "0.5.0")
    assert main(["lock", "--project", project.data]) == 0
    assert "the Docker sandbox oto-p" in capsys.readouterr().out
    assert "claude plugin install tool@acme    # locked at 0.5.0" in open(setup_path, encoding="utf-8").read()
    assert main(["status", "--project", project.data]) == 0
    assert "sandbox     sbxenv.yaml: the Docker sandbox oto-p runs in" in capsys.readouterr().out

    with open(os.path.join(project.data, "sbxenv.yaml"), "w", encoding="utf-8") as f:
        f.write('schemaVersion: "1"\nagent: claude\n')
    assert main(["lock", "--project", project.data]) == 0
    assert "sbxenv.yaml is not the one oto lock --sandbox writes, so it was left as it is" in capsys.readouterr().out
    assert open(os.path.join(project.data, "sbxenv.yaml"), encoding="utf-8").read() == 'schemaVersion: "1"\nagent: claude\n'


def test_lock_sandbox_needs_a_lock(tmp_path, capsys):
    root = str(tmp_path / "p")
    init(root, slug="p", name="P", ontology="auto-claims")
    os.remove(os.path.join(root, "oto.lock.json")) if os.path.exists(os.path.join(root, "oto.lock.json")) else None
    assert main(["lock", "--sandbox", "--project", root]) == 1
    assert "no oto.lock.json yet" in capsys.readouterr().err
