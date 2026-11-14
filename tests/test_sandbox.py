"""`oto sandbox`: everything a person would type to get OTO's kit running in a Docker sandbox, against a
fake `sbx` and `ssh` that keep their state in a JSON file. The person's approval of the kit's use of
their Anthropic sign-in is written only when they gave it, and only next to what is already there."""
import json
import os
import stat
import sys

import pytest
import re

from oto import __version__, sandbox

_REAL_BINDABLE = sandbox._bindable       # kept before the fake fixture replaces it
from oto.cli import main

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the fakes are scripts run through their #! line")

FAKE_SBX = r'''
import json, os, sys
path = os.environ["FAKE_SBX_STATE"]
state = json.load(open(path))
args = sys.argv[1:]
state["calls"].append(args)
out, err, code = "", "", 0
def save():
    json.dump(state, open(path, "w"))
if args[:1] == ["version"]:
    out = "sbx version v%s 5caf923e\n" % state.get("version", "0.51.0")
elif not state["signed_in"] and args[:1] in (["ls"], ["create"]):
    err, code = "error: not signed in to Docker\ntry: sbx login\n", 1
elif args == ["ls", "--json"]:
    out = json.dumps([{"name": name, "id": "x", "agent": box["agent"], "status": "running" if box["running"] else "stopped",
                       "workspaces": box["folders"], "created_at": box.get("created_at", "2026-10-01T10:00:00Z"),
                       "last_used_at": box.get("last_used_at")} for name, box in state["sandboxes"].items()])
elif args[:1] == ["ls"]:
    out = "SANDBOX   AGENT   STATUS   PORTS   WORKSPACE   CREATED\n"
elif args[:3] == ["policy", "allow", "network"]:
    state.setdefault("rules", {}).setdefault(args[args.index("--sandbox") + 1], []).append(args[-1])
elif args[:2] == ["policy", "ls"] and len(args) > 2:
    out = json.dumps({"rules": [{"resources": state.get("rules", {}).get(args[2], [])}]})
elif args[:2] == ["policy", "ls"]:
    if state["policy"]:
        out = "NAME   TYPE\nbalanced network\n"
    else:
        err, code = "error: global network policy has not been initialized\n", 1
elif args[:2] == ["policy", "init"]:
    state["policy"] = args[2]
elif args[:3] == ["settings", "get", "kit.allowedSources"]:
    out = json.dumps(state["sources"], separators=(",", ":")) + "\n"
elif args[:3] == ["settings", "set", "kit.allowedSources"]:
    state["sources"] = json.loads(args[3])
elif args == ["secret", "ls", "--json"]:
    out = json.dumps({"secrets": [{"scope": "global", "type": "service", "name": "anthropic", "secret": "(oauth configured)"}]
                      if state["anthropic_secret"] else [], "custom_secrets": []})
elif args[:1] == ["create"]:
    kit, rest = args[1], args[2:]
    folders, env, name, ports = [], {}, None, []
    while rest:
        a = rest.pop(0)
        if a == "--name":
            name = rest.pop(0)
        elif a == "-e":
            item = rest.pop(0)
            k, v = item.split("=", 1) if "=" in item else (item, os.environ.get(item, ""))
            env[k] = v
        elif a == "-p":
            host_port, sandbox_port = rest.pop(0).split(":")
            ports.append({"host_ip": "127.0.0.1", "host_port": int(host_port), "sandbox_port": int(sandbox_port), "protocol": "tcp4"})
        elif not a.startswith("--"):
            folders.append(a)
    state["sandboxes"][name] = {"agent": kit.split("/")[-1].split(":")[0], "running": True, "folders": folders,
                                "env": env, "init": state["init_line"], "ports": ports}
elif args[:1] == ["exec"]:
    box = state["sandboxes"][args[1]]
    box["running"] = True
    command = args[3:]
    if command[:1] == ["printenv"]:
        out = box["env"].get(command[1], "") + "\n"
    elif command[:2] == ["python3", "-c"]:
        allowed = box["env"].get("OTO_OUTSIDE_PLUGINS") == "allowed"
        out = json.dumps(box.get("lock") or {"mode": "allowed" if allowed else "blocked", "script": True, "settings": "ok",
                                             "forwarded": [] if allowed else ["engineering"], "loading": [],
                                             "switched_off": [] if allowed else ["engineering"] + box.get("given", []),
                                             "account_plugins_off": not allowed, "account_skills_off": not allowed,
                                             "connectors_off": not allowed, "hook": not allowed, "locked": not allowed}) + "\n"
    elif command[:2] == ["sh", "-c"] and "printenv" in command[2]:
        out = "".join(v + "\n" for v in command[4:] if not box["env"].get(v))
    elif command[:2] == ["sh", "-c"] and "lock-plugins\" --names" in command[2]:
        box["given"] = box.get("given", []) + command[4:]
    elif command[:2] == ["sh", "-c"] and "claude plugin install" in command[2]:
        box["plugins"] = box.get("plugins", []) + [{"project": command[4], "plugin": p} for p in command[5:]]
        out = "".join("Installed %s\n" % p for p in command[5:])
    elif "oto-init.log" in command[-1]:
        out = box["init"] + "\n"
elif args[:1] == ["ports"]:
    box = state["sandboxes"].get(args[1])
    if box is None:
        err, code = "error: no such sandbox\n", 1
    elif "--publish" in args:
        box["running"] = True
        host_port, sandbox_port = args[args.index("--publish") + 1].split(":")
        if any(p["host_port"] == int(host_port) for p in box.setdefault("ports", [])):
            err, code = "error: publish ports: 409 Conflict: port 127.0.0.1:%s/tcp4 is already published\n" % host_port, 1
        else:
            box["ports"].append({"host_ip": "127.0.0.1", "host_port": int(host_port), "sandbox_port": int(sandbox_port), "protocol": "tcp4"})
            out = "Published 127.0.0.1:%s -> %s/tcp4\n" % (host_port, sandbox_port)
    elif "--json" in args:
        out = json.dumps(box.get("ports", []))
    else:
        out = "HOST IP     HOST PORT   SANDBOX PORT   PROTOCOL\n"
elif args[:1] == ["rm"]:
    state["sandboxes"].pop(args[-1], None)
elif args[:1] == ["stop"]:
    state["sandboxes"][args[-1]]["running"] = False
elif args[:2] == ["setup", "ssh"]:
    state["ssh"] = True
elif args[:1] == ["mcp"]:
    pass
save()
sys.stdout.write(out)
sys.stderr.write(err)
sys.exit(code)
'''

FAKE_SSH = r'''
import json, os, sys
state = json.load(open(os.environ["FAKE_SBX_STATE"]))
host = sys.argv[-1]
print("host %s" % host)
if state["ssh"] and host[:-4] in state["sandboxes"]:
    print('proxycommand "/opt/homebrew/bin/sbx" ssh proxy %n')
'''


