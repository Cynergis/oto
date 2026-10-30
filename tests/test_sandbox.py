"""`oto sandbox`: everything a person would type to get OTO's kit running in a Docker sandbox, against a
fake `sbx` and `ssh` that keep their state in a JSON file. The person's approval of the kit's use of
their Anthropic sign-in is written only when they gave it, and only next to what is already there."""
import json
import os
import stat
import sys

import pytest

from oto import __version__, sandbox
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
    out = "sbx version v0.48.0 5caf923e\n"
elif not state["signed_in"] and args[:1] in (["ls"], ["create"]):
    err, code = "error: not signed in to Docker\ntry: sbx login\n", 1
elif args == ["ls", "--json"]:
    out = json.dumps([{"name": name, "id": "x", "agent": box["agent"], "status": "running" if box["running"] else "stopped",
                       "workspaces": box["folders"], "created_at": box.get("created_at", "2026-10-01T10:00:00Z"),
                       "last_used_at": box.get("last_used_at")} for name, box in state["sandboxes"].items()])
elif args[:1] == ["ls"]:
    out = "SANDBOX   AGENT   STATUS   PORTS   WORKSPACE   CREATED\n"
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
            k, v = rest.pop(0).split("=", 1)
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
    elif command[:2] == ["sh", "-c"] and "lock-plugins\" --names" in command[2]:
        box["given"] = box.get("given", []) + command[4:]
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
