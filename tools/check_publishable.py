# -*- coding: utf-8 -*-
"""Refuse to publish if client-identifying material or a credential is present.

This repository is public. It holds the engine. Client names, programme names, private repository
names and credentials belong in a private project repository, never here.

The vendor's own name is fine: Cynergis AI publishes this repository, so a copyright line and a contact
address are expected. A CLIENT's name is not, anywhere, including documentation and comments.

**The deny terms are not stored in this repository.** Writing "do not mention client X" into a public
file names client X. Terms are supplied from outside:

  OTO_DENY_TERMS   comma-separated terms, e.g. in a CI secret
  .oto-denylist    one term per line, gitignored, for local runs

With no terms supplied the scan still runs, but it can only catch credentials and generic private
repository references. It says so plainly, so a misconfigured CI job cannot pass silently while
appearing to check names.

  python tools/check_publishable.py [--strict]

`--strict` fails when no deny terms are configured. Use it in CI.
"""
import argparse
import os
import re
import sys

SECRET_PATTERNS = [
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "GitHub personal access token"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "GitHub fine-grained token"),
    (re.compile(r"sk-ant-[A-Za-z0-9-]{20,}"), "Anthropic API key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id"),
]

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", "dist", "build", "instances"}
BINARY_EXT = {".db", ".png", ".jpg", ".jpeg", ".pdf", ".pptx", ".docx", ".xlsx", ".zip", ".gz"}
SELF = "tools/check_publishable.py"
DENYLIST_FILE = ".oto-denylist"


def load_terms(root):
    """Deny terms from the environment, then a gitignored local file. Never from tracked source."""
    raw = os.environ.get("OTO_DENY_TERMS", "")
    terms = [t.strip() for t in raw.split(",") if t.strip()]
    local = os.path.join(root, DENYLIST_FILE)
    if os.path.exists(local):
        with open(local, encoding="utf-8") as f:
            terms += [l.strip() for l in f if l.strip() and not l.startswith("#")]
    return sorted({t.lower() for t in terms})


def walk(root):
    """The files that would be published: what git tracks, when the root is a repository, so
    untracked reference material and build caches beside the code are never scanned; every file
    under the root otherwise."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             capture_output=True, text=True, check=True).stdout
        names = [n for n in out.split("\0") if n]
    except (OSError, subprocess.CalledProcessError):
        names = None
    if names is not None:
        for rel in sorted(names):
            if rel.split("/")[0] in SKIP_DIRS or os.path.basename(rel) == DENYLIST_FILE:
                continue
            if os.path.splitext(rel)[1].lower() in BINARY_EXT:
                continue
            path = os.path.join(root, rel)
            if os.path.isfile(path):
                yield path
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if os.path.splitext(name)[1].lower() in BINARY_EXT:
                continue
            if name == DENYLIST_FILE:
                continue
            yield os.path.join(dirpath, name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="fail when no deny terms are configured (use in CI)")
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    terms = load_terms(root)
    term_res = [(t, re.compile(r"\b%s\b" % re.escape(t), re.IGNORECASE)) for t in terms]
    repo_res = [re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]*%s[A-Za-z0-9_.-]*" % re.escape(t),
                           re.IGNORECASE) for t in terms]

    if terms:
        print("deny terms configured: %d" % len(terms))
    else:
        print("deny terms configured: 0 — name checking is DISABLED; only credentials are checked.")
        if args.strict:
            print("RESULT: FAIL — --strict requires OTO_DENY_TERMS or %s." % DENYLIST_FILE)
            return 1

    findings, scanned = [], 0
    for path in walk(root):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1
        for lineno, line in enumerate(lines, 1):
            if rel != SELF:
                for term, pattern in term_res:
                    if pattern.search(line):
                        findings.append((rel, lineno, "client term", line.strip()[:100]))
                for pattern in repo_res:
                    if pattern.search(line):
                        findings.append((rel, lineno, "private repository reference",
                                         line.strip()[:100]))
            for pattern, label in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append((rel, lineno, label, "<redacted>"))

    print("scanned %d text files" % scanned)
    if not findings:
        print("RESULT: PASS — nothing found.")
        return 0

    seen = set()
    print("RESULT: FAIL — %d finding(s):" % len(findings))
    for rel, lineno, what, snippet in findings:
        key = (rel, lineno, what)
        if key in seen:
            continue
        seen.add(key)
        print("  %s:%d  %s" % (rel, lineno, what))
        print("      %s" % snippet)
    return 1


if __name__ == "__main__":
    sys.exit(main())