def _script(path, body):
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!%s\n%s" % (sys.executable, body))
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """A computer with sbx installed and signed in, a balanced policy, nothing else."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    state_file = tmp_path / "sbx.json"
    monkeypatch.setenv("FAKE_SBX_STATE", str(state_file))
    monkeypatch.setenv("OTO_SBX", _script(str(tmp_path / "sbx"), FAKE_SBX))
    monkeypatch.setenv("OTO_SSH", _script(str(tmp_path / "ssh"), FAKE_SSH))
    monkeypatch.setattr(sandbox, "_bindable", lambda port: True)      # the fake computer's ports are the fake sandboxes' alone

    class Fake(object):
        path = state_file
        credentials = home / ".config" / "sbx" / "credentials.yaml"

        def __init__(self):
            self.write(signed_in=True, policy="balanced", sources=["docker.io/"], anthropic_secret=True, ssh=False,
                       sandboxes={}, init_line="OTO ready: 11 plugins", calls=[])

        def read(self):
            return json.loads(state_file.read_text())

        def write(self, **changes):
            state = self.read() if state_file.exists() else {}
            state.update(changes)
            state_file.write_text(json.dumps(state))

        def calls(self, verb):
            return [c for c in self.read()["calls"] if c[:1] == [verb]]

    return Fake()


def test_without_the_sandbox_tool_it_says_how_to_install_it(fake, monkeypatch, tmp_path):
    monkeypatch.setenv("OTO_SBX", str(tmp_path / "nowhere"))
    with pytest.raises(sandbox.SandboxError) as e:
        sandbox.up(approve=True)
    assert "not installed" in str(e.value) and "brew install docker/tap/sbx" in e.value.fix and "winget" in e.value.fix
    assert sandbox.status()["sbx"] is None


def test_a_sandbox_tool_older_than_the_kit_needs_is_upgraded_first(fake, tmp_path, capsys):
    """sbx 0.51 runs the built-in agents from published schema-3 kits, and OTO's kit is one: an older
    sbx is sent to its upgrade before anything changes on the computer."""
    fake.write(version="0.50.1")
    with pytest.raises(sandbox.SandboxError) as e:
        sandbox.up(approve=True, directory=str(tmp_path / "w"))
    assert "0.50.1" in str(e.value) and sandbox.MIN_SBX in str(e.value)
    assert "brew upgrade docker/tap/sbx" in e.value.fix and "winget upgrade" in e.value.fix
    assert not fake.calls("create") and not fake.calls("settings") and not fake.calls("policy")[1:]
    assert not fake.credentials.exists()
    assert sandbox.status()["sbx_supported"] is False
    assert main(["sandbox", "status"]) == 1, "no sandbox ready"
    assert "older than the kit needs (%s or later)" % sandbox.MIN_SBX in capsys.readouterr().out
    fake.write(version=sandbox.MIN_SBX)
    assert sandbox.status()["sbx_supported"] is True
    sandbox.up(approve=True, directory=str(tmp_path / "w"))
    assert fake.calls("create")


def test_a_local_kit_folder_is_named_after_its_folder(fake, tmp_path):
    """A schema-3 kit has no name field: sbx names a sandbox's kit after the last part of its registry
    reference, or the folder of a local one."""
    folder = tmp_path / "kits" / "oto-gcp"
    folder.mkdir(parents=True)
    (folder / "oto-gcp.yaml").write_text('# syntax=docker/sandbox-kit:3\nschemaVersion: "3"\nkind: set\n')
    assert sandbox._kit_name(str(folder)) == "oto-gcp" and sandbox._kit_name(str(folder) + "/") == "oto-gcp"
    assert sandbox._kit_name(sandbox.kit_ref()) == "oto-gcp"
    sandbox.up(name="local", approve=True, directory=str(tmp_path / "w"), kit=str(folder))
    assert fake.calls("create")[0][1] == str(folder)
    assert sandbox.status("local")["from_kit"], "a sandbox made from the local kit is OTO's"


def test_signed_out_it_sends_the_person_to_sbx_login(fake):
    fake.write(signed_in=False)
    with pytest.raises(sandbox.SandboxError) as e:
        sandbox.up(approve=True)
    assert "sbx login" in e.value.fix
    assert not fake.calls("create")


def test_the_network_policy_is_set_only_when_the_person_chose_one(fake, tmp_path):
    fake.write(policy=None)
    with pytest.raises(sandbox.SandboxError) as e:
        sandbox.up(approve=True, directory=str(tmp_path / "w"))
    assert "--init-policy balanced" in e.value.fix and not fake.calls("policy")[1:]
    report = sandbox.up(approve=True, directory=str(tmp_path / "w"), init_policy="balanced")
    assert ["policy", "init", "balanced"] in fake.read()["calls"]
    assert "set the network policy for sandboxes to balanced" in report["done"]


def test_kits_from_otos_registry_are_allowed_next_to_the_others(fake, tmp_path):
    fake.write(sources=["docker.io/", "example.org/"])
    report = sandbox.up(approve=True, directory=str(tmp_path / "w"))
    assert fake.read()["sources"] == ["docker.io/", "example.org/", "ghcr.io/cynergis/"]
    assert "let sbx run kits from ghcr.io/cynergis/" in report["done"]
    sandbox.up(directory=str(tmp_path / "w"))
    assert len([c for c in fake.calls("settings") if c[1] == "set"]) == 1, "once allowed, left alone"


def test_the_anthropic_approval_is_written_only_with_the_persons_yes(fake, tmp_path):
    with pytest.raises(sandbox.SandboxError) as e:
        sandbox.up(directory=str(tmp_path / "w"))
    assert "--approve-anthropic" in e.value.fix and "ask them" in e.value.fix
    assert not fake.credentials.exists() and not fake.calls("create")
    sandbox.up(directory=str(tmp_path / "w"), approve=True)
    text = fake.credentials.read_text()
    for domain in ("api.anthropic.com", "claude.ai", "console.anthropic.com", "mcp-proxy.anthropic.com", "platform.claude.com"):
        assert "- %s\n" % domain in text
    assert sandbox.anthropic_bound(str(fake.credentials))
    assert not sandbox.approve_anthropic(str(fake.credentials)), "a second approval writes nothing"
    assert fake.credentials.read_text() == text


def test_the_approval_keeps_the_other_bindings_and_their_indentation(tmp_path):
    path = tmp_path / "credentials.yaml"
    path.write_text("bindings:\n  github:\n    token:\n      domains:\n        - api.github.com\nother: 1\n")
    assert not sandbox.anthropic_bound(str(path))
    assert sandbox.approve_anthropic(str(path))
    text = path.read_text()
    assert text.startswith("bindings:\n  anthropic:\n    apiKey:\n      domains:\n        - api.anthropic.com\n")
    assert "  github:\n    token:\n      domains:\n        - api.github.com\nother: 1\n" in text
    assert sandbox.anthropic_bound(str(path))
    path.write_text("bindings: {}\n")
    sandbox.approve_anthropic(str(path))
    assert path.read_text().count("bindings:") == 1 and sandbox.anthropic_bound(str(path))
    path.write_text("bindings:\n    other:\n        anthropic: no\n")
    assert not sandbox.anthropic_bound(str(path)), "only a binding named anthropic counts"


def test_up_creates_the_folders_and_the_sandbox_waits_for_oto_and_sets_up_ssh(fake, tmp_path):
    work = tmp_path / "work"
    report = sandbox.up(name="oto-try", directory=str(work), project_id="my-project", approve=True)
    assert (work / "project").is_dir() and (work / "code").is_dir()
    create = fake.calls("create")[0]
    assert create[:6] == ["create", "ghcr.io/cynergis/oto-gcp:%s" % __version__, str(work / "project"),
                          str(work / "code"), "--name", "oto-try"]
    assert "-e" in create and "PROJECT=my-project" in create
    assert "%s=%s" % (sandbox.PROJECT_DIR_ENV, work / "project") in create and "%s=%s" % (sandbox.CODE_DIR_ENV, work / "code") in create, \
        "the folders' paths go in, so a shell opened over SSH or sbx run lands on the project (the kit's landing hook)"
    assert report["oto"] == "OTO ready: 11 plugins" and report["ssh"]
    assert ["setup", "ssh"] in fake.read()["calls"]
    steps = "\n".join(sandbox.next_steps(report))
    assert "oto-try.sbx" in steps and str(work / "project") in steps and "sbx run --name oto-try" in steps


def test_up_again_reuses_the_sandbox_and_says_when_it_differs(fake, tmp_path):
    sandbox.up(name="oto-try", directory=str(tmp_path / "w"), project_id="one", approve=True)
    report = sandbox.up(name="oto-try", directory=str(tmp_path / "w"), project_id="two")
    assert len(fake.calls("create")) == 1
    assert "reused the sandbox oto-try (running)" in report["done"]
    assert any("has one as its Google Cloud project, not two" in w for w in report["warnings"])
    report = sandbox.up(name="oto-try", directory=str(tmp_path / "elsewhere"))
    assert any("already works on" in w and "--recreate" in w for w in report["warnings"])
    assert report["project"] == str(tmp_path / "w" / "project"), "the next steps name the folder it works on"
    assert len(fake.calls("setup")) == 1, "SSH, once set up, is left alone"


def test_a_sandbox_of_that_name_not_made_from_the_kit_is_replaced_only_when_asked(fake, tmp_path):
    fake.write(sandboxes={"oto-try": {"agent": "claude", "running": False, "folders": ["/x"], "env": {}, "init": ""}})
    with pytest.raises(sandbox.SandboxError) as e:
        sandbox.up(name="oto-try", directory=str(tmp_path / "w"), approve=True)
    assert "made from claude" in str(e.value) and "--recreate" in e.value.fix
    report = sandbox.up(name="oto-try", directory=str(tmp_path / "w"), recreate=True)
    calls = fake.read()["calls"]
    assert calls.index(["rm", "-f", "oto-try"]) < calls.index(fake.calls("create")[0])
    assert fake.read()["sandboxes"]["oto-try"]["agent"] == "oto-gcp" and report["oto"].startswith("OTO ready")


def test_oto_not_ready_inside_says_where_to_look(fake, tmp_path):
    fake.write(init_line="uv tool install failed")
    with pytest.raises(sandbox.SandboxError) as e:
        sandbox.up(name="oto-try", directory=str(tmp_path / "w"), approve=True, wait=5)
    assert "uv tool install failed" in str(e.value) and "/tmp/oto-init.log" in e.value.fix


def test_a_start_that_failed_is_said_at_once(fake, tmp_path):
    """The kit's start ends on `OTO ready` or `OTO failed`; up waits for either, not ten minutes for
    the first, and says the failure with where to read why."""
    fake.write(init_line="OTO failed: the engine is not installed; the lines above say why")
    with pytest.raises(sandbox.SandboxError) as e:
        sandbox.up(name="oto-try", directory=str(tmp_path / "w"), approve=True)
    assert "OTO failed" in str(e.value) and "tail -20 /tmp/oto-init.log" in e.value.fix
    wait = [c for c in fake.calls("exec") if "oto-init.log" in c[-1]][0][-1]
    assert 'grep -q -e "%s" -e "%s"' % (sandbox.READY, sandbox.FAILED) in wait


def test_check_changes_nothing(fake, tmp_path):
    fake.write(policy=None)
    report = sandbox.up(directory=str(tmp_path / "w"), approve=True, init_policy="balanced", check=True)
    assert report["done"] == ["set the network policy for sandboxes to balanced", "let sbx run kits from ghcr.io/cynergis/",
                              "recorded the approval for the kit to use the Anthropic sign-in (%s)" % fake.credentials,
                              "would create the sandbox oto-sandbox from ghcr.io/cynergis/oto-gcp:%s" % __version__]
    state = fake.read()
    assert state["policy"] is None and state["sources"] == ["docker.io/"] and not state["sandboxes"]
    assert not fake.credentials.exists() and not (tmp_path / "w").exists()


def test_status_reads_without_starting_a_stopped_sandbox(fake, tmp_path):
    sandbox.up(name="oto-try", directory=str(tmp_path / "w"), approve=True)
    state = fake.read()
    state["sandboxes"]["oto-try"]["running"] = False
    fake.write(sandboxes=state["sandboxes"], calls=[])
    s = sandbox.status("oto-try")
    assert s["sandbox"] == "stopped" and s["from_kit"] and s["oto"] is None and s["ssh"]
    assert s["folders"] == [str(tmp_path / "w" / "project"), str(tmp_path / "w" / "code")]
    assert not fake.calls("exec")
    assert sandbox.status("nothing")["sandbox"] is None


def test_the_command_reports_in_json_for_a_skill(fake, tmp_path, capsys):
    assert main(["sandbox", "up", "--dir", str(tmp_path / "w"), "--json"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and "Anthropic sign-in" in out["problem"] and "--approve-anthropic" in out["fix"]
    assert main(["sandbox", "up", "--dir", str(tmp_path / "w"), "--approve-anthropic", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["ssh"] and any("oto-sandbox.sbx" in line for line in out["next"])
    assert out["outside_plugins"]["locked"]
    assert main(["sandbox", "status"]) == 0
    printed = capsys.readouterr().out
    assert "running, made from oto-gcp; OTO ready: 11 plugins" in printed and "oto-sandbox.sbx" in printed
    assert "outside plugins blocked: only the sandbox's own plugins load (1 from your computer switched off)" in printed


def test_outside_plugins_are_blocked_unless_the_person_allows_them_at_creation(fake, tmp_path, capsys):
    report = sandbox.up(name="oto-try", directory=str(tmp_path / "w"), approve=True)
    assert not any("OTO_OUTSIDE_PLUGINS" in a for a in fake.calls("create")[0]), "blocked is the kit's default"
    assert report["outside_plugins"]["locked"]
    report = sandbox.up(name="oto-try", allow_outside=True)
    assert any("blocks plugins from outside it" in w and "--recreate" in w for w in report["warnings"])
    assert main(["sandbox", "up", "--name", "oto-open", "--dir", str(tmp_path / "o"), "--allow-outside-plugins"]) == 0
    assert ["-e", "OTO_OUTSIDE_PLUGINS=allowed"] == fake.calls("create")[-1][-2:]
    assert "outside plugins: allowed, by choice" in capsys.readouterr().out
    assert sandbox.status("oto-open")["outside_plugins"]["mode"] == "allowed"


def test_status_says_what_would_load_when_the_lock_is_not_in_place(fake, tmp_path, capsys):
    sandbox.up(name="oto-old", directory=str(tmp_path / "w"), approve=True)
    state = fake.read()
    state["sandboxes"]["oto-old"]["lock"] = {"mode": "blocked", "script": False, "settings": "ok", "forwarded": ["engineering", "bmad"],
                                              "loading": ["bmad"], "account_plugins_off": True, "account_skills_off": False,
                                              "connectors_off": True, "hook": False, "locked": False}
    fake.write(sandboxes=state["sandboxes"])
    main(["sandbox", "status", "--name", "oto-old"])
    assert "outside plugins NOT blocked: bmad, your claude.ai skills would load in a new session" in capsys.readouterr().out
    state["sandboxes"]["oto-old"]["lock"].update(loading=[], account_skills_off=True, locked=True)
    fake.write(sandboxes=state["sandboxes"])
    main(["sandbox", "status", "--name", "oto-old"])
    assert "blocked, but without the check at each session start" in capsys.readouterr().out


def _desktop(home, synced=(), skills_bundle=None):
    """Claude Desktop's plugins on this computer, where it keeps them."""
    for folder, name in synced:
        path = home / ".claude" / "plugins" / "synced" / "org_account" / folder / ".claude-plugin"
        path.mkdir(parents=True)
        if name:
            (path / "plugin.json").write_text(json.dumps({"name": name}))
    if skills_bundle:
        path = home / "Library" / "Application Support" / "Claude" / "local-agent-mode-sessions" / "skills-plugin" / "org" / "acct" / ".claude-plugin"
        path.mkdir(parents=True)
        (path / "plugin.json").write_text(json.dumps({"name": skills_bundle}))


