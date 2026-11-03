#!/usr/bin/env python3
"""Copy the sandbox kit's files into its descriptor.

kits/oto-gcp is a Docker Sandboxes kit set (schema 3). A set ships no files of its own: what it adds
to a sandbox is declared in its descriptor. The start script and the plugin lock are written by its
lifecycle capability, and the note for the sandbox's Claude is its agent context. Their text is kept
in kits/oto-gcp/files/home, where it is edited, read and tested as files, and this copies it into the
marked parts of kits/oto-gcp/oto-gcp.yaml:

    python3 tools/kit_files.py           # rewrite the descriptor
    python3 tools/kit_files.py --check   # exit 1 when the descriptor is out of date

Stdlib only. tests/test_kits.py runs the check, and CI runs it before building the kit.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(ROOT, "kits", "oto-gcp")
DESCRIPTOR = os.path.join(KIT, "oto-gcp.yaml")
HOME = "/home/agent"
#: written into the sandbox by the lifecycle capability, at HOME/<path>, before the agent starts
FILES = (
    (".oto/init.sh", "OTO for the agent user, run at every start"),
    (".oto/lock-plugins", "Keeps the sandbox to the plugins installed in it"),
)
#: the note for the sandbox's Claude, its agent context
CONTEXT = ".claude/CLAUDE.md"


def _text(rel):
    path = os.path.join(KIT, "files", "home", rel)
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    where = os.path.relpath(path, ROOT)
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise ValueError("%s must end with exactly one newline: a literal block keeps one" % where)
    if text[:1] in (" ", "\t", "\n") or "\r" in text:
        raise ValueError("%s must start with text and use LF line ends" % where)
    if "${{" in text:
        raise ValueError("%s holds `${{`, which the kit frontend reads as a kit placeholder" % where)
    return text


def _block(text, indent):
    """A YAML literal block of `text`, its lines at `indent` spaces; empty lines stay empty."""
    pad = " " * indent
    return "".join(pad + line if line.strip("\n") else line for line in text.splitlines(True))


def _files(indent):
    pad = " " * indent
    out = [pad + "files:\n"]
    for rel, description in FILES:
        out += ["%s  - path: %s/%s\n" % (pad, HOME, rel), "%s    description: %s\n" % (pad, description),
                "%s    content: |\n" % pad, _block(_text(rel), indent + 6)]
    return "".join(out)


def _context(indent):
    pad = " " * indent
    return "%sconfig: &oto-context\n%s  content: |\n%s" % (pad, pad, _block(_text(CONTEXT), indent + 4))


PARTS = {"files": _files, "context": _context}


def render(descriptor):
    """The descriptor with each marked part written from the files."""
    for part, write in PARTS.items():
        found = re.search(r"^( *)# >>> %s\b[^\n]*\n(.*?)^\1# <<< %s\n" % (part, part), descriptor, re.M | re.S)
        if not found:
            raise ValueError("%s has no part marked `# >>> %s` ... `# <<< %s`" % (os.path.relpath(DESCRIPTOR, ROOT), part, part))
        start, end = found.span(2)
        descriptor = descriptor[:start] + write(len(found.group(1))) + descriptor[end:]
    return descriptor


def main(argv):
    check = argv[1:] == ["--check"]
    if argv[1:] and not check:
        print("usage: python3 tools/kit_files.py [--check]", file=sys.stderr)
        return 2
    with open(DESCRIPTOR, encoding="utf-8", newline="") as f:
        current = f.read()
    try:
        wanted = render(current)
    except ValueError as e:
        print("kit_files: %s" % e, file=sys.stderr)
        return 1
    where = os.path.relpath(DESCRIPTOR, ROOT)
    if wanted == current:
        print("%s carries the kit's files as they are" % where)
        return 0
    if check:
        print("%s is out of date with kits/oto-gcp/files: run python3 tools/kit_files.py" % where)
        return 1
    with open(DESCRIPTOR, "w", encoding="utf-8", newline="") as f:
        f.write(wanted)
    print("wrote the kit's files into %s" % where)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
