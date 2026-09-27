# -*- coding: utf-8 -*-
"""Prove every starter vocabulary works, end to end.

An ontology exists so a team without an ontologist has somewhere to start. A broken one wastes the time
of the person least able to diagnose it, so each is taken through the whole loop here: init, build,
integrity gate, conformance, and a real query.

    python tools/check_ontologies.py
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(args, cwd=None):
    env = dict(os.environ, PYTHONPATH=REPO)
    return subprocess.run([sys.executable, "-m", "oto.cli"] + args, cwd=cwd or REPO, env=env,
                          capture_output=True, text=True)


def check(name):
    """Problems with this ontology. Empty means it works."""
    from oto.model import ontologies

    problems = list(ontologies.self_check(name))
    root = tempfile.mkdtemp(prefix="oto_ontology_")
    project = os.path.join(root, name)
    try:
        r = run(["init", "--slug", name.replace("-", ""), "--name", "Ontology Check",
                 "--project", project, "--ontology", name])
        if r.returncode != 0:
            problems.append("init failed: %s" % (r.stderr.strip() or r.stdout.strip())[:200])
            return problems

        r = run(["build", "--project", project])
        if r.returncode != 0:
            problems.append("build failed: %s" % (r.stderr.strip() or r.stdout.strip())[:300])
            return problems
        if "unmapped classes: none | unmapped props: none" not in r.stdout:
            problems.append("the integrity gate did not report a clean vocabulary")

        # An ontology must be internally conformant. A team's first `oto ontology check` should be
        # quiet, or the report loses its meaning before they have written anything.
        r = run(["ontology", "check", "--project", project])
        if r.returncode != 0:
            problems.append("ontology check failed: %s" % r.stderr.strip()[:200])
        for line in r.stdout.splitlines():
            if line.strip().startswith(("domain violations:", "range violations :")):
                count = line.split(":")[1].strip()
                if count != "0":
                    problems.append("ontology is not self-conformant: %s" % line.strip())

        # And it must answer something, which proves the whole loop.
        config, sample, _ = ontologies.load(name)
        first = (sample.get("nodes") or [{}])[0].get("label")
        if not first:
            problems.append("the sample graph has no labelled node to query")
        else:
            r = run(["query", "--project", project, "entity", first])
            if first not in r.stdout:
                problems.append("querying %r returned nothing" % first)
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)
    return problems


def main():
    from oto.model import ontologies

    names = ontologies.available()
    if not names:
        print("no ontologies found")
        return 1
    failed = 0
    for name in names:
        problems = check(name)
        info = ontologies.summary(name)
        if problems:
            failed += 1
            print("  FAIL %-22s %2d classes, %2d relations"
                  % (name, info["classes"], info["properties"]))
            for problem in problems:
                print("         - %s" % problem)
        else:
            print("  ok   %-22s %2d classes, %2d relations, builds and answers"
                  % (name, info["classes"], info["properties"]))
    print()
    if failed:
        print("RESULT: FAIL — %d of %d ontology(s) unusable" % (failed, len(names)))
        return 1
    print("RESULT: PASS — all %d ontology(s) init, build, pass the gate and answer a query" % len(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