def test_desktops_plugins_are_read_where_desktop_keeps_them(fake, tmp_path):
    home = tmp_path / "home"
    _desktop(home, synced=[("engineering~g2", "engineering"), ("bmad", "bmad"), ("productivity~g3", None)],
             skills_bundle="anthropic-skills")
    assert sandbox.desktop_plugins() == ["bmad", "engineering", "productivity", "anthropic-skills"]


def test_up_switches_off_desktops_plugins_before_the_first_session(fake, tmp_path):
    _desktop(tmp_path / "home", synced=[("engineering", "engineering"), ("bmad", "bmad")], skills_bundle="anthropic-skills")
    report = sandbox.up(name="oto-try", directory=str(tmp_path / "w"), approve=True)
    given = [c for c in fake.calls("exec") if c[3:5] == ["sh", "-c"] and "lock-plugins\" --names" in c[5]]
    assert len(given) == 1 and given[0][7:] == ["bmad", "anthropic-skills"], "engineering is switched off already"
    assert "switched off in the sandbox the 2 plugins Claude Desktop would bring from this computer" in report["done"]
    assert report["outside_plugins_summary"] == "blocked: only the sandbox's own plugins load (3 from your computer switched off)"
    again = sandbox.up(name="oto-try")
    assert len([c for c in fake.calls("exec") if "lock-plugins\" --names" in " ".join(c)]) == 1, "nothing new: nothing passed"
    assert not any("Claude Desktop would bring" in line for line in again["done"])
    _desktop(tmp_path / "home", synced=[("diagram-design", "diagram-design")])
    assert "diagram-design from this computer would load once in the next session: oto sandbox up switches it off now" \
        in sandbox.status("oto-try")["outside_plugins_summary"]
    sandbox.up(name="oto-try")
    assert "blocked: only" in sandbox.status("oto-try")["outside_plugins_summary"]


def test_up_passes_nothing_when_outside_plugins_are_allowed(fake, tmp_path):
    _desktop(tmp_path / "home", synced=[("bmad", "bmad")])
    sandbox.up(name="oto-open", directory=str(tmp_path / "o"), approve=True, allow_outside=True)
    assert not [c for c in fake.calls("exec") if "lock-plugins\" --names" in " ".join(c)]


