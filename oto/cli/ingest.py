# -*- coding: utf-8 -*-
"""`oto ingest`, `oto figures` and `oto survey`: the inbox into the corpus, and a map of what it holds."""
import os
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_ingest(args):

    from ..intake import pipeline

    project = _resolve(args)

    if args.ingest_command == "runs":
        manifests = pipeline.runs(project)
        if args.open_only:
            for m in pipeline.open_runs(project):
                print(m["run_id"])            # one id per line, for a script or a workflow
            return 0
        if not manifests:
            print("no ingest runs yet")
            return 0
        for m in manifests:
            s = m.get("summary") or {}
            state = "superseded" if m.get("superseded_by") else "complete" if m.get("completed") else ("OPEN" if s.get(pipeline.EXTRACTED) else "no extractions")
            print("  %-18s %-10s extracted %d, errors %d   started %s"
                  % (m.get("run_id"), state, s.get(pipeline.EXTRACTED, 0),
                     sum(v for k, v in s.items() if k != pipeline.EXTRACTED), m.get("started", "?")))
        return 0

    if args.ingest_command == "complete":
        try:
            result = pipeline.complete(project, run_id=args.run, force=args.force)
        except (pipeline.NotReady, pipeline.IngestLocked) as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        from .. import audit as _audit, work as _work
        _audit.append(project, "ingest complete", _work.identity(project), [], "applied",
                      detail="run %s: archived %s" % (result["run_id"], ", ".join(result["archived"]) or "nothing"))
        print("run %s complete: %d file(s) archived" % (result["run_id"], len(result["archived"])))
        for name in result["versioned"]:
            print("  %s: a different version was already archived; kept both, this one under archive/%s/"
                  % (name, result["run_id"]))
        for name in result["missing"]:
            print("  %s: was no longer in processing/; nothing moved" % name)
        if result["remaining"]:
            print("still in processing/ (other runs, or leftovers): %s" % ", ".join(result["remaining"]))
        else:
            print("processing/ is empty: nothing is owed")
        return 0

    print("oto ingest: %s" % project)
    try:
        result = pipeline.ingest(project, inbox=args.inbox, allow_personal_data=args.allow_personal_data,
                                 strict_privacy=args.strict_privacy, write_assets=not args.no_assets)
    except pipeline.IngestLocked as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1
    return 1 if (result["blocked"] or result["failed"]) else 0


def cmd_figures(args):
    from ..intake.figures import report, scan_corpus, worklist
    from ..intake.pipeline import DESCRIPTIONS_NAME

    project = _resolve(args)
    corpus = project.layout.corpus
    if not os.path.isdir(corpus):
        print("no corpus at %s. Run `oto ingest` first." % corpus)
        return 1
    curated = {}
    curated_path = os.path.join(project.data, DESCRIPTIONS_NAME)
    if os.path.exists(curated_path):
        import json
        with open(curated_path, encoding="utf-8") as f:
            curated = json.load(f)
    figures = scan_corpus(corpus, curated)
    print(report(figures))
    if args.worklist and figures:
        print("\nworklist written to %s" % worklist(figures, args.worklist))
    return 1 if figures and args.strict else 0


def cmd_survey(args):
    import json as _json

    from ..intake.survey import report, survey

    project = _resolve(args)
    corpus = project.layout.corpus
    if not os.path.isdir(corpus) or not any(n.endswith(".md") for n in os.listdir(corpus)):
        print("no corpus at %s. Run `oto ingest` first." % corpus)
        return 1
    if args.doc:
        from ..curate import session as _session
        from ..intake.survey import brief, brief_report

        slug = args.doc[:-3] if args.doc.endswith(".md") else args.doc
        candidate = _session.candidate(project) if _session.exists(project) else None
        try:
            result = brief(corpus, slug, _session.live(project), candidate, top=args.top)
        except FileNotFoundError:
            print("no document %s.md in the corpus. `oto query docs` lists what is there." % slug)
            return 1
        print(_json.dumps(result, indent=2, ensure_ascii=False) if args.json else brief_report(result))
        return 0
    off = [f.strip() for f in (args.off or "").split(",") if f.strip()]
    from ..intake.survey import FIXES
    unknown = [f for f in off if f not in FIXES]
    if unknown:
        print("oto: --off takes %s (got %s)" % (", ".join(FIXES), ", ".join(unknown)))
        return 1
    result = survey(corpus, top=args.top, min_count=args.min_count, off=off)
    if args.survey_command in ("accept", "reject", "decisions"):
        from ..intake import decisions as _decisions
        if args.survey_command == "decisions":
            print(_decisions.report(_decisions.read(project), _decisions.stats(_decisions.latest(project), result)))
            return 0
        try:
            entry = _decisions.record(project, result, args.term, args.survey_command + "ed",
                                      by=args.by, at=args.at, note=args.note, as_=getattr(args, "as"))
        except ValueError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        print("%s: %s, by %s on %s (stage %s%s)" % (entry["verdict"], entry["term"], entry["by"], entry["at"], entry["stage"],
                                                    (", via " + ", ".join(entry["via"])) if entry["via"] else ""))
        return 0
    if args.score or args.ablations:
        from ..intake import termscore
        gold_path = args.gold or os.path.join(project.data, "gold", "terms.jsonl")
        if not os.path.exists(gold_path):
            print("no gold term list at %s: write one (JSON Lines, `_meta` first, then {\"term\", \"aka\"}) to "
                  "measure what the survey surfaces." % gold_path)
            return 1
        try:
            meta, gold = termscore.load(gold_path)
        except ValueError as exc:
            print("oto: %s: %s" % (os.path.basename(gold_path), exc))
            return 1
        rows = termscore.ablations(corpus, gold, top=args.top, min_count=args.min_count) if args.ablations else None
        print(termscore.report(meta, result, gold, rows))
        return 0
    from ..intake import decisions as _decisions
    shown = _decisions.apply(result, _decisions.latest(project))
    if args.json:
        print(_json.dumps(shown, indent=2, ensure_ascii=False))
    else:
        print(report(shown))
    return 0


