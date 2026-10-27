#!/usr/bin/env python3
"""The engine plugin's PreToolUse guard (roadmap E3): a session that carries a policy snapshot
(`.factory/policy.json`, written by `oto policy snapshot --agent <id> --principal <id>`) may write
only where the snapshot permits. No snapshot: the guard allows everything. A snapshot that cannot
be read or trusted blocks every write. Exit 2 refuses the tool and the reason on stderr reaches the
agent; a refusal is recorded beside the snapshot for the audit log. Plain Python, no engine needed
on the machine that runs it; the reader is `policy_snapshot.py` beside this file.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import policy_snapshot  # noqa: E402


def refuse(reason):
    sys.stderr.write("policy guard: %s\n" % reason)
    sys.exit(2)


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    policy_snapshot.guard(payload, refuse)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