def test_up_warns_about_a_sandbox_made_from_a_kit_without_the_lock(fake, tmp_path, capsys):
    sandbox.up(name="oto-old", directory=str(tmp_path / "w"), approve=True)
    state = fake.read()
    state["sandboxes"]["oto-old"]["lock"] = {"mode": "blocked", "script": False, "settings": "ok", "forwarded": [], "loading": [],
                                              "switched_off": [], "account_plugins_off": False, "account_skills_off": False,
                                              "connectors_off": False, "hook": False, "locked": False}
    fake.write(sandboxes=state["sandboxes"])
    assert main(["sandbox", "up", "--name", "oto-old", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert any("made from a kit without the plugin lock" in w and "--recreate" in w for w in out["warnings"])
    assert "NOT blocked" in out["outside_plugins_summary"] and "kit without the plugin lock" in out["outside_plugins_summary"]


# ---- ls, stop and rm: every sandbox, and cleaning up ----

def test_ls_lists_every_sandbox_with_its_use_its_folders_and_desktops_stale_connections(fake, tmp_path, monkeypatch, capsys):
    import datetime
    gone = str(tmp_path / "gone" / "project")
    fake.write(ssh=True, sandboxes={
        "northwind": {"agent": "oto-gcp", "running": True, "folders": [str(tmp_path / "home")], "env": {}, "init": "OTO ready: 1 plugins",
                      "last_used_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "old-try": {"agent": "oto-gcp", "running": False, "folders": [gone], "env": {}, "init": "", "last_used_at": "2026-10-01T10:00:00Z"},
        "other": {"agent": "claude", "running": False, "folders": [], "env": {}, "init": ""}})
    desktop = tmp_path / "home" / "Library" / "Application Support" / "Claude"
    desktop.mkdir(parents=True)
    (desktop / "ssh_configs.json").write_text(json.dumps({"configs": [
        {"name": "northwind", "sshHost": "northwind.sbx"}, {"name": "first try", "sshHost": "oto-first.sbx"}, {"name": "devbox", "sshHost": "dev.example.com"}]}))
    listing = sandbox.list_sandboxes()
    by_name = {b["name"]: b for b in listing["sandboxes"]}
    assert list(by_name) == ["northwind", "old-try", "other"]
    assert by_name["northwind"]["status"] == "running" and by_name["northwind"]["from_kit"] and by_name["northwind"]["idle_days"] == 0 and by_name["northwind"]["ssh"]
    assert by_name["northwind"]["folders"][0]["exists"] is True
    assert by_name["old-try"]["status"] == "stopped" and by_name["old-try"]["idle_days"] >= 20 and by_name["old-try"]["folders"] == [{"path": gone, "exists": False}]
    assert by_name["other"]["from_kit"] is False and by_name["other"]["idle_days"] is None, "sbx said nothing about its use"
    assert listing["connections"] == [{"name": "northwind", "host": "northwind.sbx", "sandbox": "northwind", "exists": True},
                                      {"name": "first try", "host": "oto-first.sbx", "sandbox": "oto-first", "exists": False}], \
        "only .sbx hosts are sandboxes; a connection with no sandbox behind it is stale"
    assert main(["sandbox", "ls"]) == 0
    out = capsys.readouterr().out
    assert "3 sandbox(es)" in out and "old-try" in out and "(folder gone)" in out and "not OTO's kit" in out
    assert "1 with no sandbox behind them any more: first try" in out and "SSH environment menu" in out
    assert main(["sandbox", "ls", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["connections"][1]["exists"] is False


def test_stop_and_rm_act_only_on_sandboxes_that_exist_and_say_what_stays(fake, capsys):
    fake.write(sandboxes={"a": {"agent": "oto-gcp", "running": True, "folders": [], "env": {}, "init": ""},
                          "b": {"agent": "oto-gcp", "running": True, "folders": [], "env": {}, "init": ""}})
    assert main(["sandbox", "stop", "a"]) == 0
    assert "stopped the sandbox a" in capsys.readouterr().out and fake.read()["sandboxes"]["a"]["running"] is False
    assert main(["sandbox", "rm", "b", "nope"]) == 1
    out = capsys.readouterr()
    assert "removed the sandbox b" in out.out and "folders on this computer stay" in out.out and "SSH connection" in out.out
    assert "no sandbox named nope" in out.err
    assert set(fake.read()["sandboxes"]) == {"a"} and fake.calls("rm") == [["rm", "-f", "b"]]
    assert main(["sandbox", "rm"]) == 1 and "takes the sandbox name(s)" in capsys.readouterr().err
    assert main(["sandbox", "rm", "a", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"done": ["a"], "missing": [], "failed": [], "ok": True}


def test_ls_without_sbx_or_a_sign_in_says_so(fake, monkeypatch, capsys):
    fake.write(signed_in=False)
    listing = sandbox.list_sandboxes()
    assert listing["sbx"] and not listing["signed_in"] and listing["sandboxes"] == []
    assert main(["sandbox", "ls"]) == 1 and "not signed in" in capsys.readouterr().out
    monkeypatch.setenv("OTO_SBX", "/nowhere/sbx")
    assert sandbox.list_sandboxes()["sbx"] is None
    with pytest.raises(sandbox.SandboxError):
        sandbox.remove_sandboxes(["a"])


# ---- the published ports: oto serve inside, a browser tab on the computer ----

def test_up_publishes_the_serve_ports_at_creation_and_says_what_to_open(fake, tmp_path, capsys):
    work = tmp_path / "nw"
    assert main(["sandbox", "up", "--name", "nw", "--dir", str(work), "--approve-anthropic"]) == 0
    out = capsys.readouterr().out
    create = fake.calls("create")[0]
    assert create[:7] == ["create", "ghcr.io/cynergis/oto-gcp:%s" % __version__, str(work / "project"), str(work / "code"), "--name", "nw", "--no-progress"]
    assert create[7:11] == ["-p", "8798:8798", "-p", "8799:8799"], "published at creation, so the forward is live from the first start"
    assert fake.read()["sandboxes"]["nw"]["ports"][0]["sandbox_port"] == 8798
    assert "published ports 8798 and 8799 to this computer's localhost" in out and "ports: 8798 and 8799 published" in out
    assert "oto serve --project . --http 8798" in out and "open http://localhost:8798/" in out and "no token needed" in out
    s = sandbox.status("nw")
    assert [e["port"] for e in s["ports"]] == [8798, 8799] and s["ports"][0]["host"] == "127.0.0.1"
    assert main(["sandbox", "status", "--name", "nw"]) == 0
    assert "ports          8798, 8799 (oto serve --http <port> inside; open http://localhost:<port>/ on this computer)" in capsys.readouterr().out


def test_publish_chooses_the_ports_and_zero_means_none(fake, tmp_path):
    assert main(["sandbox", "up", "--name", "one", "--dir", str(tmp_path / "one"), "--publish", "9000", "--approve-anthropic"]) == 0
    assert ["-p", "9000:9000"] == fake.calls("create")[-1][7:9] and "-p" not in fake.calls("create")[-1][9:]
    assert main(["sandbox", "up", "--name", "none", "--dir", str(tmp_path / "none"), "--publish", "0", "--approve-anthropic"]) == 0
    assert "-p" not in fake.calls("create")[-1]


def test_up_on_an_existing_sandbox_publishes_what_is_missing_and_says_when_it_takes_effect(fake, tmp_path, capsys):
    fake.write(ssh=True, sandboxes={"old": {"agent": "oto-gcp", "running": True, "folders": [str(tmp_path / "old" / "project"), str(tmp_path / "old" / "code")],
                                            "env": {}, "init": "OTO ready: 1 plugins", "ports": [{"host_ip": "127.0.0.1", "host_port": 8798, "sandbox_port": 8798, "protocol": "tcp4"}]}})
    report = sandbox.up(name="old", directory=str(tmp_path / "old"), approve=True)
    published = [c for c in fake.calls("ports") if "--publish" in c]
    assert published == [["ports", "old", "--publish", "8799:8799"]], "only the missing port"
    assert [e["port"] for e in report["ports"]] == [8798, 8799]
    assert any("published port 8799" in d for d in report["done"])
    assert any("forwards from its next start" in w and "sbx stop old" in w for w in report["warnings"]), "a running sandbox forwards a new port at its next start"
    report = sandbox.up(name="old", directory=str(tmp_path / "old"), approve=True)
    assert not any("published port" in d for d in report["done"]) and not any("next start" in w for w in report["warnings"]), "nothing missing the second time"


def test_inside_the_kit_is_read_from_the_environment_or_the_kits_files(tmp_path, monkeypatch):
    monkeypatch.delenv(sandbox.INSIDE_ENV, raising=False)
    assert sandbox.inside_kit(environ={}, home=str(tmp_path)) is False
    assert sandbox.inside_kit(environ={sandbox.INSIDE_ENV: "kit"}, home=str(tmp_path)) is True
    (tmp_path / ".oto").mkdir()
    (tmp_path / ".oto" / "init.sh").write_text("#!/bin/sh\n")
    assert sandbox.inside_kit(environ={}, home=str(tmp_path)) is False, "init.sh alone is not the kit"
    (tmp_path / ".oto" / "lock-plugins").write_text("# lock\n")
    assert sandbox.inside_kit(environ={}, home=str(tmp_path)) is True


# ---- the kind, the repository and the token (docs/plans/ontology-workspace.md, phase 4) ----

FAKE_GH = r'''
import json, os, sys
path = os.environ["FAKE_SBX_STATE"]
state = json.load(open(path))
state.setdefault("gh_calls", []).append({"args": sys.argv[1:], "token": os.environ.get("GH_TOKEN")})
json.dump(state, open(path, "w"))
if sys.argv[1:3] == ["repo", "view"]:
    sys.stderr.write("GraphQL: Could not resolve to a Repository\n"); sys.exit(1)
sys.stdout.write("https://github.com/%s\n" % sys.argv[3]); sys.exit(0)
'''


def _bare(tmp_path, name="store.git"):
    import subprocess
    path = str(tmp_path / name)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", path], check=True)
    return path


def test_up_lays_out_a_knowledge_project_backed_by_a_repository_and_pushes_it_once(fake, tmp_path, monkeypatch):
    import subprocess
    from oto import sandbox
    bare = _bare(tmp_path)
    monkeypatch.setenv("FAKE_TOKEN", "a-token-that-never-reaches-a-file")
    report = sandbox.up(name="acme", directory=str(tmp_path / "acme"), kind="knowledge", repo=bare, token_env="FAKE_TOKEN", approve=True)
    project = str(tmp_path / "acme" / "project")
    assert report["kind"] == "knowledge" and report["repository"] == bare and report["commit"]
    assert os.path.exists(os.path.join(project, "project.config.json")) and os.path.exists(os.path.join(project, ".github", "workflows", "oto-checks.yml")), \
        "a knowledge project with the repository workflows, laid out before the sandbox was made"
    with open(os.path.join(project, "project.config.json"), encoding="utf-8") as f:
        assert json.load(f)["kind"] == "knowledge"
    log = subprocess.run(["git", "-C", bare, "log", "--oneline", "main"], capture_output=True, text=True).stdout
    assert "laid out by oto sandbox up" in log, "the first commit reached the repository"
    assert subprocess.run(["git", "-C", project, "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip() == bare
    assert any("pushed the first commit" in d for d in report["done"]) and any("knowledge project" in d for d in report["done"])
    assert [c for c in fake.calls("create")], "the sandbox was created after the layout"
    for root, _dirs, files in os.walk(str(tmp_path / "acme")):
        for name in files:
            with open(os.path.join(root, name), "rb") as f:
                assert b"a-token-that-never-reaches-a-file" not in f.read(), "the token is in no file of the folders: %s" % os.path.join(root, name)
    assert not [c for c in fake.calls("secret") if c[:2] == ["secret", "set"]], "a repository that is a path needs no GitHub secret in the sandbox"


def test_up_creates_the_github_repository_with_the_token_and_stores_it_as_the_sandbox_s_secret(fake, tmp_path, monkeypatch):
    from oto import sandbox
    monkeypatch.setenv("OTO_GH", _script(str(tmp_path / "gh"), FAKE_GH))
    monkeypatch.setenv("FAKE_TOKEN", "ghp-like-but-not")
    # the push to github.com cannot happen here: the dry run shows the plan, the real run is stopped at the push
    report = sandbox.up(name="fleet", directory=str(tmp_path / "fleet"), kind="ontology", repo="acme/fleet-ontology", token_env="FAKE_TOKEN", check=True, approve=True)
    assert report["repository"] == "https://github.com/acme/fleet-ontology.git"
    assert any("would create the private repository acme/fleet-ontology on GitHub with the token in FAKE_TOKEN" in d for d in report["done"]), report["done"]
    assert any("would lay out an ontology workspace for the pack fleet" in d for d in report["done"]), report["done"]
    assert not os.path.exists(str(tmp_path / "fleet" / "project" / "manifest.json")), "a dry run lays nothing out"
    url = sandbox.github_repository("acme/fleet-ontology", "ghp-like-but-not")
    assert url == "https://github.com/acme/fleet-ontology.git"
    calls = fake.read()["gh_calls"]
    assert calls[0]["args"][:3] == ["repo", "view", "acme/fleet-ontology"] and calls[1]["args"] == ["repo", "create", "acme/fleet-ontology", "--private"]
    assert all(c["token"] == "ghp-like-but-not" for c in calls), "the CLI gets the token through its environment"
    assert sandbox.github_repository(str(tmp_path), None) == str(tmp_path), "a path is a repository that exists"


def test_up_lays_out_an_ontology_workspace_with_no_repository_when_told_so(fake, tmp_path):
    from oto import sandbox
    report = sandbox.up(name="fleet", directory=str(tmp_path / "fleet"), kind="ontology", no_repo=True, approve=True)
    project = str(tmp_path / "fleet" / "project")
    assert report["kind"] == "ontology" and report["repository"] is None
    for path in ("manifest.json", "ontology/fleet/ontology.config.json", "trial/project.config.json", ".github/workflows/pack-check.yml"):
        assert os.path.exists(os.path.join(project, path)), path
    assert not os.path.isdir(os.path.join(project, ".git")), "no repository: no git"
    assert any("ontology workspace for the pack fleet" in d for d in report["done"]), report["done"]
    again = sandbox.up(name="fleet", directory=str(tmp_path / "fleet"), kind="ontology", no_repo=True, approve=True)
    assert not any("laid out" in d for d in again["done"]), "a folder that already holds a project is left alone"


def test_up_installs_in_the_sandbox_the_pack_plugins_the_project_declares(fake, tmp_path):
    """A knowledge project on a pack declares the pack's plugin in its .claude/settings.json (oto init
    --pack); the kit installs the engine plugin alone and the lock keeps the sandbox to what is
    installed inside it, so `up` installs the declared plugins inside, at project scope, from the
    project folder. The engine plugin is already there; a project with nothing declared installs none."""
    from oto import sandbox
    project = tmp_path / "board" / "project"
    project.mkdir(parents=True)
    (project / "project.config.json").write_text(json.dumps({"kind": "knowledge", "vocabulary": "derived"}))
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": {"kanban@cynergis": True, "oto@cynergis-engine": True}}))
    report = sandbox.up(name="board", directory=str(tmp_path / "board"), kind="knowledge", no_repo=True, approve=True, check=True)
    assert any(d == "would install in the sandbox the plugin kanban@cynergis the project declares, at project scope" for d in report["done"]), report["done"]
    assert fake.read()["sandboxes"] == {}, "a dry run installs nothing"
    report = sandbox.up(name="board", directory=str(tmp_path / "board"), kind="knowledge", no_repo=True, approve=True)
    box = fake.read()["sandboxes"]["board"]
    assert box.get("plugins") == [{"project": str(project), "plugin": "kanban@cynergis"}], "installed inside, from the project folder; the engine plugin is already there"
    assert any(d == "installed in the sandbox the plugin kanban@cynergis the project declares, at project scope" for d in report["done"]), report["done"]
    assert report["plugins"] == ["kanban@cynergis"]
    again = sandbox.up(name="board", directory=str(tmp_path / "board"), kind="knowledge", no_repo=True, approve=True)
    assert len(fake.read()["sandboxes"]["board"]["plugins"]) == 2, "run again, the install runs again: Claude Code says it is already there"
    assert again["plugins"] == ["kanban@cynergis"]
    # a knowledge project with no pack declares only the engine plugin: nothing to install
    bare = sandbox.up(name="bare", directory=str(tmp_path / "bare"), kind="knowledge", no_repo=True, approve=True)
    assert bare["plugins"] == [] and not fake.read()["sandboxes"]["bare"].get("plugins") and not any("installed in the sandbox" in d for d in bare["done"])
    # a workspace is a pack, not a project on one: nothing to install either
    fleet = sandbox.up(name="fleet", directory=str(tmp_path / "fleet"), kind="ontology", no_repo=True, approve=True)
    assert fleet["plugins"] == [] and not fake.read()["sandboxes"]["fleet"].get("plugins")


def test_a_kind_needs_a_repository_decision_and_a_github_repository_needs_a_token(fake, tmp_path):
    from oto import sandbox
    with pytest.raises(sandbox.SandboxError) as refused:
        sandbox.up(name="x", directory=str(tmp_path / "x"), kind="knowledge")
    assert "--repo" in refused.value.fix and "--no-repo" in refused.value.fix
    with pytest.raises(sandbox.SandboxError) as refused:
        sandbox.up(name="x", directory=str(tmp_path / "x"), kind="knowledge", repo="acme/x")
    assert "token" in str(refused.value) and "--github-token-env" in refused.value.fix
    with pytest.raises(sandbox.SandboxError):
        sandbox.up(name="x", directory=str(tmp_path / "x"), kind="knowledge", repo="acme/x", no_repo=True)


def test_the_command_takes_the_kind_the_repository_and_the_token_variable(fake, tmp_path, capsys):
    bare = _bare(tmp_path)
    os.environ["FAKE_TOKEN"] = "t"
    try:
        assert main(["sandbox", "up", "--name", "acme", "--dir", str(tmp_path / "acme"), "--kind", "knowledge", "--repo", bare,
                     "--github-token-env", "FAKE_TOKEN", "--approve-anthropic", "--json"]) == 0
    finally:
        os.environ.pop("FAKE_TOKEN", None)
    report = json.loads(capsys.readouterr().out)
    assert report["kind"] == "knowledge" and report["repository"] == bare and report["commit"]
    assert any("knowledge project" in line for line in report["next"]), report["next"]


def test_the_sandbox_skill_proposes_the_names_from_one_answer_and_names_the_token_variable_never_its_value():
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "sandbox", "SKILL.md"), encoding="utf-8") as f:
        text = f.read()
    for words in ("--kind", "--repo", "--no-repo", "--github-token-env", "ontology workspace", "knowledge project", "no repository",
                  "gh api user", "derived from", "never the value"):
        assert words in text, words
    assert not re.search(r"ghp_[A-Za-z0-9]{6,}", text)


def test_the_sandbox_skill_walks_the_two_sandboxes_in_order_and_asks_which_pack_a_graph_is_on():
    """ADR-0012: an ontology is made in a sandbox of its own, the workspace, and released; the graphs on
    it are made in other sandboxes, each a knowledge project on the released pack. The skill says the
    order, asks which pack a knowledge sandbox starts from, and says the pack must be on the computer
    before the sandbox is made, since the project is laid out there (`oto pack add`)."""
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "sandbox", "SKILL.md"), encoding="utf-8") as f:
        text = f.read()
    head, _sep, body = text.partition("\n---\n")
    assert "an ontology to make" in head and "a graph on one" in head, "the description names both sandboxes"
    assert "## Two sandboxes, in order" in body
    assert "the workspace sandbox comes first" in body and "a sandbox of its own for each team" in body
    assert "--pack <name>" in body and "**The pack** the graph is on" in body, "a knowledge sandbox is asked which pack"
    assert "oto pack add <name>" in body and "laid out on their computer before the sandbox exists" in body
    assert "not released yet" in body, "a pack still in the making sends the person to the workspace sandbox first"
    assert "the sandbox's name is the pack's name" in body, "an ontology sandbox is named after the pack it makes"
    assert "ontology-interview" in body and "build-knowledge-base" in body, "each sandbox's first skill is named"
    assert "installs inside it, at\nproject scope, the pack plugins the project declares" in body, "the pack's plugin is on from the first session"


# ---- two sandboxes at once: each gets free host ports ----

def test_a_second_sandbox_gets_free_host_ports_and_says_which_to_open(fake, tmp_path, capsys):
    """Every sandbox serves on 8798 and 8799 inside; the computer's side cannot hold the same port twice,
    so a second sandbox is published on the next free host ports and told which to open, and the
    sandbox port it serves on stays the same inside."""
    fake.write(ssh=True, sandboxes={"first": {"agent": "oto-gcp", "running": True, "folders": [str(tmp_path / "first" / "project"), str(tmp_path / "first" / "code")],
                                              "env": {}, "init": "OTO ready: 1 plugins",
                                              "ports": [{"host_ip": "127.0.0.1", "host_port": 8798, "sandbox_port": 8798, "protocol": "tcp4"},
                                                        {"host_ip": "127.0.0.1", "host_port": 8799, "sandbox_port": 8799, "protocol": "tcp4"}]}})
    work = tmp_path / "second"
    assert main(["sandbox", "up", "--name", "second", "--dir", str(work), "--approve-anthropic"]) == 0
    out = capsys.readouterr().out
    create = fake.calls("create")[-1]
    assert create[7:11] == ["-p", "8800:8798", "-p", "8801:8799"], "the host side moves, the sandbox side does not"
    assert "published port 8798 as localhost:8800 and 8799 as localhost:8801" in out and "8798 and 8799 are taken by the sandbox first" in out, out
    assert "oto serve --project . --http 8798" in out and "open http://localhost:8800/" in out and "8801 for a second view" in out, out
    s = sandbox.status("second")
    assert [(e["port"], e["host_port"]) for e in s["ports"]] == [(8798, 8800), (8799, 8801)]
    assert main(["sandbox", "status", "--name", "second"]) == 0
    assert "ports          8800->8798, 8801->8799" in capsys.readouterr().out
    # an existing sandbox that lacks a port gets a free host port too
    fake.write(ssh=True, sandboxes={"first": fake.read()["sandboxes"]["first"],
                                    "third": {"agent": "oto-gcp", "running": False, "folders": [str(tmp_path / "third" / "project"), str(tmp_path / "third" / "code")],
                                              "env": {}, "init": "OTO ready: 1 plugins", "ports": []}})
    report = sandbox.up(name="third", directory=str(tmp_path / "third"), approve=True)
    published = [c for c in fake.calls("ports") if "--publish" in c]
    assert published[-2:] == [["ports", "third", "--publish", "8800:8798"], ["ports", "third", "--publish", "8801:8799"]], published
    assert [(e["port"], e["host_port"]) for e in report["ports"]] == [(8798, 8800), (8799, 8801)]


def test_a_host_port_something_else_listens_on_is_skipped(fake, tmp_path, monkeypatch):
    import socket
    monkeypatch.setattr(sandbox, "_bindable", _REAL_BINDABLE)
    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    port = held.getsockname()[1]
    try:
        assert sandbox.free_host_port(port, set()) != port
        assert sandbox.free_host_port(port, set()) > port
        assert main(["sandbox", "up", "--name", "held", "--dir", str(tmp_path / "held"), "--publish", str(port), "--approve-anthropic"]) == 0
        mapping = fake.calls("create")[-1][8]
        assert mapping.endswith(":%d" % port) and not mapping.startswith("%d:" % port), mapping
    finally:
        held.close()


def test_up_with_a_repository_sets_the_branch_rules_on_a_knowledge_project(fake, tmp_path, monkeypatch):
    """The rules file `oto init --repo` writes is applied with the token the sandbox holds, right after
    the first push, so the route gate is required from the first pull request (docs/plans/graph-journeys.md)."""
    monkeypatch.setenv("OTO_GH", _script(str(tmp_path / "gh"), FAKE_GH))
    monkeypatch.setenv("FAKE_TOKEN", "ghp-like-but-not")
    report = sandbox.up(name="board", directory=str(tmp_path / "board"), kind="knowledge", repo="acme/board", token_env="FAKE_TOKEN", check=True, approve=True)
    assert any("would set the branch rules on main from .github/oto-rules.json" in d for d in report["done"]), report["done"]
    assert any("code owners" in d and "deploy key" in d and "oto-main" in d for d in report["done"]), \
        "the code owners and the key the two workflows push to main with come with the rules: " + str(report["done"])
    report = sandbox.up(name="fleet", directory=str(tmp_path / "fleet"), kind="ontology", repo="acme/fleet", token_env="FAKE_TOKEN", check=True, approve=True)
    assert not any("branch rules" in d for d in report["done"]), "a workspace has the pack's workflows, not a knowledge project's rules"


def test_the_sandbox_skill_sends_an_older_sandbox_tool_to_its_upgrade():
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "sandbox", "SKILL.md"), encoding="utf-8") as f:
        skill = f.read()
    assert "`sbx_supported` false" in skill and sandbox.MIN_SBX in skill
    assert "brew upgrade docker/tap/sbx" in skill and "winget upgrade" in skill


# ---- graphs read live from Neo4j (docs/plans/people-and-graphs.md, capability 3) ----

AURA = "neo4j+s://abc123.databases.neo4j.io"
LOGINS = {"NORTHWIND_NEO4J_USER": "north-user", "NORTHWIND_NEO4J_PASSWORD": "north-secret", "ACME_NEO4J_USER": "acme-user", "ACME_NEO4J_PASSWORD": "acme-secret"}


def _graphs(tmp_path, *names, uri=AURA):
    from oto import connections
    project = tmp_path / "box" / "project"
    for name in names:
        connections.add(str(project), name, uri)
    return str(tmp_path / "box")


def _logins(monkeypatch, **only):
    for key, value in (only or LOGINS).items():
        monkeypatch.setenv(key, value)


def test_up_passes_each_graphs_login_by_name_and_allows_its_host_for_that_sandbox(fake, tmp_path, monkeypatch):
    directory = _graphs(tmp_path, "northwind", "acme")
    _logins(monkeypatch)
    report = sandbox.up(name="box", directory=directory, approve=True, wait=5)
    create = fake.calls("create")[0]
    for variable in LOGINS:
        assert ["-e", variable] == create[create.index(variable) - 1:create.index(variable) + 1], "by name: the value stays out of the command line"
    called = json.dumps(fake.read()["calls"])
    for value in LOGINS.values():
        assert value not in called
        assert value not in json.dumps(report)
    assert fake.read()["sandboxes"]["box"]["env"]["ACME_NEO4J_PASSWORD"] == "acme-secret", "and it reaches the sandbox"
    assert fake.read()["rules"]["box"] == ["**.neo4j.io:7687"], "one rule for both, for this sandbox alone"
    assert [g["server"] for g in report["graphs"]] == ["acme-kg", "northwind-kg"]
    assert any("acme-kg" in line and "northwind-kg" in line for line in sandbox.next_steps(report))


def test_up_stops_before_making_a_sandbox_that_could_not_read_a_graph(fake, tmp_path, monkeypatch):
    directory = _graphs(tmp_path, "northwind", "acme")
    _logins(monkeypatch, NORTHWIND_NEO4J_USER="north-user", NORTHWIND_NEO4J_PASSWORD="north-secret")
    with pytest.raises(sandbox.SandboxError) as caught:
        sandbox.up(name="box", directory=directory, approve=True, wait=5)
    assert "ACME_NEO4J_USER" in str(caught.value) and "ACME_NEO4J_PASSWORD" in str(caught.value) and "NORTHWIND" not in str(caught.value)
    assert caught.value.fix, "it says what to do"
    assert not fake.calls("create")


def test_recreating_also_stops_first_when_a_login_is_missing(fake, tmp_path, monkeypatch):
    directory = _graphs(tmp_path, "northwind")
    _logins(monkeypatch, NORTHWIND_NEO4J_USER="north-user", NORTHWIND_NEO4J_PASSWORD="north-secret")
    sandbox.up(name="box", directory=directory, approve=True, wait=5)
    monkeypatch.delenv("NORTHWIND_NEO4J_PASSWORD")
    with pytest.raises(sandbox.SandboxError):
        sandbox.up(name="box", directory=directory, recreate=True, wait=5)
    assert "box" in fake.read()["sandboxes"], "the sandbox that worked is not removed for one that would not"


def test_check_says_what_would_pass_and_what_is_missing_and_changes_nothing(fake, tmp_path, monkeypatch):
    directory = _graphs(tmp_path, "northwind", "acme")
    _logins(monkeypatch, NORTHWIND_NEO4J_USER="north-user", NORTHWIND_NEO4J_PASSWORD="north-secret")
    report = sandbox.up(name="box", directory=directory, approve=True, check=True)
    said = " ".join(report["done"])
    assert "NORTHWIND_NEO4J_PASSWORD" in said and "**.neo4j.io:7687" in said
    assert any("ACME_NEO4J_PASSWORD" in w for w in report["warnings"])
    assert "north-secret" not in json.dumps(report)
    assert not fake.calls("create") and not fake.read().get("rules")


def test_up_again_keeps_one_rule_and_says_when_a_graph_added_later_has_no_login_inside(fake, tmp_path, monkeypatch):
    directory = _graphs(tmp_path, "northwind")
    _logins(monkeypatch, NORTHWIND_NEO4J_USER="north-user", NORTHWIND_NEO4J_PASSWORD="north-secret")
    sandbox.up(name="box", directory=directory, approve=True, wait=5)
    report = sandbox.up(name="box", directory=directory, wait=5)
    assert fake.read()["rules"]["box"] == ["**.neo4j.io:7687"] and not report["warnings"]
    _graphs(tmp_path, "acme")
    report = sandbox.up(name="box", directory=directory, wait=5)
    assert len(fake.calls("create")) == 1, "a sandbox in use is not replaced without being asked"
    assert any("ACME_NEO4J_PASSWORD" in w and "--recreate" in w for w in report["warnings"]), report["warnings"]
    assert not any("NORTHWIND" in w for w in report["warnings"])


def test_a_project_of_its_own_on_neo4j_passes_the_engines_names(fake, tmp_path, monkeypatch):
    project = tmp_path / "box" / "project"
    project.mkdir(parents=True)
    (project / "project.config.json").write_text(json.dumps({"slug": "p", "name": "P", "serve": {"backend": "neo4j"}, "neo4j": {"uri": "bolt://db.internal:7700"}}))
    monkeypatch.setenv("NEO4J_USER", "the-user")
    monkeypatch.setenv("NEO4J_PASSWORD", "the-secret")
    sandbox.up(name="box", directory=str(tmp_path / "box"), approve=True, wait=5)
    create = fake.calls("create")[0]
    assert "NEO4J_USER" in create and "NEO4J_PASSWORD" in create and "the-secret" not in create
    assert fake.read()["rules"]["box"] == ["db.internal:7700"]


def test_a_sandbox_with_no_graphs_is_made_as_before(fake, tmp_path):
    report = sandbox.up(name="box", directory=str(tmp_path / "box"), approve=True, wait=5)
    assert not fake.read().get("rules") and not report.get("graphs")
    assert not any("server of its own" in line for line in sandbox.next_steps(report))


# --- signed in to a portal (docs/plans/portal-sign-in.md, step 3) -------------------------------------------------

PORTAL = "https://portal.example"
PORTAL_TOKEN = "ghs_a-portal-token-that-never-reaches-a-file"


def _signed_in(tmp_path, monkeypatch, answers=None):
    """This computer signed in to a portal whose tenant is in the organisation Contoso, and what the portal is asked."""
    from oto import portal
    home = tmp_path / "oto-home"
    home.mkdir()
    monkeypatch.setenv("OTO_HOME", str(home))
    (home / "profile.json").write_text(json.dumps({"portal": PORTAL, "email": "ana@contoso.test", "organisation": "Contoso",
                                                   "tenant": {"id": "t", "name": "Contoso Trial"}, "registry": "Contoso/oto-registry"}))
    (home / "credentials.json").write_text(json.dumps({"portal": PORTAL, "session": "s" * 43}))
    asked = []

    def http(method, url, body=None, session=None):
        path = url[len(PORTAL + "/api/terminal/"):]
        asked.append((path, body))
        assert session == "s" * 43, "every request carries the session"
        if answers and path in answers:
            return answers[path](body)
        if path == "graphs":
            return 200, {"repository": "Contoso/%s" % body["name"], "store": "Contoso/%s-store" % body["name"], "organization": body.get("organization"),
                         "domain": body.get("domain"), "token": PORTAL_TOKEN, "expires_at": "2026-11-13T11:00:00Z", "warnings": []}
        if path == "graph-setup":
            return 200, {"repository": "Contoso/%s" % body["name"], "store": "Contoso/%s-store" % body["name"],
                         "done": ["main's deploy key is in the environment oto-main"], "warnings": []}
        if path == "github-token":
            return 200, {"token": PORTAL_TOKEN, "expires_at": "2026-11-13T11:00:00Z", "repository": body["repository"], "access": body["access"]}
        return 404, {}

    monkeypatch.setattr(portal, "_http", http)
    return asked


def _github_is(monkeypatch, owner_name, bare):
    """git reaches the bare repository on disk where it would reach github.com."""
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "url.%s.insteadOf" % bare)
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "https://github.com/%s.git" % owner_name)