def register(sub):
    ingest = sub.add_parser("ingest", help="claim the inbox into a run and extract it into the corpus")
    ingest.add_argument("ingest_command", nargs="?", default="run", choices=["run", "complete", "runs"],
                        help="run (default) claims and extracts; complete archives a run once the "
                             "graph holds its facts; runs lists the manifests")
    project_arguments(ingest)
    ingest.add_argument("--inbox", default=None,
                        help="read this run from another directory; its files are copied, never moved")
    ingest.add_argument("--run", default=None, help="the run to complete (default: the latest open one)")
    ingest.add_argument("--open", dest="open_only", action="store_true",
                        help="for runs: print only the ids of runs whose files still wait in processing/")
    ingest.add_argument("--force", action="store_true",
                        help="complete even with a candidate open or a stale build")
    ingest.add_argument("--no-assets", action="store_true", help="skip writing page and slide images")
    ingest.add_argument("--allow-personal-data", action="store_true",
                        help="ingest even when the privacy scan finds blocking items")
    ingest.add_argument("--strict-privacy", action="store_true",
                        help="treat every privacy warning as blocking")
    ingest.set_defaults(func=cmd_ingest)

    figures = sub.add_parser("figures", help="report figures that have no description")
    project_arguments(figures)
    figures.add_argument("--worklist", default=None, help="write a worklist JSON to this path")
    figures.add_argument("--strict", action="store_true",
                         help="exit non-zero when any figure lacks a description")
    figures.set_defaults(func=cmd_figures)

    survey = sub.add_parser("survey", help="map the corpus: documents, headings, recurring terms")
    survey.add_argument("survey_command", nargs="?", default="map", choices=["map", "accept", "reject", "decisions"],
                        help="map (default) lists the candidates; accept and reject record a person's decision on one "
                             "(--term, --by); decisions shows them, with acceptance by stage and by fix")
    project_arguments(survey)
    survey.add_argument("--doc", default=None,
                        help="brief one document by slug: its terms, and which already resolve to entities")
    survey.add_argument("--top", type=int, default=40, help="how many terms and acronyms to list")
    survey.add_argument("--min-count", type=int, default=2,
                        help="a phrase must occur this often to be listed")
    survey.add_argument("--json", action="store_true", help="machine-readable")
    survey.add_argument("--score", action="store_true",
                        help="measure the candidates against the gold term list: recall, precision, review load")
    survey.add_argument("--ablations", action="store_true",
                        help="with --score: the same with each fix off in turn, and with none of them")
    survey.add_argument("--gold", default=None, help="the gold term list (default: <project>/gold/terms.jsonl)")
    survey.add_argument("--term", default=None, help="for accept and reject: the candidate (its term or a variant)")
    survey.add_argument("--by", default=None, help="for accept and reject: who decided (required)")
    survey.add_argument("--at", default=None, help="for accept and reject: the date, YYYY-MM-DD (default: today)")
    survey.add_argument("--note", default=None, help="for accept and reject: why")
    survey.add_argument("--as", default=None, choices=["class", "entity", "alias", "attribute", "value"],
                        help="for accept: what the term is for the vocabulary")
    survey.add_argument("--off", default=None,
                        help="fixes to leave out, comma-separated: header, codes, openers, plurals, lowercase, expansions")
    survey.set_defaults(func=cmd_survey)
