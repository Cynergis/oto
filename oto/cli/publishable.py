# -*- coding: utf-8 -*-
"""`oto publishable`: refuse to publish a repository that names a client or holds a credential."""
import os


def cmd_publishable(args):
    from ..validate.publishable import scan
    return scan(os.path.abspath(args.directory), strict=args.strict)


def register(sub):
    p = sub.add_parser("publishable",
                       help="scan a repository for client names (OTO_DENY_TERMS, .oto-denylist) and credentials")
    p.add_argument("directory", nargs="?", default=".", help="the repository to scan (default: the current directory)")
    p.add_argument("--strict", action="store_true", help="fail when no deny terms are configured (use in CI)")
    p.set_defaults(func=cmd_publishable)