def test_signed_in_the_portal_creates_the_graph_with_its_place_and_gives_the_token_for_the_first_push(fake, tmp_path, monkeypatch):
    import subprocess
    from oto import sandbox
    asked = _signed_in(tmp_path, monkeypatch)
    bare = _bare(tmp_path, "motor-claims.git")
    _github_is(monkeypatch, "Contoso/motor-claims", bare)
    report = sandbox.up(name="motor-claims", directory=str(tmp_path / "mc"), kind="knowledge", organization="Finance", domain="Claims", approve=True)
    assert asked == [("graphs", {"name": "motor-claims", "organization": "Finance", "domain": "Claims"}),
                     ("graph-setup", {"name": "motor-claims"})], "the portal makes the graph before anything is laid out, and sets up its deploys once main is pushed"
    assert any("set up the repository: main's deploy key" in d for d in report["done"])
    assert not any("deploy key" in w for w in report["warnings"]), "what the portal did is not said to be missing"
    assert report["repository"] == "https://github.com/Contoso/motor-claims.git" and report["commit"]
    assert report["store"] == "https://github.com/Contoso/motor-claims-store"
    author = subprocess.run(["git", "-C", bare, "log", "-1", "--format=%ae", "main"], capture_output=True, text=True).stdout.strip()
    assert author == "ana@contoso.test", "the first commit names the person, not the App"
    project = str(tmp_path / "mc" / "project")
    with open(os.path.join(project, ".github", "oto-access.json"), encoding="utf-8") as f:
        access = json.load(f)
    assert access.get("store") == "Contoso/motor-claims-store" and not access.get("stewards"), "the store is named; no GitHub login is"
    secret = [c for c in fake.calls("secret") if c[:2] == ["secret", "set"]]
    assert secret and PORTAL_TOKEN in secret[0], "the portal's token is the sandbox's GitHub secret"
    assert any("Finance / Claims" in d for d in report["done"]) and any("one hour" in d for d in report["done"])
    assert not any("branch rules" in w for w in report["warnings"]), "the rules are the portal's to set and to report"
    owners = subprocess.run(["git", "-C", bare, "show", "main:.github/CODEOWNERS"], capture_output=True, text=True).stdout
    assert "@Contoso/oto-owners" in owners and "/.github/" in owners, "the first commit names the organisation's team code owner, so the rules can ask for it"
    assert any("@Contoso/oto-owners" in d for d in report["done"])
    for root, _dirs, files in os.walk(str(tmp_path)):
        for name in files:
            if name == "sbx.json":          # the fake sandbox tool's own record of its calls
                continue
            with open(os.path.join(root, name), "rb") as f:
                assert PORTAL_TOKEN.encode() not in f.read(), "the token is in no file: %s" % os.path.join(root, name)

    # again, later: the folder is already that repository's, so the portal is asked for a new token and nothing else
    del asked[:]
    again = sandbox.up(name="motor-claims", directory=str(tmp_path / "mc"), kind="knowledge", approve=True)
    assert asked == [("github-token", {"repository": "Contoso/motor-claims", "access": "write"}), ("graph-setup", {"name": "motor-claims"})]
    assert any("new one-hour token" in d for d in again["done"])


