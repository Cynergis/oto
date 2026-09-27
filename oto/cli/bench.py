# -*- coding: utf-8 -*-
"""`oto bench`: measure answer quality against a gold question set."""
import os
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_bench(args):
    from ..bench import gold as _gold, run as _run, systems as _systems

    project = _resolve(args)
    path = args.gold or os.path.join(project.data, "gold", "questions.jsonl")

    if args.bench_command == "start":
        try:
            written = _gold.write_starter(path)
        except FileExistsError:
            print("oto: %s already exists" % path, file=sys.stderr)
            return 1
        print("wrote %s" % written)
        print("Fill in `_meta` honestly: a number from a set with no recorded provenance is not "
              "evidence.")
        return 0

    if not os.path.exists(path):
        print("oto: no gold set at %s. Run `oto bench start` to start one." % path,
              file=sys.stderr)
        return 1

    if args.bench_command == "add":
        import json as _json

        if not args.source:
            print("oto: add needs --from <questions.json> (repeatable)", file=sys.stderr)
            return 1
        total = 0
        for source in args.source:
            try:
                with open(source, encoding="utf-8") as f:
                    payload = _json.load(f)
            except (OSError, ValueError) as exc:
                print("oto: cannot read %s: %s" % (source, exc), file=sys.stderr)
                return 1
            questions = payload.get("questions") if isinstance(payload, dict) else payload
            added, problems = _gold.append(path, questions or [], source_doc=(payload or {}).get("source_doc")
                                           if isinstance(payload, dict) else None, kind=args.type)
            if problems:
                print("%s: not added, %d problem(s):" % (os.path.basename(source), len(problems)))
                for problem in problems:
                    print("  %s" % problem)
                return 1
            print("%s: added %d question(s)" % (os.path.basename(source), len(added)))
            total += len(added)
        print("gold set now holds %d question(s). Its _meta says who authored them; keep it honest."
              % len(_gold.load(path)[1]))
        return 0

    try:
        meta, questions = _gold.load(path)
    except ValueError as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1

    problems = _gold.validate(meta, questions)
    if args.bench_command == "validate":
        if problems:
            print("%d problem(s) in %s:" % (len(problems), os.path.basename(path)))
            for problem in problems:
                print("  %s" % problem)
            return 1
        print("gold set is usable: %d question(s)" % len(questions))
        print()
        print(_gold.describe(meta))
        return 0

    if problems and not args.force:
        print("oto: the gold set has %d problem(s). Run `oto bench validate`, or pass --force."
              % len(problems), file=sys.stderr)
        return 1

    database = project.layout.database
    if not os.path.exists(database):
        print("oto: no database at %s. Run `oto build` first." % database, file=sys.stderr)
        return 1

    names = [n.strip() for n in args.systems.split(",") if n.strip()]
    built, unknown, skipped = _systems.build(database, names, ablations=args.ablations,
                                             progress=lambda m: print("  %s" % m))
    for name in unknown:
        print("oto: unknown system %r, skipped" % name, file=sys.stderr)
    if not built:
        print("oto: no systems to run", file=sys.stderr)
        return 1

    rows = _run.run(database, questions, built, k=args.k)
    summary = _run.aggregate(rows)
    text = _run.report(meta, questions, summary, args.k, skipped=skipped)
    print(text)

    if args.out:
        import json as _json
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            _json.dump({"meta": meta, "k": args.k, "summary": summary, "rows": rows}, f,
                       indent=2, ensure_ascii=False)
        print("\nmachine-readable results: %s" % args.out)
    return 0


def register(sub):
    bench = sub.add_parser("bench", help="measure answer quality against a gold question set")
    bench.add_argument("bench_command", nargs="?", default="run",
                       choices=["run", "validate", "start", "add"],
                       help="run scores the gold set; validate checks it; start writes a starter file; "
                            "add appends questions from a file")
    bench.add_argument("--from", dest="source", action="append", default=None,
                       help="for add: a JSON file {\"source_doc\": ..., \"questions\": [...]} (repeatable)")
    bench.add_argument("--type", default="factual", help="for add: default question type")
    project_arguments(bench)
    bench.add_argument("--gold", default=None, help="gold set path (default: <project>/gold/questions.jsonl)")
    bench.add_argument("--systems", default="oto,lexical,dense",
                       help="comma-separated systems to compare. `dense` is the embedding baseline "
                            "and needs the bench extra; it is reported as unmeasured if absent")
    bench.add_argument("--ablations", action="store_true",
                       help="also run OTO with the graph off and with time off, to show each pillar "
                            "defends the metric it claims to")
    bench.add_argument("--k", type=int, default=5, help="k for coverage")
    bench.add_argument("--out", default=None, help="write machine-readable results here")
    bench.add_argument("--force", action="store_true", help="run despite gold-set problems")
    bench.set_defaults(func=cmd_bench)
