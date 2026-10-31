# -*- coding: utf-8 -*-
"""`oto arch`: the architecture graph for implementation. import reads a framework's model into a document
and a proposal in the architecture vocabulary (roadmap H1) through the adapter the framework's pack
provides (`--framework <name>`, oto/extensions.py); export writes the graph back the same way; migrate
rewrites a graph written with a framework's former attribute names;
map reads a code repository into a code map; compile runs what the project declares, on every merge (H2);
impact reports what a decision affects, the orphans and the untraced code (H4); measure records a report
as evidence of a requirement (H6)."""
import json
import os
import sys

from oto.cli._common import project_arguments, resolve as _resolve


def cmd_arch(args):
    import oto_architecture as _arch
    project = _resolve(args)
    from oto import extensions as _extensions
    if args.arch_command == "import":
        path = args.file
        framework = args.framework or _extensions.only_adapter()
        if not framework:
            print("oto: import takes --framework <name> (the packs on this machine provide %s) and --file <model>" % (", ".join(sorted(_extensions.adapters())) or "none"),
                  file=sys.stderr)
            return 1
        try:
            adapter = _extensions.adapter(framework)
        except _extensions.ExtensionError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        if not path:
            print("oto: import takes --file <model>, the %s model to read" % framework, file=sys.stderr)
            return 1
        try:
            done = adapter["read"](project, path, args.at, name=args.name, environment=args.environment)
        except _arch.ArchError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        rel = lambda p: os.path.relpath(p, project.data)  # noqa: E731
        print("%s: %d node(s), %d interface(s), %d relationship(s), %d control(s), %d flow(s) read from %s%s"
              % (done["doc"], done["nodes"], done["interfaces"], done["relationships"], done["controls"], done["flows"], os.path.basename(path),
                 " (%s)" % done["schema"] if done["schema"] else ""))
        print("  document %s (kept in %s)" % (rel(done["document"]), rel(done["archive"])))
        print("  proposal %s" % rel(done["proposal"]))
        if done["gaps"]:
            print("  what the model does not say (the gates will ask):")
            for gap in done["gaps"]:
                print("    %s" % gap)
        print("  next: oto curate start (if no candidate is open), oto curate add --from %s, oto curate check, oto curate apply --by <you> --note \"...\"; "
              "then oto arch export --framework %s writes it back" % (rel(done["proposal"]), framework))
        return 0
    if args.arch_command == "export":
        framework = args.framework or _extensions.only_adapter()
        if not framework:
            print("oto: export takes --framework <name> (the packs on this machine provide %s)" % (", ".join(sorted(_extensions.adapters())) or "none"), file=sys.stderr)
            return 1
        try:
            model = _extensions.adapter(framework)["write"](project)
        except (_arch.ArchError, _extensions.ExtensionError) as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        text = json.dumps(model, indent=2, ensure_ascii=False) + "\n"
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print("%s: %d node(s), %d relationship(s), %d flow(s)" % (args.out, len(model.get("nodes") or []), len(model.get("relationships") or []), len(model.get("flows") or [])))
        else:
            sys.stdout.write(text)
        return 0
    if args.arch_command == "migrate":
        framework = args.framework or _extensions.only_adapter()
        if not framework:
            print("oto: migrate takes --framework <name>, the framework whose former attribute names the graph carries", file=sys.stderr)
            return 1
        try:
            adapter = _extensions.adapter(framework)
        except _extensions.ExtensionError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        migrate = adapter.get("migrate")
        if not migrate:
            print("oto: the %s adapter has no migration" % framework, file=sys.stderr)
            return 1
        try:
            changed = migrate(project, args.by)
        except _arch.ArchError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        done = changed if isinstance(changed, dict) else {"nodes": int(changed), "declarations": 0, "terms": 0}
        total = sum(done.values())
        print("%d node(s), %d vocabulary declaration(s) and %d cited term(s) migrated to the architecture pack's neutral attributes%s"
              % (done["nodes"], done["declarations"], done["terms"], "; next: oto build" if total else ": nothing to do"))
        return 0
    if args.arch_command == "map":
        if not args.repo:
            print("oto: map takes --repo <path>, the code repository to read, and --repository repo.<id>, the estate's node for it", file=sys.stderr)
            return 1
        try:
            done = _arch.map_repo(project, args.repo, args.repository, args.at, name=args.name)
        except _arch.ArchError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        rel = lambda p: os.path.relpath(p, project.data)  # noqa: E731
        print("%s: %d module(s), %d commit(s) read from %s (%s)" % (done["doc"], done["modules"], done["commits"], args.repo, done["convention"]))
        print("  document %s (kept in %s)" % (rel(done["document"]), rel(done["archive"])))
        print("  proposal %s" % rel(done["proposal"]))
        if done["gaps"]:
            print("  what the code map cannot say:")
            for gap in done["gaps"]:
                print("    %s" % gap)
        print("  next: oto curate start (if no candidate is open), oto curate add --from %s, oto curate check, oto curate apply --by <you> --note \"...\"" % rel(done["proposal"]))
        return 0
    if args.arch_command == "compile":
        try:
            done = _arch.compile_project(project, args.at, args.by, note=args.note)
        except _arch.ArchError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        rel = lambda p: os.path.relpath(p, project.data)  # noqa: E731
        print("compiled %d proposal(s): %s" % (len(done["proposals"]), ", ".join(rel(p) for p in done["proposals"])))
        for gap in done["gaps"]:
            print("  noted: %s" % gap)
        print("  applied by %s on %s%s, and built" % (args.by, args.at, " (%s)" % args.note if args.note else ""))
        return 0
    if args.arch_command == "measure":
        if not args.nfr:
            print("oto: measure takes --nfr <requirement> and --from <report> or --value \"...\", with --at <date>", file=sys.stderr)
            return 1
        try:
            done = _arch.measure(project, args.nfr, args.at, value=args.value, path=args.from_, source=args.source)
        except _arch.ArchError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        rel = lambda p: os.path.relpath(p, project.data)  # noqa: E731
        print("%s: %s measured %s on %s (%s)" % (done["doc"], args.nfr, done["value"], args.at, done["format"]))
        print("  document %s (kept in %s)" % (rel(done["document"]), rel(done["archive"])))
        print("  proposal %s" % rel(done["proposal"]))
        print("  next: oto curate start (if no candidate is open), oto curate add --from %s, oto curate check, oto curate apply --by <you> --note \"...\"; "
              "then AR6 and arch_context show the measured value next to the budget" % rel(done["proposal"]))
        return 0
    if args.arch_command == "impact":
        from oto.curate import session as _session
        fmt = args.format or "text"
        if not (args.decision or args.orphans or args.untraced or args.files):
            print("oto: impact takes --decision <id|ADR-nnn>, --orphans, --untraced, or --files <paths...> (the files a pull request changed)", file=sys.stderr)
            return 1
        try:
            if args.files:
                sys.stdout.write(_arch.impact_of_files(project, args.files, fmt))
                return 0
            graph = _session.live(project)
            if args.decision:
                sys.stdout.write(_arch.render_impact(_arch.impact(graph, args.decision), fmt))
            if args.orphans:
                sys.stdout.write(_arch.render_orphans(_arch.orphans(graph), fmt))
            if args.untraced:
                sys.stdout.write(_arch.render_untraced(_arch.untraced(graph), fmt))
        except _arch.ArchError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        return 0
    print("oto: unknown arch command %r" % args.arch_command, file=sys.stderr)
    return 1


