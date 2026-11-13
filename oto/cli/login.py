# -*- coding: utf-8 -*-
"""`oto login`, `oto whoami`, `oto logout`: this computer signed in to an OTO portal (oto/portal.py,
docs/plans/portal-sign-in.md)."""
import json
import sys


def _fail(exc):
    print("oto: %s" % exc, file=sys.stderr)
    if getattr(exc, "fix", ""):
        print("  %s" % exc.fix, file=sys.stderr)
    return 1


def _lines(who):
    tenant = (who.get("tenant") or {}).get("name") or "a tenant with no name"
    lines = ["%s, in %s" % (who.get("email") or "signed in", tenant),
             "  portal        %s" % who.get("portal")]
    if who.get("organisation"):
        lines += ["  organisation  %s" % who["organisation"], "  registry      %s" % who.get("registry")]
    else:
        lines.append("  organisation  none yet: %s isn't linked to a GitHub organisation" % tenant)
    if who.get("signed_in_until"):
        lines.append("  signed in until %s" % str(who["signed_in_until"])[:10])
    return lines


def cmd_login(args):
    from .. import portal
    browse = None
    if not args.no_browser:
        import webbrowser
        browse = webbrowser.open
    try:
        who = portal.login(portal=args.portal, say=print, browse=browse)
    except portal.PortalError as exc:
        return _fail(exc)
    except KeyboardInterrupt:
        print("\noto: stopped; this computer isn't signed in", file=sys.stderr)
        return 1
    print("Signed in: " + "\n".join(_lines(who)))
    return 0


def cmd_whoami(args):
    from .. import portal
    try:
        who = portal.whoami()
    except portal.PortalError as exc:
        return _fail(exc)
    if who is None:
        if args.json:
            print("null")
        else:
            print("oto: this computer isn't signed in to a portal\n  run `oto login --portal https://<your portal>`", file=sys.stderr)
        return 1
    print(json.dumps(who, indent=2, ensure_ascii=False) if args.json else "\n".join(_lines(who)))
    return 0


def cmd_logout(args):
    from .. import portal
    try:
        was = portal.logout()
    except portal.PortalError as exc:
        return _fail(exc)
    print("Signed out: this computer holds no session now" if was else "This computer wasn't signed in")
    return 0


def register(sub):
    login = sub.add_parser("login", help="sign this computer in to your OTO portal, through your browser")
    login.add_argument("--portal", default=None, metavar="URL",
                       help="the portal's address, https://<your portal> (default: $OTO_PORTAL, or the portal this computer last signed in to)")
    login.add_argument("--no-browser", action="store_true", help="don't open the page; print its address only, to open on another device")
    login.set_defaults(func=cmd_login)

    whoami = sub.add_parser("whoami", help="who this computer is signed in as: the person, the tenant, its GitHub organisation and registry")
    whoami.add_argument("--json", action="store_true", help="machine-readable")
    whoami.set_defaults(func=cmd_whoami)

    logout = sub.add_parser("logout", help="end this computer's session at the portal and remove it from this computer")
    logout.set_defaults(func=cmd_logout)
