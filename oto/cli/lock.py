# -*- coding: utf-8 -*-
"""`oto lock`: record the tools a project is built with, check a machine against them, and write
the script that rebuilds them elsewhere, or the Docker sandbox that runs the project with them."""
import os
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_lock(args):
    from ..model import lock as _lock

    project = _resolve(args)
    if args.check:
        locked = _lock.read(project)
        problems = _lock.drift(project, locked)
        if not problems:
            print("%s matches this machine (locked %s)" % (_lock.LOCK_NAME, locked.get("locked_at")))
            return 0
        print("%d difference(s) from %s:" % (len(problems), _lock.LOCK_NAME))
        for problem in problems:
            print("  - %s" % problem)
        print("oto lock --script rebuilds the locked tools elsewhere; oto lock records this machine's instead")
        return 1
    if args.script:
        locked = _lock.read(project)
        if locked is None:
            print("oto: no %s yet: oto lock writes it" % _lock.LOCK_NAME, file=sys.stderr)
            return 1
        sys.stdout.write(_lock.restore_script(locked, project.config().get("name")))
        return 0
    if args.sandbox:
        locked = _lock.read(project)
        if locked is None:
            print("oto: no %s yet: oto lock writes it" % _lock.LOCK_NAME, file=sys.stderr)
            return 1
        _sandbox_written(project, locked)
        print("  start it      sbx env run, in the project folder: the first run creates the sandbox, asks you to approve it")
        print("                once and sets up the tools inside; later runs reopen it")
        print("  it needs      Docker Sandboxes (sbx), signed in (sbx login), with a network policy (sbx policy init balanced)")
        print("commit them with the project; oto lock rewrites them when it records new tools")
        return 0
    if args.use:
        ids = [k.strip() for k in args.use.split(",") if k.strip()]
        bad = [k for k in ids if "@" not in k]
        if bad:
            print("oto: --use takes plugins as name@marketplace: %s" % ", ".join(bad), file=sys.stderr)
            return 1
        added = _lock.declare(project.data, ids)
        print("declared in %s: %s" % (_lock.SETTINGS, ", ".join(added) or "nothing new"))
        for name, key, state in _lock.install_views(project.data, ids):
            print("  %s views/%s (from %s)" % ("installed" if state == "wrote" else "kept, already there:", name, key))
    where, locked = _lock.write(project)
    eng = locked["engine"]
    print("wrote %s" % where)
    print("  engine        %s%s" % (eng["version"], (" at %s" % eng["commit"][:10]) if eng.get("commit") else " (tag %s)" % eng["tag"]))
    for market in locked["marketplaces"]:
        print("  marketplace   %s at %s" % (market["name"], (market.get("commit") or "an unknown commit")[:10]))
    plugins = [p for p in locked["plugins"] if p["installed"]]
    print("  plugins       %d, declared by %s: %s" % (len(plugins), locked["declared_by"],
                                                     ", ".join("%s %s" % (p["id"], p["version"]) for p in plugins) or "none"))
    record = locked.get("ontologies") or {}
    parts = record.get("parts") or ([record] if record.get("name") else [])
    if parts:
        print("  ontologies    %s" % ", ".join("%s @%s" % (p.get("name"), p.get("release")) for p in parts))
    for warning in _lock.warnings(locked):
        print("  note: %s" % warning)
    if _lock.sandbox_written(project.data):
        _sandbox_written(project, locked)
    elif os.path.exists(os.path.join(project.data, _lock.SANDBOX_FILE)):
        print("  note: %s is not the one oto lock --sandbox writes, so it was left as it is" % _lock.SANDBOX_FILE)
    if locked["declared_by"] != ".claude/settings.json":
        print("  the project declares no plugins of its own: oto lock --use <name@marketplace>,... declares them in %s"
              % _lock.SETTINGS)
    print("commit it with the project (and %s); oto lock --check compares a machine, oto lock --script rebuilds the tools"
          % _lock.SETTINGS)
    return 0


def _sandbox_written(project, locked):
    from ..model import lock as _lock
    files = _lock.write_sandbox(project, locked)
    print("wrote %s: the Docker sandbox %s, with the engine %s and the locked plugins"
          % (" and ".join(files), _lock.sandbox_name(project.config().get("slug")), (locked.get("engine") or {}).get("version")))


def register(sub):
    lock = sub.add_parser("lock", help="record the engine, plugins and ontologies a project is built with; check or rebuild them")
    project_arguments(lock)
    mode = lock.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="say how this machine differs from oto.lock.json (exit 1 when it does)")
    mode.add_argument("--script", action="store_true", help="print the shell script that rebuilds the locked tools elsewhere")
    mode.add_argument("--sandbox", action="store_true",
                      help="write the project's Docker sandbox (sbxenv.yaml and .sandbox/setup.sh): Claude Code with the "
                           "locked tools, started with `sbx env run`")
    lock.add_argument("--use", metavar="PLUGINS",
                      help="declare plugins the project uses beyond its packs (name@marketplace, comma-separated) in "
                           ".claude/settings.json, then lock")
    lock.set_defaults(func=cmd_lock)
