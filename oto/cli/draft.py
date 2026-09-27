# -*- coding: utf-8 -*-
"""`oto draft`: a model drafts one document's proposal, for a person and the gates to review."""
import os
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_draft(args):
    from .. import draft as _draft

    project = _resolve(args)
    slug = args.slug[:-3] if args.slug.endswith(".md") else args.slug
    try:
        path, proposal, report, usage = _draft.run(project, slug, model=args.model or _draft.DEFAULT_MODEL, force=args.force)
    except _draft.DraftError as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1
    root = os.path.dirname(project.src)
    print("drafted %s with %s" % (os.path.relpath(path, root), proposal["drafted_by"]["model"]))
    if usage is not None:
        print("  tokens: %s in, %s out" % (getattr(usage, "input_tokens", "?"), getattr(usage, "output_tokens", "?")))
    print("  %d node(s), %d edge(s); dry run against the %s: +%d, %d merged, %d updated, %d suspect(s)"
          % (len(proposal.get("nodes") or []), len(proposal.get("edges") or []),
             "candidate" if os.path.exists(os.path.join(root, "graph.candidate.json")) else "live graph",
             len(report["added"]), len(report["merged"]), len(report["updated"]), len(report["suspects"])))
    for nid, others in report["suspects"][:args.show]:
        print("    SUSPECT  %-28s same name as %s" % (nid, ", ".join(others)))
    from ..curate import batch as _batch
    for reason in _batch.refused(report)[:args.show]:
        print("    WOULD REFUSE  %s" % reason)
    r = proposal.get("report") or {}
    for key in ("needs_vocabulary", "contradictions", "inferences", "unsure"):
        for item in (r.get(key) or [])[:args.show]:
            print("    %-16s %s" % (key.replace("_", " ") + ":", item))
    print("A first draft. Read the document against it, then: oto curate add --from %s --dry-run"
          % os.path.relpath(path, root))
    return 0


def register(sub):
    draft = sub.add_parser("draft", help="a model drafts one document's proposal (needs the draft extra)")
    project_arguments(draft)
    draft.add_argument("slug", help="the document's slug in the corpus")
    draft.add_argument("--model", default=None, help="model id (default: claude-opus-5)")
    draft.add_argument("--force", action="store_true", help="redraft over an existing proposal file")
    draft.add_argument("--show", type=int, default=8, help="how many items to list per section")
    draft.set_defaults(func=cmd_draft)