def test_signed_in_a_portal_that_cannot_set_up_the_deploys_is_a_warning_and_the_graph_is_still_made(fake, tmp_path, monkeypatch):
    from oto import sandbox
    _signed_in(tmp_path, monkeypatch, {"graph-setup": lambda body: (502, {"error": "the App needs the repository permissions Administration and Environments"})})
    _github_is(monkeypatch, "Contoso/motor-claims", _bare(tmp_path, "motor-claims.git"))
    report = sandbox.up(name="motor-claims", directory=str(tmp_path / "mc"), kind="knowledge", approve=True)
    assert report["commit"], "the first commit is pushed all the same"
    said = [w for w in report["warnings"] if "didn't set up the deploys" in w]
    assert said and "Environments" in said[0] and "again" in said[0] and "branch rules" in said[0]


def test_signed_in_a_refusal_from_the_portal_stops_before_anything_is_laid_out(fake, tmp_path, monkeypatch):
    from oto import sandbox
    _signed_in(tmp_path, monkeypatch, {"graphs": lambda body: (403, {"error": "Creating a graph in Finance takes the Graph steward role there."})})
    with pytest.raises(sandbox.SandboxError) as refused:
        sandbox.up(name="motor-claims", directory=str(tmp_path / "mc"), kind="knowledge", organization="Finance", approve=True)
    assert "Graph steward" in str(refused.value)
    assert not os.path.exists(str(tmp_path / "mc" / "project" / "project.config.json")) and not fake.calls("create")


