# -*- coding: utf-8 -*-
"""`oto vet`: audit the graph against the documents the corpus still holds."""
import os
import sys

from ._common import project_arguments, resolve as _resolve, today as _today


def cmd_vet(args):
    """Audit the graph against the documents the corpus actually holds."""
    import json as _json

    from ..curate import session as _session
    from ..curate import vet as _prov

    project = _resolve(args)
    try:
        with open(project.graph_path, encoding="utf-8") as f:
            graph = _json.load(f)
    except (OSError, ValueError) as exc:
        print("oto: cannot read %s: %s" % (project.graph_path, exc), file=sys.stderr)
        return 1

    corpus = _prov.corpus_slugs(project)
    if not corpus:
        print("oto: no documents in %s. Run `oto ingest` first: with an empty corpus every citation "
              "looks dead and the audit would tell you to delete the whole graph."
              % project.layout.corpus, file=sys.stderr)
        return 1

    extra = [s.strip() for s in (args.vetted or "").split(",") if s.strip()]
    report = _prov.audit(graph, corpus, extra)
    remove = [s.strip() for s in (args.remove or "").split(",") if s.strip()]
    actions, unknown = _prov.plan(graph, report, remove=remove, fallback=args.fallback)

    if args.json:
        print(_json.dumps({"report": report, "actions": actions, "unknown_removals": unknown},
                          indent=2, sort_keys=True))
        return 0

    total = len(graph.get("nodes", []))
    print("%d documents in the corpus, %d nodes in the graph" % (len(corpus), total))
    if extra:
        print("accepting %d extra source tag(s) you named: %s" % (len(extra), ", ".join(extra)))
    print()

    if report["curation"]:
        print("Curation markers, not documents (never treated as dead):")
        for tag, count in sorted(report["curation"].items()):
            print("  %-40s %d node(s)" % (tag, count))
        print()

    if not report["dead"]:
        print("Every citation in the graph resolves to a document in the corpus.")
        return 0

    print("%d source tag(s) the corpus does not hold:" % len(report["dead"]))
    for tag, count in sorted(report["dead"].items(), key=lambda kv: (-kv[1], kv[0])):
        print("  %-40s %d node(s)" % (tag, count))
    print()
    print("Before deleting anything, check these against your filenames. A tag that does not match a")
    print("file is usually an alias for one that does, and treating an alias as a phantom deletes")
    print("real knowledge. Whitelist the aliases with --vetted, then look at what is left.")
    print()
    print("%d node(s) keep at least one live citation: a citation to strip, not a fact to lose."
          % len(report["mixed"]))
    print("%d node(s) cite nothing that exists. Those are the facts at risk:" % len(report["pure"]))
    print()

    for key, heading in (("removed", "would be REMOVED (you named them)"),
                         ("resourced", "would be RE-SOURCED to a neighbour that cites a live document"),
                         ("fallback", "would fall back to the source you named"),
                         ("orphaned", "would keep NO citation, so they are left alone for you to decide")):
        items = actions[key]
        if not items:
            continue
        print("  %d %s:" % (len(items), heading))
        for item in items[:12]:
            extra_detail = ""
            if item.get("to"):
                extra_detail = " -> %s" % ", ".join(item["to"])
            elif item.get("cites"):
                extra_detail = " (cites %s)" % ", ".join(item["cites"])
            print("    %-38s %s%s" % (item["id"], item.get("label") or "", extra_detail))
        if len(items) > 12:
            print("    ... and %d more" % (len(items) - 12))
        print()

    if unknown:
        print("oto: --remove named %d id(s) that are not at risk: %s"
              % (len(unknown), ", ".join(unknown)), file=sys.stderr)
        print("Removing a node that still has a live citation is not a provenance fix. Use "
              "`oto curate` for that.", file=sys.stderr)
        return 1

    if actions["removed"]:
        dangling = _prov.orphaned_edges(graph, [e["id"] for e in actions["removed"]])
        if dangling:
            print("Removing those %d node(s) would drop %d edge(s)."
                  % (len(actions["removed"]), len(dangling)))
            print()

    if not args.apply:
        print("Nothing was written. Re-run with --apply to produce a candidate graph.")
        return 0

    fresh = _prov.rewrite(graph, report, actions, args.as_of or _today())
    path = _session.candidate_path(project)
    if os.path.exists(path) and not args.force:
        print("oto: a curate session is already open at %s. Finish or abort it first, or pass "
              "--force." % os.path.basename(path), file=sys.stderr)
        return 1
    fresh["_about"] = ("A CANDIDATE produced by `oto vet --apply`. Dead citations stripped, facts "
                       "re-sourced where a neighbour attests them. Review with `oto curate check`, "
                       "then `oto curate apply` or `oto curate abort`.")
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(fresh, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    print("wrote %s" % os.path.basename(path))
    print()
    print("Nothing is live yet. This goes through the normal gates:")
    print("  1) oto curate check     what would change, and whether it contradicts anything")
    print("  2) oto curate apply     promote it, keeping the previous graph")
    print("  3) oto build            rebuild every layer")
    print("Then re-run `oto vet` and expect no dead tags.")
    return 0


def register(sub):
    vet = sub.add_parser("vet", help="audit the graph against the documents the corpus holds")
    project_arguments(vet)
    vet.add_argument("--vetted", default="",
                     help="comma-separated source tags to accept even though no file matches; use "
                          "this for aliases, after checking them against your filenames")
    vet.add_argument("--remove", default="",
                     help="comma-separated node ids to delete. Nothing is deleted unless you name "
                          "it here: losing a fact is worse than carrying a citation you can fix")
    vet.add_argument("--fallback", default=None,
                     help="source tag for facts no neighbour attests, instead of leaving them")
    vet.add_argument("--as-of", dest="as_of", default=None,
                     help="date to stamp on every changed node (default: today)")
    vet.add_argument("--apply", action="store_true",
                     help="write a candidate graph; review it with `oto curate check`")
    vet.add_argument("--force", action="store_true", help="overwrite an open curate session")
    vet.add_argument("--json", action="store_true", help="machine-readable report")
    vet.set_defaults(func=cmd_vet)
