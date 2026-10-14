# -*- coding: utf-8 -*-
"""Refuse to publish if client-identifying material or a credential is present.

A public repository (the engine, a registry, an ontology, a pack, a plugin) holds no client names,
programme names, private repository names or credentials: they belong in a private project
repository, never there. The vendor's own name is fine: Cynergis AI publishes these repositories, so
a copyright line and a contact address are expected. A CLIENT's name is not, anywhere, including
documentation, comments, changelogs and samples.

**The deny terms are not stored in this repository.** Writing "do not mention client X" into a public
file names client X. Terms are supplied from outside:

  OTO_DENY_TERMS   comma-separated terms, e.g. in a CI secret
  .oto-denylist    one term per line, gitignored, for local runs

With no terms supplied the scan still runs, but it can only catch credentials and generic private
repository references. It says so plainly, so a misconfigured CI job cannot pass silently while
appearing to check names.

  oto publishable [<dir>] [--strict]          any repository (python tools/check_publishable.py in the engine)

`--strict` fails when no deny terms are configured. Use it in CI.
"""
import os
import re
import subprocess

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
SELF = {"tools/check_publishable.py", "oto/validate/publishable.py"}   # the scanner names no term
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


def env_terms():
    """The deny terms of the environment alone (OTO_DENY_TERMS), lower-cased: what the pack and
    ontology gates check."""
    return sorted({t.strip().lower() for t in os.environ.get("OTO_DENY_TERMS", "").split(",") if t.strip()})


def term_patterns(terms):
    """A term is matched as a whole word, in any case: "IGM" is a client, "Figma" is not."""
    return [re.compile(r"\b%s\b" % re.escape(t), re.IGNORECASE) for t in terms]


def names_a_term(text, patterns):
    """Whether a text names any term. Says nothing of which: a finding is printed in public CI logs."""
    return any(p.search(text) for p in patterns)


def walk(root):
    """The files that would be published: what git tracks, when the root is a repository, so
    untracked reference material and build caches beside the code are never scanned; every file
    under the root otherwise."""
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


def scan(root, strict=False, out=print):
    """Scan `root` (what git tracks there, else every file). Returns 0 when clean, 1 otherwise.
    A finding names the file, the line and what was found, never the text: a CI log is public."""
    root = os.path.abspath(root)
    terms = load_terms(root)
    term_res = [(t, p) for t, p in zip(terms, term_patterns(terms))]
    repo_res = [re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]*%s[A-Za-z0-9_.-]*" % re.escape(t),
                           re.IGNORECASE) for t in terms]

    if terms:
        out("deny terms configured: %d" % len(terms))
    else:
        out("deny terms configured: 0 — name checking is DISABLED; only credentials are checked.")
        if strict:
            out("RESULT: FAIL — --strict requires OTO_DENY_TERMS or %s." % DENYLIST_FILE)
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
            if rel not in SELF:
                for _term, pattern in term_res:
                    if pattern.search(line):
                        findings.append((rel, lineno, "client term"))
                for pattern in repo_res:
                    if pattern.search(line):
                        findings.append((rel, lineno, "private repository reference"))
            for pattern, label in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append((rel, lineno, label))

    out("scanned %d text files" % scanned)
    if not findings:
        out("RESULT: PASS — nothing found.")
        return 0
    seen = []
    for finding in findings:
        if finding not in seen:
            seen.append(finding)
    out("RESULT: FAIL — %d finding(s):" % len(seen))
    for rel, lineno, what in seen:
        out("  %s:%d  %s" % (rel, lineno, what))
    return 1