def test_signed_in_check_asks_the_portal_nothing_and_a_token_variable_still_wins(fake, tmp_path, monkeypatch):
    from oto import sandbox
    asked = _signed_in(tmp_path, monkeypatch)
    report = sandbox.up(name="motor-claims", directory=str(tmp_path / "mc"), kind="knowledge", organization="Finance", check=True, approve=True)
    assert asked == [] and any("would ask the portal" in d and "Contoso/motor-claims" in d and "Finance" in d for d in report["done"])
    with pytest.raises(sandbox.SandboxError) as refused:       # another repository's name: the portal names it after the sandbox
        sandbox.up(name="motor-claims", directory=str(tmp_path / "mc"), kind="knowledge", repo="Contoso/other", approve=True)
    assert "Contoso/motor-claims" in str(refused.value)
    bare = _bare(tmp_path)
    monkeypatch.setenv("FAKE_TOKEN", "mine")
    sandbox.up(name="own", directory=str(tmp_path / "own"), kind="knowledge", repo=bare, token_env="FAKE_TOKEN", approve=True)
    assert asked == [], "with a token variable named, the portal is not asked"


def test_a_place_is_only_for_a_graph_the_portal_makes(fake, tmp_path):
    from oto import sandbox
    with pytest.raises(sandbox.SandboxError) as refused:
        sandbox.up(name="x", directory=str(tmp_path / "x"), kind="knowledge", no_repo=True, organization="Finance")
    assert "oto login" in refused.value.fix


