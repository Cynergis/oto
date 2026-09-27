# -*- coding: utf-8 -*-
"""Scan a document for personal data and credentials BEFORE it joins the corpus.

Once a document is extracted, indexed and served, removing personal data means rebuilding every
layer and, if it was committed, rewriting history. It is far cheaper to catch it at the door.

Two severities:

  block   a credential, or an identifier that is personal data on its own (a social insurance
          number, a payment card). Ingestion stops.
  warn    something that is often legitimate in a business document (an email address, a phone
          number, a vehicle identification number). Reported, and ingestion continues unless
          strict mode is on.

Checked digits are verified where the format defines them, so a nine-digit part number is not
reported as a social insurance number. This is a safety net, not a substitute for review: it cannot
recognise a name, an address or a medical detail written as prose.
"""
import re

BLOCK = "block"
WARN = "warn"


def _luhn(digits):
    """True when a digit string satisfies the Luhn checksum."""
    total, alternate = 0, False
    for char in reversed(digits):
        d = ord(char) - 48
        if alternate:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alternate = not alternate
    return total % 10 == 0


def _luhn_only(match):
    digits = re.sub(r"\D", "", match)
    return _luhn(digits)


# (name, severity, pattern, validator or None)
DETECTORS = [
    ("credential: GitHub token", BLOCK, re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), None),
    ("credential: GitHub fine-grained token", BLOCK,
     re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), None),
    ("credential: Anthropic API key", BLOCK, re.compile(r"\bsk-ant-[A-Za-z0-9-]{20,}\b"), None),
    ("credential: AWS access key id", BLOCK, re.compile(r"\bAKIA[0-9A-Z]{16}\b"), None),
    ("credential: private key", BLOCK, re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), None),
    ("credential: Slack token", BLOCK, re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), None),

    # Canadian social insurance number: nine digits, Luhn-checked, optionally spaced or hyphenated.
    ("personal data: social insurance number", BLOCK,
     re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{3}\b"), _luhn_only),
    # Payment cards: 13 to 19 digits, Luhn-checked.
    ("personal data: payment card number", BLOCK,
     re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), _luhn_only),

    ("personal data: email address", WARN,
     re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), None),
    ("personal data: phone number", WARN,
     re.compile(r"\b(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b"), None),
    # Vehicle identification number: 17 characters, no I, O or Q by standard.
    ("personal data: vehicle identification number", WARN,
     re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b"), None),
    ("personal data: Canadian postal code", WARN,
     re.compile(r"\b[A-Za-z]\d[A-Za-z][ -]?\d[A-Za-z]\d\b"), None),
]


class Finding:
    __slots__ = ("kind", "severity", "line", "sample", "count")

    def __init__(self, kind, severity, line, sample, count=1):
        self.kind = kind
        self.severity = severity
        self.line = line
        self.sample = sample
        self.count = count

    def __repr__(self):
        return "%s (%s) line %d x%d" % (self.kind, self.severity, self.line, self.count)


def _mask(value):
    """Never echo the value itself. A report must not leak what it found."""
    stripped = re.sub(r"\s", "", value)
    if len(stripped) <= 4:
        return "*" * len(stripped)
    return "%s%s%s" % (stripped[:2], "*" * (len(stripped) - 4), stripped[-2:])


def scan(text, detectors=None):
    """Return a list of Finding, one per (kind, line)."""
    detectors = detectors or DETECTORS
    grouped = {}
    for lineno, line in enumerate(text.split("\n"), 1):
        for kind, severity, pattern, validator in detectors:
            for match in pattern.findall(line):
                value = match if isinstance(match, str) else match[0]
                if validator and not validator(value):
                    continue
                key = (kind, lineno)
                if key in grouped:
                    grouped[key].count += 1
                else:
                    grouped[key] = Finding(kind, severity, lineno, _mask(value))
    return [grouped[k] for k in sorted(grouped, key=lambda k: (k[1], k[0]))]


def blocking(findings):
    return [f for f in findings if f.severity == BLOCK]


def summarize(findings):
    """One line per kind, with counts. Suitable for a build log."""
    totals = {}
    for f in findings:
        entry = totals.setdefault(f.kind, {"severity": f.severity, "count": 0, "lines": []})
        entry["count"] += f.count
        entry["lines"].append(f.line)
    out = []
    for kind in sorted(totals):
        entry = totals[kind]
        lines = ", ".join(str(l) for l in entry["lines"][:5])
        more = "" if len(entry["lines"]) <= 5 else ", ..."
        out.append("  [%s] %s x%d (line %s%s)"
                   % (entry["severity"], kind, entry["count"], lines, more))
    return "\n".join(out)
