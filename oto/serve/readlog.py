# -*- coding: utf-8 -*-
"""Who read what (docs/plans/people-and-graphs.md, phase 5). Refused reads were always recorded; this records the permitted ones.

    OTO_READ_LOG=stderr     one JSON line per read on stderr, which Cloud Run sends to Cloud Logging. `oto serve --iap` sets this unless told otherwise
    OTO_READ_LOG=<path>     one JSON line per read in that file

Off otherwise. It records who, which tool and what they asked, shortened, and never the answer. Stdout is never used: a stdio server speaks JSON-RPC there.
"""
import datetime
import json
import os
import sys
import threading

ENV = "OTO_READ_LOG"
MAX_VALUE = 300
_LOCK = threading.Lock()


def _short(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= MAX_VALUE else text[:MAX_VALUE - 3] + "..."


def record(caller, tool, arguments, ok, graph=None):
    """One line for one read, when the log is on. Never raises: a log that can't be written mustn't take the answer with it, and says so on stderr."""
    target = (os.environ.get(ENV) or "").strip()
    if not target:
        return
    caller = caller or {}
    row = {"severity": "INFO", "event": "oto.read", "at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
           "principal": caller.get("principal") or "(nobody named)", "agent": caller.get("agent"), "graph": graph, "tool": tool,
           "arguments": {k: _short(v) for k, v in (arguments or {}).items()}, "ok": bool(ok)}
    line = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
    try:
        with _LOCK:
            if target == "stderr":
                sys.stderr.write(line)
                sys.stderr.flush()
            else:
                with open(target, "a", encoding="utf-8", newline="\n") as f:
                    f.write(line)
    except OSError as exc:
        print("oto serve: the read log can't be written: %s" % exc, file=sys.stderr)
