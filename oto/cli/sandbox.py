# -*- coding: utf-8 -*-
"""`oto sandbox`: Claude Code with OTO inside a Docker sandbox, made from OTO's kit and ready to be
driven from Claude Desktop's Code tab over SSH, or from a terminal."""
import json
import sys


def _print_status(s):
    yes = lambda ok: "yes" if ok else "no"  # noqa: E731
    print("sandbox %s (kit %s)" % (s["name"], s["kit"]))
    print("  sbx            %s" % ("not installed" if not s["sbx"] else "v%s, signed in: %s" % (s["sbx"], yes(s["signed_in"]))))
    if s["sbx"] and s["signed_in"]:
        print("  network policy %s" % ("set" if s["policy"] else "not set"))
        print("  kit allowed    %s" % yes(s["kit_allowed"]))
    print("  Anthropic      approved for the kit: %s%s" % (yes(s["anthropic_approved"]),
          (", signed in: %s" % yes(s["anthropic_signed_in"])) if s["sbx"] and s["signed_in"] else ""))
    if s["sandbox"]:
        print("  sandbox        %s, made from %s; %s" % (s["sandbox"], s["made_from"] or "?", s["oto"] or (
            "not OTO's kit" if not s["from_kit"] else "OTO says nothing yet" if s["sandbox"] == "running"
            else "oto sandbox up starts it")))
        if s["folders"]:
            print("  folders        %s" % ", ".join(s["folders"]))
        if s["sandbox"] == "running" and s["from_kit"]:
            print("  outside plugins %s" % s["outside_plugins_summary"])
        print("  SSH            %s" % ("%s.sbx" % s["name"] if s["ssh"] else "not set up"))
        if s.get("ports"):
            print("  ports          %s (oto serve --http <port> inside; open http://localhost:<port>/ on this computer)"
                  % ", ".join("%d" % e["port"] if e["port"] == e["host_port"] else "%d->%d" % (e["host_port"], e["port"]) for e in s["ports"]))
    elif s["sbx"] and s["signed_in"]:
        print("  sandbox        not created: oto sandbox up --name %s" % s["name"])


def _print_listing(listing):
    if not listing["sbx"]:
        print("sbx is not installed: nothing to list")
        return
    if not listing["signed_in"]:
        print("sbx is not signed in to Docker (sbx login): nothing to list")
        return
    boxes = listing["sandboxes"]
    print("%d sandbox(es) on this computer" % len(boxes) if boxes else "no sandbox on this computer")
    for box in boxes:
        idle = "used today" if box["idle_days"] == 0 else ("idle %d day(s)" % box["idle_days"]) if box["idle_days"] is not None else "last use unknown"
        kit = "OTO's kit" if box["from_kit"] else ("made from %s, not OTO's kit" % (box["made_from"] or "?"))
        print("  %-22s %-8s %s; %s; SSH %s" % (box["name"], box["status"], idle, kit, "%s.sbx" % box["name"] if box["ssh"] else "not set up"))
        for folder in box["folders"]:
            print("      %s%s" % (folder["path"], "" if folder["exists"] else "  (folder gone)"))
    stale = [c for c in listing["connections"] if not c["exists"]]
    if listing["connections"]:
        print("Claude Desktop knows %d SSH connection(s) to sandboxes%s" % (len(listing["connections"]),
              ": %d with no sandbox behind them any more: %s. Remove those in Desktop's SSH environment menu." % (len(stale), ", ".join(c["name"] for c in stale)) if stale else ", each with its sandbox"))


