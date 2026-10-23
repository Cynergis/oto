# -*- coding: utf-8 -*-
"""`oto lexicon`: an embedding model proposes what a word means; a named person accepts or rejects."""
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_lexicon(args):
    from ..model import lexicon as _lexicon

    project = _resolve(args)
    command = args.lexicon_command

    if command == "suggest":
        terms = [t.strip() for t in args.terms.split(",")] if args.terms else None
        try:
            from ..bench import dense as _dense
            result = _lexicon.suggest(project, terms=terms, min_similarity=args.min_similarity,
                                      min_margin=args.min_margin, top=args.top, model=_dense.MODEL_NAME)
        except RuntimeError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        print("%d suggestion(s), written to %s; nothing is in the lexicon until someone accepts it."
              % (len(result["suggestions"]), _lexicon.SUGGESTIONS))
        _print_suggestions(result["suggestions"])
        if result["unclear"]:
            print("unclear, close to two entities (less than %.2f apart): a person names the target with --target"
                  % args.min_margin)
            for item in result["unclear"]:
                print("  %-28s ? %s" % (item["term"], "   ".join("%s %.2f" % (c["target"], c["similarity"])
                                                           for c in item["candidates"])))
        for label, key in (("already a name in the graph", "known"),
                           ("a term of the vocabulary, not an entity (kg_define answers it)", "vocabulary"),
                           ("a document's own title", "documents"),
                           ("below the %.2f similarity floor, not proposed"
                                                                      % args.min_similarity, "unmatched"),
                           ("rejected before, not proposed again", "rejected")):
            if result[key]:
                print("%s: %s" % (label, ", ".join(result[key])))
        if result["suggestions"]:
            print("\nAccept one with: oto lexicon accept --term \"<term>\" --by \"<you>\"  (then oto build)")
        return 0

    if command == "list":
        entries = _lexicon.load(project)["entries"]
        print("lexicon: %d entr%s" % (len(entries), "y" if len(entries) == 1 else "ies"))
        for entry in entries:
            print("  %-28s -> %s  [%s]  %s" % (entry.get("term"), ", ".join(entry.get("targets") or []) or "-",
                                             entry.get("status", "current"), entry.get("note", "")))
        waiting = _lexicon.pending(project)
        print("\nsuggestions waiting for a person: %d" % len(waiting))
        _print_suggestions(waiting)
        return 0

    try:
        if command == "accept":
            entry = _lexicon.accept(project, args.term, args.by, target=args.target, at=args.at)
            print("lexicon: %s -> %s  (%s)" % (entry["term"], ", ".join(entry["targets"]), entry["note"]))
            print("Run `oto build`: the next build carries it, and every lookup binds it.")
        else:
            record = _lexicon.reject(project, args.term, args.by, target=args.target, at=args.at)
            print("rejected: %s -> %s, by %s on %s; it will not be suggested again."
                  % (record["term"], record["target"], record["by"], record["at"]))
    except ValueError as exc:
        print("oto: %s" % exc, file=sys.stderr)
        return 1
    return 0


def _print_suggestions(suggestions):
    for s in suggestions:
        runner = s.get("runner_up")
        print("  %-28s -> %-28s %.2f%s%s" % (
            s["term"], "%s (%s)" % (s.get("target_label"), s["target"]), s["similarity"],
            ("   next: %s %.2f" % (runner["target"], runner["similarity"])) if runner else "",
            ("   in: %s" % ", ".join(s["seen_in"])) if s.get("seen_in") else ""))


def register(sub):
    from ..model.lexicon import DEFAULT_MIN_MARGIN, DEFAULT_MIN_SIMILARITY
    lexicon = sub.add_parser("lexicon", help="propose lexicon entries from an embedding model; a named person accepts them")
    lexicon.add_argument("lexicon_command", nargs="?", default="list", choices=["suggest", "list", "accept", "reject"],
                         help="suggest proposes targets for words no name binds (written to lexicon.suggestions.json, "
                              "never to the lexicon); list shows the lexicon and what waits; accept --term --by takes one "
                              "in; reject --term --by refuses one")
    project_arguments(lexicon)
    lexicon.add_argument("--terms", default=None,
                         help="for suggest: comma-separated words to propose for (default: recurring corpus terms no name binds)")
    lexicon.add_argument("--term", default=None, help="for accept and reject: the word")
    lexicon.add_argument("--target", default=None, help="for accept and reject: the entity id (default: the suggestion's)")
    lexicon.add_argument("--by", default=None, help="for accept and reject: who decided (required)")
    lexicon.add_argument("--at", default=None, help="for accept and reject: the date, YYYY-MM-DD (default: today)")
    lexicon.add_argument("--min-similarity", dest="min_similarity", type=float, default=DEFAULT_MIN_SIMILARITY,
                         help="for suggest: propose only at or above this cosine similarity (default %.2f)" % DEFAULT_MIN_SIMILARITY)
    lexicon.add_argument("--min-margin", dest="min_margin", type=float, default=DEFAULT_MIN_MARGIN,
                         help="for suggest: propose only when the best target leads the runner-up by this much "
                              "(default %.2f); closer calls are listed as unclear" % DEFAULT_MIN_MARGIN)
    lexicon.add_argument("--top", type=int, default=40, help="for suggest: how many corpus terms to consider")
    lexicon.set_defaults(func=cmd_lexicon)