def register(sub):
    arch = sub.add_parser("arch", help="the architecture graph for implementation: a framework's model in through its adapter, the code map, compile on merge, impact")
    arch.add_argument("arch_command", choices=["import", "export", "migrate", "map", "compile", "impact", "measure"],
                      help="import reads a framework's model (--framework <name> --file <model>) into a document and a proposal through the framework's adapter; "
                           "export writes the graph back as that framework; migrate rewrites a graph written with a framework's former attribute names; "
                           "map reads a code repository (--repo, --repository) into a code-map document and a proposal; "
                           "compile runs what project.config.json declares under `arch` through the gates and builds; "
                           "impact reports what a decision affects, the orphans, the untraced code, or the decision records among changed files; "
                           "measure records a test, coverage or load-test report as evidence of a requirement")
    arch.add_argument("--framework", default=None, help="for import, export and migrate: the architecture framework, chosen among the adapters the packs provide (the only one is the default)")
    arch.add_argument("--file", default=None, help="for import: the model file to read, in the framework's form")
    arch.add_argument("--at", default=None, help="for import: the date the model was read, YYYY-MM-DD; never defaulted")
    arch.add_argument("--name", default=None, help="for import: the document's slug (default: the file's stem)")
    arch.add_argument("--environment", default=None, help="for import: the Environment the estate declares, for what the model deploys nowhere")
    arch.add_argument("--out", default=None, help="for export: write the model here instead of printing it")
    arch.add_argument("--repo", default=None, help="for map: the code repository to read (a git checkout records its commits)")
    arch.add_argument("--repository", default=None, help="for map: the Repository node the estate declares for it, repo.<id>")
    arch.add_argument("--by", default=None, help="for compile: who compiles (the workflow names itself); for migrate: who migrates")
    arch.add_argument("--note", default=None, help="for compile: what to record with the apply, such as the merge's sha")
    arch.add_argument("--decision", default=None, help="for impact: the decision, decision.<id> or its ADR id")
    arch.add_argument("--orphans", action="store_true", help="for impact: the systems, components, stores and interfaces no relationship reaches")
    arch.add_argument("--untraced", action="store_true", help="for impact: the modules nothing implements and the components with no module")
    arch.add_argument("--files", nargs="*", default=None, help="for impact: files a pull request changed; every decision record among them is reported")
    arch.add_argument("--format", default=None, choices=["text", "markdown"], help="for impact: text (default) or markdown, for a pull request comment")
    arch.add_argument("--nfr", default=None, help="for measure: the requirement with a budget, nfr.<id>")
    arch.add_argument("--from", dest="from_", default=None, help="for measure: a JUnit XML, coverage.py XML or k6 summary JSON report")
    arch.add_argument("--value", default=None, help="for measure: the value stated, when there is no report")
    arch.add_argument("--source", default=None, help="for measure: where the report can be seen, a URL")
    project_arguments(arch)
    arch.set_defaults(func=cmd_arch)
