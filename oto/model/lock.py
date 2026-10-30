# -*- coding: utf-8 -*-
"""The project lock: the exact tools a project is built with, so another machine can rebuild them
and an auditor can read them.

`oto.lock.json`, at the project root and committed with it:

    engine        the OTO engine: its version, and the checkout and commit when it runs from one
    marketplaces  each Claude Code marketplace the project's plugins come from: its source, its commit
    plugins       each plugin the project uses: its marketplace, version and commit
    ontologies    what the project started from: project.config.json's record, releases and commits

Which plugins a project uses: those its `.claude/settings.json` enables (Claude Code's own
declaration, committed with the project); without one, the OTO plugins this machine has for it:
the engine plugin, the packs, and the plugins that depend on the engine. `oto init` writes the
declaration for the packs it starts from (`declare`), in the form `claude plugin install --scope
project` writes, so whoever opens the project is offered the same plugins; `oto lock --use` adds a
tool no ontology brings. Everything is read from
Claude Code's files under CLAUDE_CONFIG_DIR (default ~/.claude); nothing is installed or fetched.

`drift` says how this machine differs from the lock; `restore_script` writes the shell script that
rebuilds the locked tools on a fresh machine or in a container: each marketplace cloned at its
locked commit and added from that directory (Claude Code pins a marketplace to a branch or a tag,
never a commit), each plugin installed from it, and the engine pinned by its release tag through
OTO_SOURCE, which the engine plugin's server and hook read.

`sandbox_files` writes the project's Docker sandbox (Docker Sandboxes, the `sbx` CLI): Claude Code
in a small virtual machine of its own, the project folder shared with it, the network closed but
for what the person's sbx policy allows, an API key added on the way out and never inside.
`sbxenv.yaml` names it and pins OTO_SOURCE; once, when the sandbox is created, it runs
`.sandbox/setup.sh` inside it: the same restore, plus what Docker's Claude image lacks (LibreOffice
and fonts for older Office files, Chromium for pdf-to-template, the `uvx` the engine plugin calls,
GitHub over HTTPS, since the sandbox closes SSH). `oto lock` rewrites both while they are its own.
"""
import datetime
import functools
import json
import os
import re
import subprocess

from . import ontologies as _ontologies

LOCK_NAME = "oto.lock.json"
ENGINE_PLUGIN = "oto"
ENGINE_REPO = "https://github.com/Cynergis/oto"
ABOUT = ("The tools this project is built with, so another machine can rebuild them (oto lock --script) and "
         "an auditor can read them. Written by `oto lock`; `oto lock --check` and `oto status` say how a "
         "machine differs. Commit it with the project.")


