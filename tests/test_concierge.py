"""The concierge skill cannot drift from the engine: every command it names must parse, and every
next step `oto status` can suggest must be a step the skill knows."""
import argparse
import ast
import os
import re

from oto.cli import COMMANDS, main
from oto.cli import status as _status

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "concierge", "SKILL.md")
COMMAND_RE = re.compile(r"`?oto ([a-z]+(?:-[a-z]+)*)(?: ([a-z]+(?:-[a-z]+)*))?")


def _parser():
    parser = argparse.ArgumentParser(prog="oto")
    sub = parser.add_subparsers(dest="command")
    for command in COMMANDS:
        command.register(sub)
    sub.add_parser("version")
    return parser, sub


def _subcommand_choices(subparser):
    """The choices of a command's first positional, when it has one with choices."""
    for action in subparser._actions:
        if not action.option_strings and action.choices:
            return set(action.choices)
    return None


def _skill_text():
    with open(SKILL, encoding="utf-8") as f:
        return f.read()


def test_every_command_the_skill_names_parses():
    parser, sub = _parser()
    known = set(sub.choices)
    text = _skill_text()
    named = set()
    for command, subcommand in COMMAND_RE.findall(text):
        assert command in known, "the skill names `oto %s`, which the engine does not have" % command
        choices = _subcommand_choices(sub.choices[command])
        if subcommand and choices is not None:
            assert subcommand in choices, "the skill names `oto %s %s`; %s accepts %s" % (
                command, subcommand, command, ", ".join(sorted(choices)))
        named.add(command)
    for essential in ("status", "ingest", "ontology", "curate", "build", "serve", "query", "rules", "preview", "publish", "sync", "bench"):
        assert essential in named, "the skill never mentions `oto %s`" % essential


def test_every_next_step_status_can_suggest_is_a_step_the_skill_knows():
    source = open(_status.__file__, encoding="utf-8").read()
    tree = ast.parse(source)
    next_fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_next")
    suggestions = [n.value for n in ast.walk(next_fn) if isinstance(n, ast.Constant) and isinstance(n.value, str) and "oto " in n.value]
    assert len(suggestions) >= 10, "the next-step logic moved; update this test"
    text = _skill_text()
    for suggestion in suggestions:
        for command, subcommand in COMMAND_RE.findall(suggestion):
            phrase = ("oto %s %s" % (command, subcommand)).strip()
            assert phrase in text or ("oto %s" % command) in text, \
                "`oto status` can suggest %r but the concierge skill never mentions it" % phrase
        for skill in re.findall(r"the ([a-z-]+) skill", suggestion):
            assert skill in text, "`oto status` points at the %s skill; the concierge does not know it" % skill


def test_the_skill_names_every_playbook_and_no_secret_value():
    text = _skill_text()
    for skill in sorted(os.listdir(os.path.join(ROOT, "skills"))):
        if skill in ("concierge", "README.md"):
            continue
        assert skill in text, "the hand-off table lacks %s" % skill
    assert "--force" not in text.replace("no `--force`", "") and "sk-ant" not in text
    assert text.startswith("---\nname: concierge\n")


def test_rules_explain_prints_the_reason_the_pattern_and_the_last_build(capsys):
    import tempfile
    from oto.scaffold import init
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="arch", name="Arch", ontology="software-architecture")
        capsys.readouterr()
        assert main(["rules", "explain", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "14 rule(s)" in out and "risk-reaches-system" in out and "A risk to a component" in out
        assert main(["rules", "explain", "risk-reaches-system", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "why:        A risk to a component" in out and "confirmed:  by nobody yet" in out
        assert "when:       r -threatens-> c  and  c -part_of-> s" in out and "then:       derive r -threatens-> s" in out
        assert "last build: none yet" in out
        assert main(["build", "--project", root]) == 0
        capsys.readouterr()
        assert main(["rules", "explain", "decision-is-documented", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "(policy, severity warn)" in out and 'flag "a decision must cite' in out
        assert "d is a Decision  and  no d -documented_in-> *" in out
        assert "last build: 0 edge(s), 0 attribute(s) derived, 1 finding(s)" in out and "[warn] decision.single-ledger" in out
        assert main(["rules", "explain", "nope", "--project", root]) == 1
        assert "no rule 'nope'" in capsys.readouterr().err


def test_the_guide_is_carried_composed_checked_and_installed(capsys):
    import tempfile
    from oto.model import ontologies
    assert "guide" in ontologies.manifest_for("software-architecture")["carries"]
    guide = ontologies.guide_for("software-architecture")
    assert guide.startswith("# Reading a software-architecture graph") and "## Common mistakes" in guide
    assert ontologies.self_check("software-architecture") == []
    with tempfile.TemporaryDirectory() as root:
        assert main(["init", "--slug", "g", "--name", "G", "--project", root, "--ontology", "software-architecture"]) == 0
        assert "GUIDE.md" in capsys.readouterr().out
        text = open(os.path.join(root, "GUIDE.md"), encoding="utf-8").read()
        assert "## What this graph is for" in text and "Installed from the `software-architecture` ontology" in text
    assert main(["ontology", "show", "software-architecture"]) == 0
    assert ", a guide" in capsys.readouterr().out
