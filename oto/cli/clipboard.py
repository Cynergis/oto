# -*- coding: utf-8 -*-
"""`oto clipboard`: the selected text, read into the conversation under the engine's rules."""
import json
import sys

from .. import clipboard as _clipboard


def cmd_clipboard(args):
    if args.when_asked:
        try:
            event = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            event = {}
        if not _clipboard.asked((event or {}).get("prompt") if isinstance(event, dict) else ""):
            return 0
    try:
        text, source = _clipboard.read()
    except _clipboard.NoClipboard as exc:
        print(str(exc))
        return 0
    result = _clipboard.check(text, max_chars=args.max_chars)
    if result["refused"]:
        print("The clipboard was not read into the conversation: it holds %s. Remove it and copy again."
              % ", ".join(result["refused"]))
        return 1
    result["source"] = source
    print(_clipboard.render(result))
    return 0


def register(sub):
    p = sub.add_parser("clipboard", help="the selected or copied text, as data for the conversation: capped, scanned "
                                         "for credentials, and only when there is a clipboard to read")
    p.add_argument("--when-asked", action="store_true",
                   help="read a UserPromptSubmit event on stdin and print only when the prompt means the clipboard")
    p.add_argument("--max-chars", type=int, default=_clipboard.MAX_CHARS, help="the cap (default %d)" % _clipboard.MAX_CHARS)
    p.set_defaults(func=cmd_clipboard)