def test_signed_in_a_clone_of_the_tenants_repository_uses_the_portals_token_to_write_or_else_to_read(fake, tmp_path, monkeypatch):
    import subprocess
    from oto import sandbox
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    (work / "project.config.json").write_text("{}")
    subprocess.run(["git", "-C", str(work), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(work), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "one"], check=True)
    bare = str(tmp_path / "claims.git")
    subprocess.run(["git", "clone", "-q", "--bare", str(work), bare], check=True)
    _github_is(monkeypatch, "Contoso/claims", bare)

    def token(body):
        if body["access"] == "write":
            return 403, {"error": "Adding to this graph takes the Graph steward or Contributor role on its place."}
        return 200, {"token": PORTAL_TOKEN, "repository": body["repository"], "access": "read"}

    asked = _signed_in(tmp_path, monkeypatch, {"github-token": token})
    report = sandbox.up(name="claims", directory=str(tmp_path / "claims"), clone="Contoso/claims", approve=True)
    assert [body["access"] for _path, body in asked] == ["write", "read"]
    assert os.path.exists(str(tmp_path / "claims" / "project" / "project.config.json"))
    assert any("to read Contoso/claims" in d for d in report["done"])
    assert [c for c in fake.calls("secret") if c[:2] == ["secret", "set"] and PORTAL_TOKEN in c]

    del asked[:]                                    # a repository outside the tenant's organisation: the portal is not asked
    other = _bare(tmp_path, "other.git")
    sandbox.up(name="elsewhere", directory=str(tmp_path / "elsewhere"), clone=other, approve=True)
    assert asked == []


def test_signed_in_a_clone_the_portal_refuses_says_why(fake, tmp_path, monkeypatch):
    from oto import sandbox
    _signed_in(tmp_path, monkeypatch, {"github-token": lambda body: (403, {"error": "You have no role on this graph's place."})})
    with pytest.raises(sandbox.SandboxError) as refused:
        sandbox.up(name="claims", directory=str(tmp_path / "claims"), clone="Contoso/claims", approve=True)
    assert "no role" in str(refused.value) and not fake.calls("create")


def test_the_portal_module_asks_for_a_graph_with_only_what_was_given(tmp_path, monkeypatch):
    from oto import portal
    asked = _signed_in(tmp_path, monkeypatch)
    made = portal.create_graph("loose")
    assert asked == [("graphs", {"name": "loose"})] and made["repository"] == "Contoso/loose"
    assert portal.signed_in()["organisation"] == "Contoso"
    os.remove(str(tmp_path / "oto-home" / "credentials.json"))
    assert portal.signed_in() is None
    with pytest.raises(portal.PortalError) as refused:
        portal.create_graph("loose")
    assert "oto login" in refused.value.fix