def cmd_sandbox(args):
    from .. import sandbox as _sandbox

    if args.action == "ls":
        listing = _sandbox.list_sandboxes()
        if args.json:
            print(json.dumps(listing, indent=2))
        else:
            _print_listing(listing)
        return 0 if listing["sbx"] and listing["signed_in"] else 1
    if args.action in ("stop", "rm"):
        if not args.names:
            print("oto: sandbox %s takes the sandbox name(s): oto sandbox %s <name> [<name> ...]" % (args.action, args.action), file=sys.stderr)
            return 1
        try:
            done = _sandbox.remove_sandboxes(args.names, stop_only=args.action == "stop")
        except _sandbox.SandboxError as e:
            if args.json:
                print(json.dumps({"ok": False, "problem": str(e), "fix": e.fix}, indent=2))
            else:
                print("oto: %s" % e, file=sys.stderr)
            return 2
        done["ok"] = not done["failed"] and not done["missing"]
        if args.json:
            print(json.dumps(done, indent=2))
        else:
            verb = "stopped" if args.action == "stop" else "removed"
            for name in done["done"]:
                print("%s the sandbox %s%s" % (verb, name, "" if args.action == "stop" else
                      " (its containers, state and secrets; the project and code folders on this computer stay)"))
            for name in done["missing"]:
                print("oto: no sandbox named %s (oto sandbox ls)" % name, file=sys.stderr)
            for failed in done["failed"]:
                print("oto: %s: %s" % (failed["name"], failed["error"]), file=sys.stderr)
            if done["done"] and args.action == "rm":
                print("  Claude Desktop still lists the SSH connection and any session on it: remove the connection in its SSH environment menu, archive or delete the sessions from the sidebar.")
        return 0 if done["ok"] else 1

    if args.action == "status":
        s = _sandbox.status(args.name)
        if args.json:
            print(json.dumps(s, indent=2))
        else:
            _print_status(s)
        return 0 if s["sandbox"] and s["oto"] and _sandbox.READY in s["oto"] and s["ssh"] else 1

    say = (lambda line: None) if args.json else (lambda line: print("  ... " + line, flush=True))
    if args.publish is not None:
        args.publish = [p for p in args.publish if p > 0]
    try:
        report = _sandbox.up(name=args.name, directory=args.dir, project_id=args.project_id, kit=args.kit,
                             approve=args.approve_anthropic, init_policy=args.init_policy, recreate=args.recreate,
                             check=args.check, wait=args.wait, say=say, allow_outside=args.allow_outside_plugins,
                             publish=args.publish if args.publish is not None else None)
    except _sandbox.SandboxError as e:
        if args.json:
            print(json.dumps({"ok": False, "problem": str(e), "fix": e.fix}, indent=2))
        else:
            print("oto: %s" % e, file=sys.stderr)
            if e.fix:
                print("  %s" % e.fix, file=sys.stderr)
        return 2
    report["ok"] = True
    report["next"] = [] if report["check"] else _sandbox.next_steps(report)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print("%s sandbox %s (kit %s)" % ("checked the" if report["check"] else "ready: the", report["name"], report["kit"]))
    for line in report["done"]:
        print("  - %s" % line)
    if report["check"]:
        for line in report["warnings"]:
            print("  warning: %s" % line)
    else:
        print("  folders: %s" % " and ".join(f for f in (report["project"], report["code"]) if f))
        print("  %s" % report["oto"])
        print("  outside plugins: %s" % report["outside_plugins_summary"])
        if report.get("ports"):
            print("  ports: %s published to this computer's localhost" % " and ".join("%d" % e["port"] for e in report["ports"]))
        for line in report["warnings"]:
            print("  warning: %s" % line)
        if not report["anthropic_signed_in"]:
            print("  note: sbx holds no Anthropic sign-in yet: Claude Code asks you to sign in (/login) the first time")
        print("")
        for line in report["next"]:
            print(line)
    return 0


def register(sub):
    p = sub.add_parser("sandbox", help="Claude Code with OTO in a Docker sandbox, for Claude Desktop or a terminal: "
                                       "up creates and sets it up, status says where it stands, ls lists them all, stop and rm clean up")
    p.add_argument("action", choices=["up", "status", "ls", "stop", "rm"],
                   help="up: check, create and set up; status: say where it stands; ls: every sandbox on this computer, "
                        "with Desktop's SSH connections to them; stop <name>...; rm <name>...: remove for good (the folders stay)")
    p.add_argument("names", nargs="*", help="for stop and rm: the sandbox name(s)")
    p.add_argument("--name", default="oto-sandbox", help="the sandbox's name; SSH reaches it as <name>.sbx (default oto-sandbox)")
    p.add_argument("--dir", help="the folder holding its project and code folders (default ~/<name>)")
    p.add_argument("--project-id", help="the Google Cloud project's id, given to the sandbox as PROJECT")
    p.add_argument("--kit", help="the kit to make it from (default ghcr.io/cynergis/oto-gcp:<this engine's version>)")
    p.add_argument("--approve-anthropic", action="store_true",
                   help="record the person's approval for the kit to use their Anthropic sign-in (ask them first)")
    p.add_argument("--init-policy", choices=["balanced", "deny-all", "allow-all"],
                   help="when no network policy is set yet, set this one (ask the person first)")
    p.add_argument("--allow-outside-plugins", action="store_true",
                   help="create the sandbox so that plugins from this computer, Claude Desktop and the claude.ai "
                        "account load in it too (by default only the sandbox's own plugins load)")
    p.add_argument("--publish", type=int, action="append", metavar="PORT",
                   help="for up: a sandbox port to publish to this computer's localhost, repeatable (default 8798 and 8799, "
                        "for oto serve inside; --publish 0 publishes none)")
    p.add_argument("--recreate", action="store_true", help="remove an existing sandbox of that name and create it again")
    p.add_argument("--check", action="store_true", help="say what up would do, change nothing")
    p.add_argument("--wait", type=int, default=600, help="seconds to wait for OTO to be ready inside (default 600)")
    p.add_argument("--json", action="store_true", help="machine-readable output, for a skill")
    p.set_defaults(func=cmd_sandbox)
