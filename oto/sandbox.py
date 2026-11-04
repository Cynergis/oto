# -*- coding: utf-8 -*-
"""An OTO sandbox: Claude Code with OTO inside a Docker sandbox, made from OTO's kit, ready to be
driven from Claude Desktop's Code tab over SSH or from a terminal.

Docker Sandboxes (the `sbx` CLI) runs each sandbox as a small virtual machine. The kit
(`kits/oto-gcp`, published as ghcr.io/cynergis/oto-gcp:<engine version>) says what the sandbox
holds and may reach, and sets OTO up inside it: a schema-3 kit set on Docker's Claude Code kit,
which `sbx` runs from 0.51 on (`MIN_SBX`). `up` does everything a person would otherwise type:

- checks that `sbx` is installed, recent enough and signed in, with a network policy;
- lets `sbx` run kits from OTO's registry (`kit.allowedSources`);
- records the person's approval for the kit to use their Anthropic sign-in, a binding in
  `credentials.yaml`. `sbx` asks for it only at a terminal; started from a tool, a kit's sandbox
  gets no credential without it, and Claude Code then asks to sign in at every message. The binding
  is written only when the caller says the person agreed (`approve_anthropic`), never on its own;
- creates the project and code folders and the sandbox, with the Google Cloud project's id as
  `PROJECT`, and waits until OTO is ready inside it;
- sets up SSH, so `<name>.sbx` reaches the sandbox (Claude Desktop's Code tab, VS Code, a terminal);
- passes the login of each graph in the folder (oto/connections.py) from this environment by name, and
  allows each graph's host for this sandbox alone, so the graph answers live from Neo4j.

Inside, only the plugins installed in the sandbox load: the kit's `lock-plugins` switches off what
Claude Desktop brings from the person's computer and what their claude.ai account brings, at every
start and every session start. `up` also passes it the plugins Claude Desktop would bring from this
computer (`desktop_plugins`), so the first session starts without them too. `allow_outside`
(`--allow-outside-plugins`) creates a sandbox that keeps them. `status` reads where the lock stands
(`plugin_lock`), never changes it.

What only the person can do is said, never guessed: installing `sbx`, signing in to Docker, and
adding the SSH connection in Claude Desktop. Everything is read from `sbx` itself; nothing in a
sandbox is touched but through `sbx exec`.
"""
import glob
import contextlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import datetime
import time

from . import __version__
from . import connections as _connections
from . import repo as _repo

KIT_REPO = "ghcr.io/cynergis/oto-gcp"
KIT_SOURCE = "ghcr.io/cynergis/"
#: the first sbx that runs the kit: 0.51 made `claude` Docker's schema-3 kit, which the kit is built on
MIN_SBX = "0.51.0"
SBX_UPGRADE = ("on a Mac: brew upgrade docker/tap/sbx; on Windows: winget upgrade Docker.sbx; on Linux: "
               "sudo apt-get install --only-upgrade docker-sbx; then run again")
DEFAULT_NAME = "oto-sandbox"
#: what `sbx` records when a person approves the kit's use of their Anthropic sign-in at a terminal
ANTHROPIC_BINDING = {"apiKey": ["api.anthropic.com", "claude.ai", "console.anthropic.com", "mcp-proxy.anthropic.com"],
                     "oauth": ["platform.claude.com"]}
POLICIES = ("balanced", "deny-all", "allow-all")
READY = "OTO ready"
#: how the kit's start ends when the engine did not install: `up` stops waiting on it too
FAILED = "OTO failed"
#: the kit's switch for the plugin lock: `allowed` keeps outside plugins, anything else blocks them
OUTSIDE = "OTO_OUTSIDE_PLUGINS"
PROJECT_DIR_ENV = "OTO_PROJECT_DIR"   # the project folder's path inside the sandbox, for the kit's landing hook
CODE_DIR_ENV = "OTO_CODE_DIR"
#: set by the kit's environment (kits/oto-gcp/oto-gcp.yaml): the engine runs inside an OTO sandbox
INSIDE_ENV = "OTO_SANDBOX"
#: the ports `oto sandbox up` publishes to the computer's loopback: the explorer, and a second view
DEFAULT_PORTS = (8798, 8799)


def inside_kit(environ=None, home=None):
    """True inside a sandbox made from OTO's kit: the kit's environment says so (OTO_SANDBOX), or its
    files are in the home folder (init.sh and lock-plugins under ~/.oto). What this changes: `oto serve`
    binds all interfaces by default and needs no token, since the sandbox tool publishes a port to the
    computer's loopback only, and a server on the sandbox's loopback is unreachable from the computer."""
    env = environ if environ is not None else os.environ
    if (env.get(INSIDE_ENV) or "").strip():
        return True
    base = os.path.join(home or os.path.expanduser("~"), ".oto")
    return os.path.isfile(os.path.join(base, "init.sh")) and os.path.isfile(os.path.join(base, "lock-plugins"))

#: Run inside the sandbox by `plugin_lock`: reads what the kit's lock-plugins writes, changes nothing.
#: Read on its own, so it also answers for a sandbox made before the kit carried the lock.
LOCK_CHECK = r"""
import glob, json, os
home = os.path.expanduser("~")
out = {"mode": "allowed" if os.environ.get("OTO_OUTSIDE_PLUGINS", "").strip().lower() == "allowed" else "blocked",
       "script": os.path.isfile(os.path.join(home, ".oto", "lock-plugins")), "settings": "ok"}
try:
    with open(os.path.join(home, ".claude", "settings.json"), encoding="utf-8") as f:
        settings = json.load(f)
except FileNotFoundError:
    settings, out["settings"] = {}, "missing"
except (OSError, ValueError):
    settings, out["settings"] = {}, "unreadable"
if not isinstance(settings, dict):
    settings, out["settings"] = {}, "unreadable"
enabled = settings.get("enabledPlugins") if isinstance(settings.get("enabledPlugins"), dict) else {}
names = []
for folder in sorted(glob.glob(os.path.join(home, ".claude", "remote", "plugins", "*", "*"))):
    if not os.path.isdir(folder):
        continue
    try:
        with open(os.path.join(folder, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            name = json.load(f).get("name")
    except (OSError, ValueError, AttributeError):
        name = None
    name = name.strip() if isinstance(name, str) and name.strip() else os.path.basename(folder)
    if name not in names:
        names.append(name)
hooks = settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {}
out.update(forwarded=names, switched_off=sorted(k[:-len("@inline")] for k, v in enabled.items() if k.endswith("@inline") and v is False), loading=[n for n in names if enabled.get(n + "@inline") is not False],
           account_plugins_off=settings.get("syncClaudeAiPlugins") is False,
           account_skills_off=settings.get("syncClaudeAiSkills") is False,
           connectors_off=settings.get("disableClaudeAiConnectors") is True,
           hook=".oto/lock-plugins" in json.dumps(hooks.get("SessionStart", [])))
out["locked"] = not out["loading"] and out["account_plugins_off"] and out["account_skills_off"] and out["connectors_off"]
print(json.dumps(out))
"""


