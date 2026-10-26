# -*- coding: utf-8 -*-
"""`oto connectors`: the stores a build can be published to, and the conformance kit run against one."""
import os
import sys
import tempfile

from .. import connectors as _connectors
from ..connectors import conformance as _conformance
from ._common import project_arguments, resolve as _resolve


def cmd_connectors(args):
    if args.connectors_command == "list":
        print("connectors (oto build publishes through them; a connector is listed only with a passing kit):")
        for name in _connectors.available():
            manifest = _connectors.get(name).MANIFEST
            caps = ", ".join(k for k, v in sorted(manifest["capabilities"].items()) if v)
            print("  %-8s %s  modes %s  %s  capabilities: %s  auth: %s  conformance %s"
                  % (name, manifest["version"], ", ".join(manifest["modes"]), manifest["query_language"], caps or "none",
                     ", ".join(manifest["auth"]), manifest["conformance"]))
        return 0

    connector = _connectors.get(args.which)
    if connector is None:
        print("oto: no connector %r; shipped: %s" % (args.which, ", ".join(_connectors.available())), file=sys.stderr)
        return 1
    project = _resolve(args)
    if not os.path.exists(os.path.join(project.layout.graph, "knowledge-graph.json")):
        print("oto: the kit needs a built graph: run `oto build` first", file=sys.stderr)
        return 1
    scratch = tempfile.mkdtemp(prefix="oto-kit-")
    try:
        if args.which == "sqlite":
            def sessions(name):
                return connector.connect({"path": os.path.join(scratch, "%s.db" % name)})
        else:
            settings = connector.settings(project)

            def sessions(name):
                if "project" in settings and name != "overlay":
                    return connector.connect(dict(settings, project="%s-kit-%s" % (settings["project"], name)))
                return connector.connect(settings)
        result = _conformance.run(connector, project, sessions)
    finally:
        import shutil
        shutil.rmtree(scratch, ignore_errors=True)
    print(_conformance.report(result))
    return 0 if result["passed"] else 1


def register(sub):
    connectors = sub.add_parser("connectors", help="the stores a build publishes to, and the conformance kit")
    connectors.add_argument("connectors_command", nargs="?", default="list", choices=["list", "check"],
                            help="list (the default) shows each connector's manifest; check <name> runs the kit against the project's build")
    connectors.add_argument("which", nargs="?", default=None, help="for check: the connector's name")
    project_arguments(connectors)
    connectors.set_defaults(func=cmd_connectors)
