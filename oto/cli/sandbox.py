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
        print("  SSH            %s" % ("%s.sbx" % s["name"] if s["ssh"] else "not set up"))
    elif s["sbx"] and s["signed_in"]:
        print("  sandbox        not created: oto sandbox up --name %s" % s["name"])


def cmd_sandbox(args):
    from .. import sandbox as _sandbox

    if args.action == "status":
        s = _sandbox.status(args.name)
        if args.json:
            print(json.dumps(s, indent=2))
        else:
            _print_status(s)
        return 0 if s["sandbox"] and s["oto"] and _sandbox.READY in s["oto"] and s["ssh"] else 1

    say = (lambda line: None) if args.json else (lambda line: print("  ... " + line, flush=True))
    try:
        report = _sandbox.up(name=args.name, directory=args.dir, project_id=args.project_id, kit=args.kit,
                             approve=args.approve_anthropic, init_policy=args.init_policy, recreate=args.recreate,
                             check=args.check, wait=args.wait, say=say)
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
                                       "up creates and sets it up, status says where it stands")
    p.add_argument("action", choices=["up", "status"], help="up: check, create and set up; status: say where it stands")
    p.add_argument("--name", default="oto-sandbox", help="the sandbox's name; SSH reaches it as <name>.sbx (default oto-sandbox)")
    p.add_argument("--dir", help="the folder holding its project and code folders (default ~/<name>)")
    p.add_argument("--project-id", help="the Google Cloud project's id, given to the sandbox as PROJECT")
    p.add_argument("--kit", help="the kit to make it from (default ghcr.io/cynergis/oto-gcp:<this engine's version>)")
    p.add_argument("--approve-anthropic", action="store_true",
                   help="record the person's approval for the kit to use their Anthropic sign-in (ask them first)")
    p.add_argument("--init-policy", choices=["balanced", "deny-all", "allow-all"],
                   help="when no network policy is set yet, set this one (ask the person first)")
    p.add_argument("--recreate", action="store_true", help="remove an existing sandbox of that name and create it again")
    p.add_argument("--check", action="store_true", help="say what up would do, change nothing")
    p.add_argument("--wait", type=int, default=600, help="seconds to wait for OTO to be ready inside (default 600)")
    p.add_argument("--json", action="store_true", help="machine-readable output, for a skill")
    p.set_defaults(func=cmd_sandbox)