class SandboxError(Exception):
    """A step that cannot go on; `fix` says what the person does about it."""

    def __init__(self, message, fix=""):
        super().__init__(message)
        self.fix = fix


def kit_ref(version=None):
    """The kit published for this engine: its tag is the engine's version."""
    return "%s:%s" % (KIT_REPO, version or __version__)


def _kit_name(kit):
    """The name `sbx ls` shows for a sandbox made from this kit, the last part of its reference or of a
    local kit's folder: ghcr.io/cynergis/oto-gcp:0.11.30 -> oto-gcp, kits/oto-gcp -> oto-gcp."""
    last = re.split(r"[\\/]", kit.rstrip("/\\"))[-1]
    return re.sub(r"\.(zip|git)$", "", last.split("@")[0].split(":")[0])


def credentials_path():
    """Where `sbx` keeps its approvals: %APPDATA%\\sbx on Windows, ~/.config/sbx elsewhere."""
    if os.name == "nt" and os.environ.get("APPDATA"):
        return os.path.join(os.environ["APPDATA"], "sbx", "credentials.yaml")
    return os.path.join(os.path.expanduser("~"), ".config", "sbx", "credentials.yaml")


def _tool(env, name):
    path = os.environ.get(env) or shutil.which(name)
    return path if path and os.path.exists(path) else None


def _run(argv, timeout=120, env=None):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return 124, "", "timed out after %ds" % timeout
    return done.returncode, done.stdout, done.stderr


class Sbx(object):
    """The `sbx` CLI, found on the PATH (or OTO_SBX)."""

    def __init__(self):
        self.path = _tool("OTO_SBX", "sbx")

    def __call__(self, *args, **kw):
        return _run([self.path] + list(args), **kw)


# ---- what is there ----

def _version(sbx):
    code, out, err = sbx("version")
    match = re.search(r"v?(\d+\.\d+\.\d+)", out)
    return match.group(1) if code == 0 and match else None


def supported(version):
    """Whether this sbx runs the kit: True from MIN_SBX on, False before, None when the version is unknown."""
    if not version or not re.match(r"^\d+\.\d+\.\d+$", version):
        return None
    return tuple(int(x) for x in version.split(".")) >= tuple(int(x) for x in MIN_SBX.split("."))


def _signed_in(sbx):
    code, out, err = sbx("ls")
    return code == 0 and "not signed in" not in (out + err).lower()


def _policy_set(sbx):
    code, out, err = sbx("policy", "ls")
    return code == 0 and "not been initialized" not in (out + err)


def _allowed_sources(sbx):
    code, out, err = sbx("settings", "get", "kit.allowedSources")
    try:
        value = json.loads(out.strip()) if code == 0 else None
    except ValueError:
        value = None
    return value if isinstance(value, list) else ["docker.io/"]


def _source_allowed(sources, ref):
    """Whether `sbx` runs this kit: a local folder or zip always, a registry's only when allowed."""
    return os.path.exists(os.path.expanduser(ref)) or any(ref.startswith(prefix) for prefix in sources)


def _anthropic_secret(sbx):
    """Whether sbx holds an Anthropic sign-in or key for sandboxes (`sbx secret ls` names it, never shows it)."""
    code, out, err = sbx("secret", "ls", "--json")
    try:
        secrets = json.loads(out).get("secrets") or [] if code == 0 else []
    except (ValueError, AttributeError):
        secrets = []
    return any(isinstance(x, dict) and x.get("name") == "anthropic" and x.get("type") == "service" for x in secrets)


def anthropic_bound(path=None):
    """Whether the person has approved a kit's use of their Anthropic sign-in (any mechanism)."""
    path = path or credentials_path()
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return False
    block = re.search(r"^bindings:\s*\n((?:[ \t]+.*\n?|\s*\n)*)", text, re.M)
    if not block:
        return False
    entry = re.search(r"^([ \t]+)anthropic:\s*\n((?:\1[ \t]+.*\n?)*)", block.group(1), re.M)
    return bool(entry and re.search(r"\b(apiKey|oauth):", entry.group(2)))


def _sandboxes(sbx):
    """The local sandboxes, by name: their status (running or stopped), agent or kit, and folders."""
    code, out, err = sbx("ls", "--json")
    try:
        listed = json.loads(out) if code == 0 else []
    except ValueError:
        listed = []
    return {box["name"]: {"status": "running" if box.get("status") == "running" else "stopped",
                          "agent": box.get("agent") or "", "folders": list(box.get("workspaces") or []),
                          "created_at": box.get("created_at"), "last_used_at": box.get("last_used_at")}
            for box in listed if isinstance(box, dict) and box.get("name")}