def _claude_dir():
    return os.environ.get(_ontologies.CLAUDE_CONFIG_ENV) or os.path.join(os.path.expanduser("~"), ".claude")


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _git(path, *args):
    """git's answer in `path`, or None when it is not a checkout or git is absent."""
    try:
        out = subprocess.run(["git", "-C", path] + list(args), capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


# ---- what this machine has ----

def engine():
    """The engine running now: its version, and the checkout and commit when it runs from one. An
    engine installed from a package records no commit; its release tag (v<version>) pins it."""
    from .. import __version__
    out = {"version": __version__, "source": ENGINE_REPO, "tag": "v%s" % __version__, "commit": None}
    out.update(_checkout())
    pinned = os.environ.get("OTO_SOURCE")
    if pinned:
        out["oto_source"] = pinned
    return out


@functools.lru_cache(maxsize=1)
def _checkout():
    """The engine's checkout when it runs from one: asked once per process, it does not change."""
    top = _git(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rev-parse", "--show-toplevel")
    if not top:
        return {}
    return {"source": _git(top, "config", "--get", "remote.origin.url") or top, "checkout": top,
            "commit": _git(top, "rev-parse", "HEAD"),
            "modified": bool(_git(top, "status", "--porcelain", "--untracked-files=no"))}


SETTINGS = os.path.join(".claude", "settings.json")


def _installs():
    plugins = (_read_json(os.path.join(_claude_dir(), "plugins", "installed_plugins.json"), {}) or {}).get("plugins") or {}
    return plugins if isinstance(plugins, dict) else {}


def plugin_for(directory):
    """The installed plugin (`name@marketplace`) whose install is this directory, or None: how a
    pack given by its path is named."""
    want = os.path.normpath(os.path.abspath(directory))
    for key, entries in sorted(_installs().items()):
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict) and entry.get("installPath") and os.path.normpath(entry["installPath"]) == want:
                return key
    return None


def packs_of(ontology, root, prefer=()):
    """The installed plugin that is the pack of this ontology (its manifest embeds it as its own),
    for this project: it brings the ontology's skills and views wherever the vocabulary was read
    from (a built-in ddd still needs the ddd pack's model-domain). Several, from several
    marketplaces: the one from a preferred marketplace, else the first. None when no pack is installed."""
    owners = []
    for key, entry in sorted(installed(root).items()):
        path = entry.get("installPath") or ""
        manifest = _read_json(os.path.join(path, "manifest.json"), None)
        if isinstance(manifest, dict) and (manifest.get("ontology") or {}).get("name") == ontology \
                and os.path.isdir(os.path.join(path, "ontology")):
            owners.append(key)
    preferred = [k for k in owners if k.split("@", 1)[1] in set(prefer)]
    return (preferred or owners or [None])[0]


def engine_plugin_id(prefer=()):
    """`oto@<marketplace>` for the engine plugin as this machine can install it: from a marketplace in
    `prefer` that lists it, else from any marketplace Claude Code knows that does (the engine's own,
    `cynergis-engine`, since a registry carries no engine: ADR-0009). None when no marketplace lists it."""
    known = _read_json(os.path.join(_claude_dir(), "plugins", "known_marketplaces.json"), {}) or {}
    names = [m for m in prefer if m in known] + sorted(m for m in known if m not in prefer)
    for market in names:
        if _listed_from(market, ENGINE_PLUGIN) is not None:
            return "%s@%s" % (ENGINE_PLUGIN, market)
    return None


def declare(root, ids):
    """Add plugins to the project's Claude Code declaration (.claude/settings.json), as `claude plugin
    install --scope project` does: each enabled, its marketplace known, and the engine plugin from the
    marketplace that lists it (the engine's own, unless the pack's registry lists one). Everything else
    in the file is kept. Returns the ids it added."""
    wanted = list(ids)
    if not any(key.split("@", 1)[0] == ENGINE_PLUGIN for key in wanted):
        engine_id = engine_plugin_id(prefer=[key.split("@", 1)[1] for key in ids if "@" in key])
        if engine_id:
            wanted.append(engine_id)
    path = os.path.join(root, SETTINGS)
    settings = _read_json(path, {})
    settings = settings if isinstance(settings, dict) else {}
    enabled = settings.setdefault("enabledPlugins", {})
    markets = settings.setdefault("extraKnownMarketplaces", {})
    added = []
    for key in wanted:
        if enabled.get(key) is not True:
            enabled[key] = True
            added.append(key)
        market = key.split("@", 1)[1] if "@" in key else None
        source = _known(market).get("source") if market else None
        if market and market not in markets and source:
            markets[market] = {"source": source}
    if not markets:
        settings.pop("extraKnownMarketplaces")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return added


def install_views(root, ids, force=False, skip=()):
    """Copy the views of these plugins into the project's views/, so its site and its server show
    them: [(view, plugin id, "wrote" or "kept")]. A name already there is kept, the first pack to
    bring it wins, unless `force`; plugins in `skip` (whose views are already in) are passed over."""
    import shutil
    from . import packs as _packs
    have = installed(root)
    out = []
    for key in ids:
        path = (have.get(key) or {}).get("installPath")
        if key in skip or not path:
            continue
        for name, source in sorted(_packs.views(path).items()):
            target = os.path.join(root, "views", name)
            if os.path.exists(target) and not force:
                out.append((name, key, "kept"))
                continue
            if os.path.exists(target):
                shutil.rmtree(target)
            shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store"))
            out.append((name, key, "wrote"))
    return out


def declared(root):
    """The plugins the project's own Claude Code settings enable, as `name@marketplace`, or None."""
    settings = _read_json(os.path.join(root, SETTINGS), None)
    if not isinstance(settings, dict) or not isinstance(settings.get("enabledPlugins"), dict):
        return None
    return sorted(k for k, on in settings["enabledPlugins"].items() if on and "@" in k)


def installed(root):
    """Claude Code's installs that apply to this project: `name@marketplace` -> its record, the
    project's own scope before the user's."""
    root = os.path.normpath(os.path.abspath(root))
    out = {}
    for key, entries in _installs().items():
        if not isinstance(entries, list):
            continue
        mine = [e for e in entries if isinstance(e, dict) and e.get("projectPath")
                and os.path.normpath(e["projectPath"]) == root]
        users = [e for e in entries if isinstance(e, dict) and e.get("scope") == "user"]
        if mine or users:
            out[key] = (mine or users)[0]
    return out


def _is_oto(key, entry):
    """The engine plugin, a pack, or a plugin that depends on the engine."""
    if key.split("@", 1)[0] == ENGINE_PLUGIN:
        return True
    path = entry.get("installPath") or ""
    if os.path.exists(os.path.join(path, "manifest.json")) and os.path.isdir(os.path.join(path, "ontology")):
        return True
    plugin = _read_json(os.path.join(path, ".claude-plugin", "plugin.json"), {}) or {}
    return any(str(d).split("@", 1)[0] == ENGINE_PLUGIN for d in (plugin.get("dependencies") or []))   # "oto" or "oto@<its marketplace>"


def used(root):
    """(the plugins the project uses, whether the project declares them itself)."""
    have = installed(root)
    mine = declared(root)
    if mine is not None:
        return mine, True
    disabled = {k for k, on in ((_read_json(os.path.join(_claude_dir(), "settings.json"), {}) or {})
                                .get("enabledPlugins") or {}).items() if on is False}
    return sorted(k for k, e in have.items() if k not in disabled and _is_oto(k, e)), False


def _known(name):
    known = (_read_json(os.path.join(_claude_dir(), "plugins", "known_marketplaces.json"), {}) or {}).get(name)
    return known if isinstance(known, dict) else {}


def offered(root):
    """What the project's plugins offer, for `oto status` and the concierge: for each plugin it uses
    other than the engine's own, its version, its skills (name, what it does in one clause, the
    command that calls it) and its views. Read from the installs; a declared plugin not installed
    here offers nothing yet and says so."""
    from . import packs as _packs
    have = installed(root)
    ids, own = used(root)
    out = []
    for key in ids:
        name = key.split("@", 1)[0]
        if name == ENGINE_PLUGIN:
            continue
        entry = have.get(key) or {}
        path = entry.get("installPath") or ""
        skills = []
        for skill, skill_path in sorted(_packs.skills(path).items()) if path else []:
            try:
                summary = _packs._skill_summary(skill_path)
            except OSError:
                summary = ""
            skills.append({"name": skill, "summary": summary, "command": "/%s:%s" % (name, skill)})
        manifest = _read_json(os.path.join(path, "manifest.json"), {}) if path else {}
        pattern = (manifest or {}).get("pattern") if isinstance(manifest, dict) else None
        playbook = (manifest or {}).get("playbook") if isinstance(manifest, dict) else None
        binding = (manifest or {}).get("binding") if isinstance(manifest, dict) else None
        out.append({"id": key, "name": name, "version": entry.get("version"), "installed": bool(entry),
                    "pack": bool(path) and os.path.isdir(os.path.join(path, "ontology")),
                    "pattern": pattern if isinstance(pattern, dict) else None,
                    "playbook": playbook if isinstance(playbook, dict) else None,
                    "binding": binding if isinstance(binding, dict) else None,
                    "skills": skills, "views": sorted(_packs.views(path)) if path else []})
    return {"declared_by": ".claude/settings.json" if own else ("the OTO plugins installed for it" if out else None),
            "plugins": out}


def marketplace(name):
    """A marketplace Claude Code knows: its source as Claude Code records it, and the commit of its copy."""
    location = _known(name).get("installLocation") or ""
    return {"name": name, "source": _known(name).get("source") or None,
            "commit": _git(location, "rev-parse", "HEAD") if location else None}


def _listed_from(market, name):
    """Where a marketplace's listing says a plugin comes from: "marketplace" (inside it, pinned with
    it), a repository (its default branch unless a ref is named), or None when unknown."""
    location = _known(market).get("installLocation") or ""
    listing = _read_json(os.path.join(location, ".claude-plugin", "marketplace.json"), {}) or {}
    for plugin in listing.get("plugins") or []:
        if plugin.get("name") == name:
            source = plugin.get("source")
            if isinstance(source, str):
                return "marketplace"
            if isinstance(source, dict):
                where = source.get("repo") or source.get("url") or "a repository"
                return "%s@%s" % (where, source["ref"]) if source.get("ref") else where
    return None


def make(project):
    """The lock this machine would write for the project."""
    root = project.data
    have = installed(root)
    ids, own = used(root)
    plugins = []
    for key in ids:
        name, market = key.split("@", 1)
        entry = have.get(key)
        plugins.append({"id": key, "name": name, "marketplace": market,
                        "version": entry.get("version") if entry else None,
                        "commit": entry.get("gitCommitSha") if entry else None,
                        "listed_from": _listed_from(market, name), "installed": entry is not None})
    markets = [marketplace(m) for m in sorted({p["marketplace"] for p in plugins})]
    try:
        record = project.config().get("ontology")
    except Exception:                                                  # noqa: BLE001 - a lock still records the tools
        record = None
    return {"_about": ABOUT, "locked_at": datetime.date.today().isoformat(), "engine": engine(),
            "declared_by": ".claude/settings.json" if own else "the OTO plugins installed for it",
            "marketplaces": markets, "plugins": plugins, "ontologies": record}


def path(project):
    return os.path.join(project.data, LOCK_NAME)


def read(project):
    return _read_json(path(project), None)


def write(project):
    """Write the lock; returns (path, lock)."""
    lock = make(project)
    with open(path(project), "w", encoding="utf-8", newline="\n") as f:
        json.dump(lock, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path(project), lock


# ---- how this machine differs ----

def drift(project, lock=None):
    """What differs between the lock and this machine, as sentences; [] when they agree. The
    marketplaces' commits are not compared: a registry moves on while the plugins a project uses
    stay at their versions."""
    lock = lock if lock is not None else read(project)
    if lock is None:
        return ["no %s: oto lock writes it" % LOCK_NAME]
    now = make(project)
    out = []
    was, here = lock.get("engine") or {}, now["engine"]
    if was.get("version") != here["version"]:
        out.append("the engine is %s here, locked at %s" % (here["version"], was.get("version")))
    elif was.get("commit") and here.get("commit") and was["commit"] != here["commit"]:
        out.append("the engine is %s at commit %s here, locked at %s" % (here["version"], here["commit"][:10], was["commit"][:10]))
    locked = {p["id"]: p for p in lock.get("plugins") or []}
    current = {p["id"]: p for p in now["plugins"]}
    for key in sorted(locked):
        want, have = locked[key], current.get(key)
        if have is None or not have["installed"]:
            out.append("%s is locked at %s and not installed here" % (key, want.get("version")))
        elif have["version"] != want.get("version"):
            out.append("%s is %s here, locked at %s" % (key, have["version"], want.get("version")))
        elif want.get("commit") and have.get("commit") and have["commit"] != want["commit"]:
            out.append("%s is %s here from commit %s, locked from %s" % (key, have["version"], have["commit"][:10], want["commit"][:10]))
    for key in sorted(set(current) - set(locked)):
        out.append("%s %s is used here and not in the lock" % (key, current[key]["version"]))
    if (lock.get("ontologies") or None) != (now["ontologies"] or None):
        out.append("the project's ontology record changed since the lock")
    return out


def warnings(lock):
    """What a lock cannot pin, as sentences: a reader of the lock should know."""
    out = []
    eng = lock.get("engine") or {}
    if eng.get("checkout") and eng.get("modified"):
        out.append("the engine ran from a checkout with uncommitted changes (%s)" % eng["checkout"])
    for market in lock.get("marketplaces") or []:
        source = market.get("source") or {}
        if source.get("source") == "directory":
            out.append("marketplace %s is a directory on this machine (%s): another machine cannot clone it"
                       % (market["name"], source.get("path")))
        elif not market.get("commit"):
            out.append("marketplace %s: its commit could not be read" % market["name"])
    for plugin in lock.get("plugins") or []:
        if not plugin.get("installed"):
            out.append("%s is declared but not installed here: nothing to lock" % plugin["id"])
        elif plugin.get("listed_from") not in (None, "marketplace") and "@" not in plugin["listed_from"]:
            out.append("%s comes from %s's default branch: a restore installs what it holds then, and the check "
                       "names any other version" % (plugin["id"], plugin["listed_from"]))
    return out


# ---- rebuilding it elsewhere ----

def _clone_url(source):
    kind = (source or {}).get("source")
    if kind == "github":
        return "https://github.com/%s.git" % source["repo"]
    if kind in ("git", "url"):
        return source.get("url")
    return None


def engine_pin(lock):
    """What installs the locked engine: `oto-kg[intake] @ git+<repo>@<commit or tag>`."""
    eng = lock.get("engine") or {}
    ref = eng.get("commit") or eng.get("tag") or "main"
    source = eng.get("source") if str(eng.get("source") or "").startswith(("http", "git@")) else ENGINE_REPO
    source = source[:-4] if source.endswith(".git") else source
    return "oto-kg[intake] @ git+%s@%s" % (source, ref)


def _restore_lines(lock):
    """The body of a restore: each marketplace at its commit, each plugin, the engine."""
    eng = lock.get("engine") or {}
    pin = engine_pin(lock)
    lines = ['DIR="${OTO_LOCK_DIR:-$HOME/.oto/locked}"', 'mkdir -p "$DIR"', ""]
    for market in lock.get("marketplaces") or []:
        url, commit = _clone_url(market.get("source")), market.get("commit")
        if not url or not commit:
            lines.append("# marketplace %s cannot be rebuilt here: %s" % (market["name"], "no commit" if url else "not a git source"))
            continue
        where = '"$DIR/%s-%s"' % (market["name"], commit[:12])
        lines += ["# marketplace %s at %s (Claude Code pins a branch or a tag, not a commit: added from a clone)" % (market["name"], commit),
                  "[ -d %s ] || git clone --quiet %s %s" % (where, url, where),
                  "git -C %s checkout --quiet %s" % (where, commit),
                  "claude plugin marketplace add %s" % where, ""]
    for plugin in lock.get("plugins") or []:
        if plugin.get("installed"):
            lines.append("claude plugin install %s    # locked at %s" % (plugin["id"], plugin.get("version")))
    lines += ["",
              "# the engine at %s %s: its plugin's server and hook read OTO_SOURCE, the oto command is installed from it"
              % (eng.get("version"), pin.rsplit("@", 1)[1]),
              'uv tool install --force "%s"' % pin]
    return lines


def restore_script(lock, project_name=None):
    """A POSIX shell script that rebuilds the locked tools: run it in a fresh environment (a
    container, a test profile with CLAUDE_CONFIG_DIR set). Needs git, uv and Claude Code."""
    lines = ["#!/bin/sh",
             "# The tools of %s as locked on %s (oto.lock.json). Needs git, uv and Claude Code."
             % (project_name or "this project", lock.get("locked_at")),
             "# Run it where they should live: a container, or a profile of its own (CLAUDE_CONFIG_DIR).",
             "set -e"] + _restore_lines(lock)
    lines.append("echo 'add to the environment: export OTO_SOURCE=\"%s\"'" % engine_pin(lock).replace("[intake]", ""))
    return "\n".join(lines) + "\n"


# ---- the project's Docker sandbox ----

SANDBOX_FILE = "sbxenv.yaml"
SANDBOX_SETUP = os.path.join(".sandbox", "setup.sh")
SANDBOX_MARK = "Written by `oto lock --sandbox`"


def sandbox_name(slug):
    """The sandbox's name: oto-<slug>, in the letters a sandbox name takes."""
    return "oto-" + (re.sub(r"[^a-z0-9]+", "-", str(slug or "project").lower()).strip("-") or "project")


def sandbox_files(lock, slug, project_name=None):
    """{relative path: text} for the project's Docker sandbox: sbxenv.yaml and .sandbox/setup.sh."""
    name = sandbox_name(slug)
    pin = engine_pin(lock)
    env = """# The Docker sandbox %(project)s runs in (Docker Sandboxes, the `sbx` CLI): Claude Code in a small
# virtual machine of its own, this folder shared with it, the network closed but for what your sbx
# policy allows. %(mark)s from oto.lock.json; `oto lock` rewrites it.
# Start it here with `sbx env run`: the first run creates it, asks you to approve once, and sets up the
# locked tools inside it (.sandbox/setup.sh); later runs reopen it.
schemaVersion: "1"
name: %(name)s
agent: claude
workspace: .
env:
  OTO_SOURCE: "%(source)s"
lifecycle:
  postCreate:
    - name: oto-tools
      command: sbx exec "$SBX_SANDBOX_NAME" -- sh "$SBX_WORKSPACE/.sandbox/setup.sh"
      timeout: 30m
""" % {"project": project_name or "this project", "mark": SANDBOX_MARK, "name": name, "source": pin.replace("[intake]", "")}
    setup = ["#!/bin/sh",
             "# Sets up, inside the Docker sandbox of %s, the tools oto.lock.json records (locked %s)."
             % (project_name or "this project", lock.get("locked_at")),
             "# %s; sbxenv.yaml runs it once, when the sandbox is created." % SANDBOX_MARK,
             "set -e",
             'cd "$(dirname "$0")/.."',
             "",
             'echo "== LibreOffice and fonts, for older Office files at intake"',
             "# the sandbox may still be updating its own packages when this starts: wait for it",
             "n=0; while pgrep -x apt-get >/dev/null || pgrep -x dpkg >/dev/null; do n=$((n+1)); [ $n -gt 300 ] && break; sleep 2; done",
             "sudo apt-get -o DPkg::Lock::Timeout=600 update -qq",
             "sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 install -y -qq --no-install-recommends \\",
             "  libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui fonts-liberation fonts-dejavu-core >/dev/null",
             "",
             'echo "== uvx, which the oto plugin calls, and GitHub over HTTPS (the sandbox closes SSH)"',
             "command -v uvx >/dev/null || { printf '#!/bin/sh\\nexec uv tool run \"$@\"\\n' | sudo tee /usr/local/bin/uvx >/dev/null; "
             "sudo chmod 755 /usr/local/bin/uvx; }",
             'git config --global url."https://github.com/".insteadOf git@github.com:',
             'git config --global --add url."https://github.com/".insteadOf ssh://git@github.com/',
             "",
             'echo "== the locked marketplace, plugins and engine"'] + _restore_lines(lock) + [
             "",
             'echo "== Chromium, for pdf-to-template\'s renderer"',
             "uv tool run --from playwright playwright install --with-deps chromium >/tmp/oto-chromium.log 2>&1 \\",
             '  || echo "Chromium was not installed (see /tmp/oto-chromium.log); pdf-to-template\'s doctor installs it on first use"',
             "",
             "oto lock --check --project ."]
    return {SANDBOX_FILE: env, SANDBOX_SETUP: "\n".join(setup) + "\n"}


def sandbox_written(root):
    """Whether the project's sbxenv.yaml is the one `oto lock --sandbox` wrote (so `oto lock` may rewrite it)."""
    try:
        return SANDBOX_MARK in open(os.path.join(root, SANDBOX_FILE), encoding="utf-8").read()
    except OSError:
        return False


def write_sandbox(project, lock):
    """Write the sandbox files under the project; returns their relative paths."""
    files = sandbox_files(lock, project.config().get("slug"), project.config().get("name"))
    for rel, text in files.items():
        where = os.path.join(project.data, rel)
        os.makedirs(os.path.dirname(where) or ".", exist_ok=True)
        with open(where, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        if rel.endswith(".sh"):
            os.chmod(where, 0o755)
    return sorted(files)