def _days_since(stamp):
    """Whole days since an ISO timestamp `sbx ls` prints, or None when it prints none."""
    if not stamp:
        return None
    try:
        then = datetime.datetime.strptime(str(stamp)[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return max(0, (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - then).days)


def desktop_ssh_connections():
    """The SSH connections Claude Desktop has saved, by the host each reaches (`<name>.sbx` for a
    sandbox), read from the app's own file where it exists (macOS); [] elsewhere. Read only: the app
    owns the file, and a connection is removed in its SSH environment menu, never here."""
    path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Claude", "ssh_configs.json")
    try:
        with open(path, encoding="utf-8") as f:
            configs = (json.load(f) or {}).get("configs") or []
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    for entry in configs:
        if isinstance(entry, dict) and isinstance(entry.get("sshHost"), str):
            out.append({"name": entry.get("name") or entry["sshHost"], "host": entry["sshHost"]})
    return out


def list_sandboxes():
    """Every sandbox on this computer, for `oto sandbox ls`: {sandboxes: [...], connections: [...]}.
    A sandbox carries its status, the kit it was made from (and whether that is OTO's), its folders
    with whether each still exists, when it was created and last used, how many days idle, and
    whether SSH reaches it. A saved Desktop connection to a `.sbx` host carries whether a sandbox of
    that name still exists: one without is stale, and only the person can remove it (§ the skill)."""
    sbx = Sbx()
    out = {"sbx": None, "signed_in": False, "sandboxes": [], "connections": []}
    if not sbx.path:
        return out
    out["sbx"] = _version(sbx) or "unknown"
    out["signed_in"] = _signed_in(sbx)
    if not out["signed_in"]:
        return out
    kit = _kit_name(kit_ref())
    boxes = _sandboxes(sbx)
    for name in sorted(boxes):
        box = boxes[name]
        out["sandboxes"].append({
            "name": name, "status": box["status"], "made_from": box["agent"], "from_kit": box["agent"] == kit,
            "folders": [{"path": f, "exists": os.path.isdir(f)} for f in box["folders"]],
            "created_at": box.get("created_at"), "last_used_at": box.get("last_used_at"),
            "idle_days": _days_since(box.get("last_used_at")), "ssh": _ssh_ready(name)})
    for conn in desktop_ssh_connections():
        host = conn["host"]
        if host.endswith(".sbx"):
            out["connections"].append({"name": conn["name"], "host": host, "sandbox": host[:-4], "exists": host[:-4] in boxes})
    return out


def remove_sandboxes(names, stop_only=False):
    """Stop (`stop_only`) or remove sandboxes by name, for `oto sandbox stop` and `rm`: {done, missing,
    failed}. Removal is `sbx rm -f`: the containers, the state and the sandbox's own secrets go; the
    project and code folders on this computer stay. Nothing is removed that `sbx ls` does not list."""
    sbx = Sbx()
    if not sbx.path:
        raise SandboxError("sbx is not installed", fix="install Docker Sandboxes first (oto sandbox status says how)")
    have = _sandboxes(sbx)
    out = {"done": [], "missing": [], "failed": []}
    for name in names:
        if name not in have:
            out["missing"].append(name)
            continue
        code, _o, err = sbx("stop", name) if stop_only else sbx("rm", "-f", name)
        if code == 0:
            out["done"].append(name)
        else:
            out["failed"].append({"name": name, "error": (err or _o).strip().splitlines()[-1] if (err or _o).strip() else "sbx failed"})
    return out


def published_ports(sbx, name):
    """The sandbox ports published to this computer, from `sbx ports <name> --json`: [{port, host_port, host}]."""
    code, out, err = sbx("ports", name, "--json")
    try:
        listed = json.loads(out) if code == 0 else []
    except ValueError:
        listed = []
    return [{"port": int(e["sandbox_port"]), "host_port": int(e["host_port"]), "host": e.get("host_ip") or "127.0.0.1"}
            for e in listed if isinstance(e, dict) and e.get("sandbox_port") is not None]


def host_ports_taken(sbx, except_name=None):
    """The computer's ports other sandboxes publish, by the sandbox holding each: {host_port: name}. A
    stopped sandbox keeps its mapping and takes the port back when it starts, so it counts too."""
    taken = {}
    for other in _sandboxes(sbx):
        if other == except_name:
            continue
        for entry in published_ports(sbx, other):
            taken.setdefault(entry["host_port"], other)
    return taken


def _bindable(port):
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def free_host_port(port, taken, span=100):
    """`port` itself when nothing on this computer holds it, else the first free port above it: every
    sandbox serves on the same ports inside, and the computer's side cannot hold one twice. `taken`
    is what other sandboxes publish (and what this call already chose); a port something else listens
    on is skipped as well."""
    for candidate in range(port, port + span):
        if candidate not in taken and _bindable(candidate):
            return candidate
    raise SandboxError("no free port on this computer between %d and %d" % (port, port + span - 1),
                       "stop a sandbox (oto sandbox stop <name>), or pass --publish with ports that are free")


def _host_mapping(sbx, name, ports):
    """[(host_port, sandbox_port)] for the ports to publish, each on a free host port, and the words
    for what moved: {sandbox_port: holder}."""
    taken = host_ports_taken(sbx, except_name=name)
    chosen, moved = [], {}
    for port in ports:
        host = free_host_port(port, set(taken) | {h for h, _p in chosen})
        chosen.append((host, port))
        if host != port:
            moved[port] = taken.get(port) or "something else on this computer"
    return chosen, moved


def _published_words(mapping, moved):
    """'published ports 8798 and 8799 to this computer's localhost', or which host port each took and why."""
    if not moved:
        return "published port%s %s to this computer's localhost" % ("" if len(mapping) == 1 else "s", " and ".join(str(p) for _h, p in mapping))
    pairs = " and ".join("%d as localhost:%d" % (p, h) if h != p else "%d" % p for h, p in mapping)
    holders = {}
    for port, holder in moved.items():
        holders.setdefault(holder, []).append(port)
    why = "; ".join("%s %s taken by %s" % (" and ".join(str(p) for p in ports), "is" if len(ports) == 1 else "are",
                                          holder if holder.startswith("something") else "the sandbox %s" % holder)
                    for holder, ports in holders.items())
    return "published port %s (%s)" % (pairs, why)


def _ssh_ready(name):
    ssh = _tool("OTO_SSH", "ssh")
    if not ssh:
        return False
    code, out, err = _run([ssh, "-G", "%s.sbx" % name], timeout=30)
    return code == 0 and bool(re.search(r"^proxycommand .*sbx", out, re.M | re.I))


def status(name=DEFAULT_NAME):
    """Where things stand, without changing anything."""
    sbx = Sbx()
    out = {"name": name, "kit": kit_ref(), "credentials": credentials_path(), "sbx": None, "sbx_supported": None, "signed_in": False,
           "policy": False, "kit_allowed": False, "anthropic_approved": anthropic_bound(), "anthropic_signed_in": False,
           "sandbox": None, "made_from": None, "from_kit": False, "folders": [], "oto": None, "outside_plugins": None, "outside_plugins_summary": None,
           "ssh": False, "ports": []}
    if not sbx.path:
        return out
    out["sbx"] = _version(sbx) or "unknown"
    out["sbx_supported"] = supported(out["sbx"])
    out["signed_in"] = _signed_in(sbx)
    if not out["signed_in"]:
        return out
    out["policy"] = _policy_set(sbx)
    out["kit_allowed"] = _source_allowed(_allowed_sources(sbx), out["kit"])
    out["anthropic_signed_in"] = _anthropic_secret(sbx)
    found = _sandboxes(sbx).get(name)
    if found:
        out["sandbox"], out["folders"], out["made_from"] = found["status"], found["folders"], found["agent"]
        out["ports"] = published_ports(sbx, name)
        out["from_kit"] = found["agent"] == _kit_name(out["kit"])
        if found["status"] == "running":     # `sbx exec` would start a stopped one
            out["oto"] = _oto_line(sbx, name, wait=0)
            out["outside_plugins"] = plugin_lock(sbx, name)
            out["outside_plugins_summary"] = describe_lock(out["outside_plugins"], coming(out["outside_plugins"]))
        out["ssh"] = _ssh_ready(name)
    return out


def _oto_line(sbx, name, wait=600):
    """The last line of the kit's start log, waiting up to `wait` seconds for the start to end, ready or failed."""
    rounds = max(1, int(wait) // 5)
    script = ('for i in $(seq 1 %d); do grep -q -e "%s" -e "%s" /tmp/oto-init.log 2>/dev/null && break; sleep 5; done; '
              'tail -1 /tmp/oto-init.log 2>/dev/null' % (rounds, READY, FAILED)) if wait else "tail -1 /tmp/oto-init.log 2>/dev/null"
    code, out, err = sbx("exec", name, "--", "sh", "-c", script, timeout=wait + 120)
    lines = [l for l in out.splitlines() if l.strip()]
    return lines[-1].strip() if lines else None


# ---- what `up` changes ----

def approve_anthropic(path=None):
    """Record the approval `sbx` would record at a terminal. Keeps every other binding; does nothing
    when an Anthropic binding is already there. Returns True when it wrote."""
    path = path or credentials_path()
    if anthropic_bound(path):
        return False
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        text = ""
    unit = "    "
    found = re.search(r"^bindings:\s*\n([ \t]+)\S", text, re.M)
    if found:
        unit = found.group(1)
    lines = [unit + "anthropic:"]
    for mechanism in ("apiKey", "oauth"):
        lines += [unit * 2 + mechanism + ":", unit * 3 + "domains:"]
        lines += [unit * 4 + "- " + domain for domain in ANTHROPIC_BINDING[mechanism]]
    entry = "\n".join(lines) + "\n"
    text = re.sub(r"^bindings:[ \t]*\{[ \t]*\}[ \t]*$", "bindings:", text, flags=re.M)
    if re.search(r"^bindings:\s*$", text, re.M):
        text = re.sub(r"^bindings:\s*\n", lambda m: "bindings:\n" + entry, text, count=1, flags=re.M)
    else:
        text = (text.rstrip("\n") + "\n" if text.strip() else "") + "bindings:\n" + entry
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return True


def desktop_plugins():
    """The plugins Claude Desktop on this computer hands to an SSH session, each loading there as
    <name>@inline: the claude.ai account's plugins it keeps in ~/.claude/plugins/synced, and its bundle
    of the account's skills. These are Desktop's own folders, which it does not document: what is
    missed here, the kit's session-start check still switches off, one session late."""
    home = os.path.expanduser("~")
    apps = [os.path.join(home, "Library", "Application Support", "Claude"), os.path.join(home, ".config", "Claude")]
    if os.environ.get("APPDATA"):
        apps.append(os.path.join(os.environ["APPDATA"], "Claude"))
    patterns = [os.path.join(home, ".claude", "plugins", "synced", "*", "*")]
    patterns += [os.path.join(app, "local-agent-mode-sessions", "skills-plugin", "*", "*") for app in apps]
    names = []
    for pattern in patterns:
        for folder in sorted(glob.glob(pattern)):
            if not os.path.isdir(folder):
                continue
            try:
                with open(os.path.join(folder, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
                    name = json.load(f).get("name")
            except (OSError, ValueError, AttributeError):
                name = None
            if not isinstance(name, str) or not name.strip():
                name = re.sub(r"~g\d+$", "", os.path.basename(folder))   # synced copies are suffixed ~g2, ~g3
            if name.strip() not in names:
                names.append(name.strip())
    return names


def plugin_lock(sbx, name):
    """Where the plugin lock stands in a running sandbox, read through `sbx exec`; None when it cannot be read."""
    code, out, err = sbx("exec", name, "--", "python3", "-c", LOCK_CHECK, timeout=60)
    try:
        found = json.loads(out.strip().splitlines()[-1]) if code == 0 and out.strip() else None
    except ValueError:
        found = None
    return found if isinstance(found, dict) else None


def coming(lock, names=None):
    """Plugins on this computer that Desktop would hand to the next session and the lock has not
    switched off yet: they would load once, in that session."""
    if not lock or lock.get("mode") != "blocked":
        return []
    names = desktop_plugins() if names is None else names
    return [n for n in names if n not in lock.get("switched_off", []) and n not in lock.get("loading", [])]


def describe_lock(lock, next_session=()):
    """The plugin lock in a sentence, for a person."""
    if not lock:
        return "unknown: the sandbox could not be read"
    if lock["mode"] == "allowed":
        return "allowed, by choice: plugins from your computer and your claude.ai account load in the sandbox too"
    if not lock["locked"]:
        loading = list(lock["loading"]) + list(next_session)
        loading += [what for off, what in ((lock["account_plugins_off"], "your claude.ai plugins"),
                                           (lock["account_skills_off"], "your claude.ai skills"),
                                           (lock["connectors_off"], "your claude.ai connectors")) if not off]
        said = "NOT blocked: %s would load in a new session" % ", ".join(loading)
        if not lock["script"]:
            said += "; the sandbox was made from a kit without the plugin lock: make it again from the current kit to lock it"
        return said
    if next_session:
        return "blocked, but %s from this computer would load once in the next session: oto sandbox up switches %s " \
               "off now" % (", ".join(next_session), "it" if len(next_session) == 1 else "them")
    count = len(lock.get("switched_off", []))
    done = ("only the sandbox's own plugins load (%d from your computer switched off)" % count if count else
            "only the sandbox's own plugins load")
    if not lock["hook"]:
        return "blocked, but without the check at each session start: a plugin your computer adds later would load once " \
               "a session starts with it; " + done
    return "blocked: " + done


KINDS = ("knowledge", "ontology")
GITHUB = "https://github.com/"


def _github_url(repo):
    """`owner/name` -> its https URL; a URL or a path stays as given."""
    if repo and "://" not in repo and not os.path.exists(os.path.expanduser(repo)) and repo.count("/") == 1 and not repo.startswith("."):
        return GITHUB + repo + ".git"
    return repo


def _git(cwd, *args, env=None, timeout=300):
    code, out, err = _run(["git", "-C", cwd] + list(args), timeout=timeout, env=env)
    if code != 0:
        raise SandboxError("git %s failed in %s: %s" % (args[0], cwd, (err or out).strip()[-400:]), "")
    return out


def layout(kind, project_dir, name, pack=None, maintainer=None, repo=False):
    """Lay the project out in the sandbox's project folder, on this computer, before the sandbox is made:
    a knowledge project (on a pack when one is named, with the repository workflows when it is backed by
    one), or an ontology workspace, a pack in the making (docs/plans/ontology-workspace.md). Returns what
    was laid out, in words; nothing when the folder already holds a project."""
    if os.path.exists(os.path.join(project_dir, "project.config.json")) or os.path.exists(os.path.join(project_dir, "manifest.json")):
        return None
    if kind == "ontology":
        from .model import packs as _packs
        with contextlib.redirect_stdout(io.StringIO()):
            _packs.new(name, into=project_dir, maintainer=maintainer or "")
        return "laid out an ontology workspace for the pack %s in %s: a starter vocabulary to fill, a trial project, the check and publish workflows" % (name, project_dir)
    from . import scaffold as _scaffold
    from .model import lock as _lock
    with contextlib.redirect_stdout(io.StringIO()):
        _scaffold.init(project_dir, slug=name, name=name.replace("-", " ").title(), pack=pack, repo=repo)
    _lock.own(project_dir)                  # the sandbox's plugins, not this computer's
    return "laid out a knowledge project in %s%s%s" % (project_dir, (" on the pack %s" % pack) if pack else "",
                                                     ", with the repository workflows" if repo else "")


def declared_plugins(project_dir):
    """The pack plugins the project declares in its .claude/settings.json (`oto init --pack` writes them),
    the engine plugin left out: the kit installs that one, and the sandbox's lock keeps the sandbox to
    the plugins installed inside it, so these are installed inside by `up`, at project scope."""
    from .model import lock as _lock
    return [key for key in (_lock.declared(project_dir) or []) if key.split("@", 1)[0] != _lock.ENGINE_PLUGIN]


INSTALL_PLUGINS = 'cd "$1" || exit 1; shift; for p in "$@"; do claude plugin install "$p" --scope project || exit 1; done'


def _plugins_words(ids):
    return "the plugin%s %s the project declares, at project scope" % ("" if len(ids) == 1 else "s", ", ".join(ids))


def github_repository(repo, token, check=False, gh=None):
    """Create the GitHub repository `owner/name` (private) with the GitHub CLI and the token, unless it
    exists. Returns its https URL. A URL or a path is taken as a repository that exists."""
    url = _github_url(repo)
    if not url.startswith(GITHUB):
        return url
    owner_name = url[len(GITHUB):-len(".git")]
    gh = gh or _tool("OTO_GH", "gh")
    if not gh:
        raise SandboxError("the GitHub CLI (gh) is not on this computer, and creating %s needs it" % owner_name,
                           "on a Mac: brew install gh; then run again (or create the repository yourself and pass its URL to --repo)")
    env = dict(os.environ, GH_TOKEN=token) if token else dict(os.environ)
    if check:
        return url
    code, out, err = _run([gh, "repo", "view", owner_name, "--json", "name"], timeout=60, env=env)
    if code == 0:
        return url
    code, out, err = _run([gh, "repo", "create", owner_name, "--private"], timeout=120, env=env)
    if code != 0:
        raise SandboxError("could not create the repository %s: %s" % (owner_name, (err or out).strip()[-300:]),
                           "check the token in the variable you named has the repo scope, or create the repository yourself and pass its URL to --repo")
    return url


def first_push(project_dir, url, token=None, kind="knowledge"):
    """Put the laid-out folder under git, with `origin` at the repository, and push its first commit.
    The token, when there is one, goes in the push's own header, never in the remote URL or a file."""
    if not os.path.isdir(os.path.join(project_dir, ".git")):
        _git(project_dir, "init", "-q", "-b", "main")
    _git(project_dir, "add", "-A")
    identity = ["-c", "user.name=oto sandbox", "-c", "user.email=oto-sandbox@localhost"]
    code, out, err = _run(["git", "-C", project_dir] + identity + ["commit", "-q", "-m", "The %s, laid out by oto sandbox up" % ("ontology workspace" if kind == "ontology" else "knowledge project")], timeout=120)
    remotes = _run(["git", "-C", project_dir, "remote"], timeout=60)[1].split()
    if "origin" not in remotes:
        _git(project_dir, "remote", "add", "origin", url)
    header = []
    if token and url.startswith(GITHUB):
        import base64
        header = ["-c", "http.extraheader=AUTHORIZATION: basic %s" % base64.b64encode(("x-access-token:" + token).encode("utf-8")).decode("ascii")]
    code, out, err = _run(["git", "-C", project_dir] + header + ["push", "-q", "-u", "origin", "main"], timeout=300)
    if code != 0:
        raise SandboxError("the first push to %s failed: %s" % (url, (err or out).strip()[-300:]),
                           "check the repository exists and the token in the variable you named may push to it")
    return _run(["git", "-C", project_dir, "rev-parse", "--short", "HEAD"], timeout=60)[1].strip()


def _allow_graph_hosts(sbx, name, rules, report):
    """Let this sandbox alone reach its graphs on the Bolt port, once each. A failure is said, not fatal: the graph's own server says it can't reach Neo4j."""
    if not rules:
        return
    code, out, err = sbx("policy", "ls", name, "--json")
    have = out if code == 0 else ""
    for rule in rules:
        if '"%s"' % rule in have:
            continue
        code, out, err = sbx("policy", "allow", "network", "--sandbox", name, rule)
        if code == 0:
            report["done"].append("allowed %s for this sandbox alone, so it can reach its graphs" % rule)
        else:
            report["warnings"].append("%s could not be allowed for the sandbox: %s; its graphs can't be reached until it is" % (rule, (err or out).strip()[-200:]))


def up(name=DEFAULT_NAME, directory=None, project_id=None, kit=None, approve=False, init_policy=None,
       recreate=False, check=False, wait=600, say=None, allow_outside=False, publish=None,
       kind=None, repo=None, no_repo=False, token_env=None, pack=None):
    """Make the sandbox ready. Returns a report: what was found, what was done, what is next.
    Raises SandboxError, with what the person does about it, when a step cannot go on.

    `kind` lays the project out before the sandbox is made: a knowledge project (on `pack` when named)
    or an ontology workspace. `repo` (owner/name, a URL or a path) backs it with a git repository:
    created on GitHub with the token in the environment variable `token_env` when it is owner/name,
    pushed once from here, and the token stored for the sandbox as the sandbox tool's own GitHub
    secret, so the agent inside pushes without the token ever entering the sandbox. `no_repo` says
    the project is local to the folders."""
    say = say or (lambda line: None)
    if kind is not None and kind not in KINDS:
        raise SandboxError("the kind is one of %s, not %r" % (" or ".join(KINDS), kind), "")
    if repo and no_repo:
        raise SandboxError("--repo and --no-repo contradict each other", "")
    if kind and not repo and not no_repo:
        raise SandboxError("a %s project is backed by a repository unless you say it is not" % kind,
                           "pass --repo <owner/name> (created for you, with the token in --github-token-env), or --no-repo for a project local to the folders")
    token = os.environ.get(token_env) if token_env else None
    if repo and _github_url(repo).startswith(GITHUB) and not token and not check:
        raise SandboxError("creating and pushing to %s needs a GitHub token, and %s" % (repo, ("the variable %s is empty" % token_env) if token_env else "no variable was named"),
                           "put a token with the repo scope in an environment variable and name it with --github-token-env <VAR>; the value is never written anywhere")
    kit = kit or kit_ref()
    if os.path.exists(os.path.expanduser(kit)):   # a local kit: sbx wants an explicit path
        kit = os.path.abspath(os.path.expanduser(kit))
    directory_given = bool(directory)
    directory = os.path.abspath(os.path.expanduser(directory or os.path.join("~", name)))
    project_dir, code_dir = os.path.join(directory, "project"), os.path.join(directory, "code")
    ports = [int(p) for p in (DEFAULT_PORTS if publish is None else publish)]
    report = {"name": name, "kit": kit, "project": project_dir, "code": code_dir, "done": [], "warnings": [], "check": check,
              "ports": [{"port": p, "host_port": p, "host": "127.0.0.1"} for p in ports]}

    sbx = Sbx()
    if not sbx.path:
        raise SandboxError("Docker Sandboxes (the sbx command) is not installed",
                           "on a Mac: brew trust docker/tap && brew install docker/tap/sbx; on Windows 11, in "
                           "PowerShell: winget install -h Docker.sbx (with Windows Hypervisor Platform turned on); "
                           "then open a new terminal")
    report["sbx"] = _version(sbx)
    if supported(report["sbx"]) is False:
        raise SandboxError("Docker Sandboxes %s is older than OTO's kit needs (%s or later)" % (report["sbx"], MIN_SBX),
                           SBX_UPGRADE)
    if not _signed_in(sbx):
        raise SandboxError("the sbx command is not signed in to Docker", "run `sbx login` in a terminal: it opens the browser")
    if not _policy_set(sbx):
        if not init_policy:
            raise SandboxError("no network policy is set for sandboxes yet",
                               "choose one: `balanced` (AI providers, code hosts and package sites allowed, the rest "
                               "asked) is the usual one; then run again with --init-policy balanced")
        if not check:
            code, out, err = sbx("policy", "init", init_policy)
            if code != 0:
                raise SandboxError("sbx could not set the network policy: %s" % (err or out).strip()[:300])
        report["done"].append("set the network policy for sandboxes to %s" % init_policy)
    sources = _allowed_sources(sbx)
    if not _source_allowed(sources, kit):
        prefix = KIT_SOURCE if kit.startswith(KIT_SOURCE) else kit.rsplit(":", 1)[0].rsplit("/", 1)[0] + "/"
        if not check:
            code, out, err = sbx("settings", "set", "kit.allowedSources", json.dumps(sources + [prefix]))
            if code != 0:
                raise SandboxError("sbx would not allow kits from %s: %s" % (prefix, (err or out).strip()[:300]))
        report["done"].append("let sbx run kits from %s" % prefix)
    if not anthropic_bound():
        if not approve:
            raise SandboxError("the kit needs the person's approval to use their Anthropic sign-in",
                               "ask them; with their yes, run again with --approve-anthropic. It lets the sandbox "
                               "use their Claude sign-in for Anthropic's sites only; the credential itself never "
                               "enters the sandbox")
        if not check:
            approve_anthropic()
        report["done"].append("recorded the approval for the kit to use the Anthropic sign-in (%s)" % credentials_path())
    report["anthropic_signed_in"] = _anthropic_secret(sbx)

    existing = _sandboxes(sbx).get(name)
    if existing and not recreate:
        if existing["agent"] != _kit_name(kit):
            raise SandboxError("a sandbox named %s already exists, made from %s rather than OTO's kit" % (name, existing["agent"] or "something else"),
                               "choose another name, or run again with --recreate to replace it (what is only inside it is lost)")
        if existing["folders"]:
            report["project"] = existing["folders"][0]
            report["code"] = existing["folders"][1] if len(existing["folders"]) > 1 else None
        if existing["folders"][:1] != [project_dir] and directory_given:
            report["warnings"].append("the sandbox %s already works on %s, not %s: run again with --recreate to change it"
                                      % (name, ", ".join(existing["folders"]) or "no folder", project_dir))
    report["kind"] = kind
    report["repository"] = _github_url(repo) if repo else None
    graphs = _connections.logins(report["project"] or project_dir)
    report["graphs"] = [{"name": g["name"], "server": g["server"], "variables": g["variables"]} for g in graphs]
    logins = [v for g in graphs for v in g["variables"]]
    logins = [v for i, v in enumerate(logins) if v not in logins[:i]]
    rules = [g["rule"] for g in graphs if g["rule"]]
    rules = [r for i, r in enumerate(rules) if r not in rules[:i]]
    unset = [v for v in logins if not os.environ.get(v)]
    if unset and not check and (recreate or not existing):             # before anything is made or removed
        raise SandboxError("a sandbox made now could not read its graphs: %s %s not set in this terminal" % (" and ".join(unset), "is" if len(unset) == 1 else "are"),
                           "set them here, and run again; a password read with `read -rs` stays out of the shell's history. A graph you have no login for: oto graphs rm <name>")
    if check:
        if logins:
            report["done"].append("would pass the graphs' logins into the sandbox, by name, from this terminal's environment (%s), and allow %s for it alone"
                                  % (", ".join(logins), " and ".join(rules) or "no host"))
        if unset:
            report["warnings"].append("%s %s not set in this terminal: a sandbox made now could not read those graphs" % (" and ".join(unset), "is" if len(unset) == 1 else "are"))
        if kind:
            report["done"].append("would lay out %s in %s" % ("an ontology workspace for the pack %s" % name if kind == "ontology"
                                                           else "a knowledge project%s" % (" on the pack %s" % pack if pack else ""), project_dir))
        if repo:
            url = _github_url(repo)
            creating = ""
            if url.startswith(GITHUB):
                creating = "would create the private repository %s on GitHub with the token in %s, " % (url[len(GITHUB):-len(".git")], token_env or "(no variable named)")
            report["done"].append(creating + "would push the first commit to %s and store the token as the sandbox's GitHub secret" % url)
            if url.startswith(GITHUB) and (kind or "knowledge") == "knowledge":
                report["done"].append("would set the branch rules on main from %s: pull requests required, the checks oto checks and oto route, "
                                      "no approvals at the branch level but a code owner's for what the gate runs on, the merge queue on; "
                                      "with them the code owners (%s, in the first commit) and main's deploy key, kept in the environment %s, "
                                      "for the two workflows that push to main" % (_repo.RULES_FILE, _repo.CODEOWNERS_FILE, _repo.MAIN_ENVIRONMENT))
        report["done"].append(("would remove and recreate the sandbox %s" % name) if existing and recreate else
                              ("would reuse the sandbox %s" % name) if existing else
                              ("would create the sandbox %s from %s" % (name, kit)))
        wanted = declared_plugins(project_dir)
        if wanted:
            report["done"].append("would install in the sandbox " + _plugins_words(wanted))
        elif kind == "knowledge" and pack:
            report["done"].append("would install in the sandbox the plugin of the pack %s, at project scope" % pack)
        report["plugins"] = wanted
        report["ssh"] = _ssh_ready(name)
        return report
    if kind:
        os.makedirs(project_dir, exist_ok=True)
        laid = layout(kind, project_dir, name, pack=pack, repo=bool(repo))
        if laid:
            report["done"].append(laid)
    if repo:
        say("the repository %s" % repo)
        url = github_repository(repo, token)
        if url.startswith(GITHUB):
            report["done"].append("created (or found) the private repository %s on GitHub" % url[len(GITHUB):-len(".git")])
        rules_here = url.startswith(GITHUB) and os.path.exists(os.path.join(project_dir, _repo.RULES_FILE))
        if rules_here and not _repo.code_owner_of(project_dir):
            # the code owners travel in the first commit, so they are on main before the rules ask for them
            from .project import ProjectError
            try:
                login = _repo.github_login(token, gh=_tool("OTO_GH", "gh"))
            except ProjectError:
                login = None
            if login:
                report["done"].append("named %s the code owner of what the route gate runs on (%s)"
                                      % (_repo.write_code_owners(project_dir, login), _repo.CODEOWNERS_FILE))
        commit = first_push(project_dir, url, token=token, kind=kind or "knowledge")
        report["repository"] = url
        report["commit"] = commit
        report["done"].append("pushed the first commit (%s) to %s; origin is set in %s" % (commit, url, project_dir))
        if rules_here:
            from .project import ProjectError
            try:
                rules = _repo.apply_rules(project_dir, url[len(GITHUB):-len(".git")], token=token, gh=_tool("OTO_GH", "gh"))
                report["done"].append("set the branch rules on main from %s (%s): pull requests required, the checks oto checks and oto route, "
                                      "no approvals at the branch level but %s's for what the gate runs on, the merge queue on; main's deploy key "
                                      "is in the environment %s, for the two workflows that push to main"
                                      % (_repo.RULES_FILE, "created" if rules["created"] else "replaced", rules.get("code_owner"), rules.get("environment")))
                for warning in rules.get("warnings") or []:
                    report.setdefault("warnings", []).append(warning)
            except ProjectError as exc:
                report.setdefault("warnings", []).append("the branch rules were not set: %s. Later: oto repo rules --apply, in the project folder" % exc)
    if existing and recreate:
        sbx("rm", "-f", name)
        existing = None
        report["done"].append("removed the sandbox %s, to create it again" % name)
    if existing:
        report["done"].append("reused the sandbox %s (%s)" % (name, existing["status"]))
    else:
        for folder in (project_dir, code_dir):
            os.makedirs(folder, exist_ok=True)
        say("creating the sandbox %s from %s: about a minute the first time" % (name, kit))
        args = ["create", kit, project_dir, code_dir, "--name", name, "--no-progress"]
        mapping, moved = _host_mapping(sbx, name, ports)
        for host, port in mapping:           # published at creation, so the forward is live from the first start
            args += ["-p", "%d:%d" % (host, port)]
        if project_id:
            args += ["-e", "PROJECT=%s" % project_id]
        # the folders' paths inside (the tool mounts them at their own paths): the kit's startup script
        # writes a profile hook from them, so a shell over SSH or sbx run lands on the project, not in
        # the tool's default folder
        args += ["-e", "%s=%s" % (PROJECT_DIR_ENV, project_dir), "-e", "%s=%s" % (CODE_DIR_ENV, code_dir)]
        if allow_outside:
            args += ["-e", "%s=allowed" % OUTSIDE]
        for variable in logins:              # by name: sbx takes the value from this environment, so it stays off the command line
            args += ["-e", variable]
        code, out, err = sbx(*args, timeout=1800)
        if code != 0:
            raise SandboxError("sbx could not create the sandbox: %s" % (err or out).strip()[-600:])
        report["done"].append("created the sandbox %s from %s" % (name, kit))
        if ports:
            report["done"].append(_published_words(mapping, moved) + ", for oto serve inside")
            report["ports"] = [{"port": p, "host_port": h, "host": "127.0.0.1"} for h, p in mapping]
        if logins:
            report["done"].append("passed the graphs' logins into the sandbox, by name, from this terminal's environment: %s" % ", ".join(logins))
    _allow_graph_hosts(sbx, name, rules, report)
    if repo and token and _github_url(repo).startswith(GITHUB):
        code, out, err = sbx("secret", "set", "github", "--sandbox", name, "--token", token, "-f", timeout=120)
        if code != 0:
            report["warnings"].append("the GitHub token could not be stored for the sandbox: %s; pushes from inside will ask for it" % (err or out).strip()[-200:])
        else:
            report["done"].append("stored the token as the sandbox's own GitHub secret: the agent inside pushes to %s, and the token never enters the sandbox" % _github_url(repo))
    say("waiting for OTO to be ready inside it")
    line = _oto_line(sbx, name, wait=wait)
    report["oto"] = line
    if existing and logins:                  # names only: printenv's output goes nowhere, so no value is ever read out
        code, out, err = sbx("exec", name, "--", "sh", "-c", 'for v in "$@"; do printenv "$v" >/dev/null || echo "$v"; done', "sh", *logins)
        absent = out.split() if code == 0 else []
        if absent:
            report["warnings"].append("the sandbox %s holds no %s: a login is set when the sandbox is made. With %s in this terminal, run again with "
                                      "--recreate (what is only inside it is lost; its folders stay)" % (name, " or ".join(absent), "it" if len(absent) == 1 else "them"))
    if existing and project_id:
        code, out, err = sbx("exec", name, "--", "printenv", "PROJECT")
        if out.strip() != project_id:
            report["warnings"].append("the sandbox %s has %s as its Google Cloud project, not %s: run again with "
                                      "--recreate to change it" % (name, out.strip() or "no project", project_id))
    if existing and ports:
        have = {e["port"] for e in published_ports(sbx, name)}
        mapping, moved = _host_mapping(sbx, name, [p for p in ports if p not in have])
        added = []
        for host, port in mapping:
            code, out, err = sbx("ports", name, "--publish", "%d:%d" % (host, port))
            if code == 0:
                added.append((host, port))
            else:
                report["warnings"].append("port %d could not be published: %s" % (port, (err or out).strip()[-200:]))
        if added:
            report["done"].append(_published_words(added, {p: moved[p] for _h, p in added if p in moved}))
            if existing["status"] == "running":
                report["warnings"].append("a port published to a running sandbox forwards from its next start: `sbx stop %s`, "
                                          "then the next connection starts it" % name)
        report["ports"] = published_ports(sbx, name)
    if existing and allow_outside:
        code, out, err = sbx("exec", name, "--", "printenv", OUTSIDE)
        if out.strip().lower() != "allowed":
            report["warnings"].append("the sandbox %s blocks plugins from outside it: run again with --recreate to "
                                      "make one that allows them" % name)
    if not line or READY not in line:
        raise SandboxError("OTO is not ready in the sandbox: %s" % (line or "it says nothing yet"),
                           "`sbx exec %s -- tail -20 /tmp/oto-init.log` shows how far it got" % name)
    if not _ssh_ready(name):
        code, out, err = sbx("setup", "ssh", timeout=300)
        if code != 0 or not _ssh_ready(name):
            raise SandboxError("SSH to the sandbox is not set up: %s" % (err or out).strip()[:300],
                               "run `sbx setup ssh` in a terminal")
        report["done"].append("set up SSH, so %s.sbx reaches the sandbox" % name)
    report["ssh"] = True
    lock = plugin_lock(sbx, name)
    new = coming(lock) if lock and lock.get("script") else []
    if new:
        code, out, err = sbx("exec", name, "--", "sh", "-c", 'python3 "$HOME/.oto/lock-plugins" --names "$@"', "sh", *new)
        if code == 0:
            report["done"].append("switched off in the sandbox the %d plugin%s Claude Desktop would bring from this "
                                  "computer" % (len(new), "" if len(new) == 1 else "s"))
        lock = plugin_lock(sbx, name)
    if lock and lock["mode"] == "blocked" and not lock["locked"] and not lock["script"]:
        report["warnings"].append("the sandbox %s was made from a kit without the plugin lock: plugins from this computer "
                                  "and your claude.ai account load in it. Run again with --recreate to make it from the "
                                  "current kit" % name)
    report["outside_plugins"] = lock
    report["outside_plugins_summary"] = describe_lock(lock, coming(lock))
    wanted = declared_plugins(project_dir)
    report["plugins"] = wanted
    if wanted:
        say("installing in the sandbox %s" % _plugins_words(wanted))
        code, out, err = sbx("exec", name, "--", "sh", "-c", INSTALL_PLUGINS, "sh", project_dir, *wanted, timeout=600)
        if code == 0:
            report["done"].append("installed in the sandbox " + _plugins_words(wanted))
        else:
            report["warnings"].append("the plugins the project declares (%s) could not be installed in the sandbox: %s; "
                                      "inside, the packs skill (/oto:packs) installs them" % (", ".join(wanted), (err or out).strip()[-300:]))
    return report


def next_steps(report):
    """What the person does next, in Claude Desktop or a terminal."""
    name = report["name"]
    lines = []
    if report.get("kind") == "ontology":
        lines.append("In the sandbox the project folder is an ontology workspace: the ontology-interview skill fills ontology/%s/, "
                     "oto pack check . --strict and oto pack try . hold it to its gates, oto pack publish releases it." % name)
    elif report.get("kind") == "knowledge":
        lines.append("In the sandbox the project folder is a knowledge project%s: documents into inbox/, the build-knowledge-base skill from there."
                     % ("" if not report.get("repository") else ", backed by %s" % report["repository"]))
    lines += ["In Claude Desktop: the Code tab, a new session, then the environment menu: SSH, Add SSH connection.",
             "  Name: OTO (%s). SSH host: %s.sbx. Leave the port and the identity file empty." % (name, name),
             "  Choose that connection, then the folder %s." % (report["project"] or "you work in"),
             "Or in a terminal: sbx run --name %s" % name]
    if report.get("graphs"):
        lines += ["In the sandbox each graph has a server of its own: %s. Ask in the project folder, and each answer comes from Neo4j at that moment."
                  % ", ".join(g["server"] for g in report["graphs"]),
                  "  A login is set when the sandbox is made: after adding a graph with a new one, oto sandbox up --recreate (its folders stay)."]
    ports = [(e["port"], e.get("host_port", e["port"])) for e in report.get("ports") or []]
    if ports:
        lines += ["To see a served graph: in the sandbox, oto serve --project . --http %d (it binds all interfaces there, no token needed);"
                  % ports[0][0],
                  "  on this computer, open http://localhost:%d/%s" % (ports[0][1], (" (and %s for a second view)" % ", ".join("%d" % h for _p, h in ports[1:])) if ports[1:] else "")]
    return lines
