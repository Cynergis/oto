"""The core and the packs (ADR-0006). OTO's core is the knowledge graph's lifecycle with its tools,
the estate and the reified model it is described in, and the deploy of the graph. An architecture
framework (CALM today, C4 tomorrow) is a pack plus an adapter; a domain feature (work, data, policy,
the domain model) is a pack plus its tools; what is built on the graph lives outside the engine (ADR-0007). The first step records the decision and draws the line in the
documents and the command line, before any code moves."""
import os
import re

from oto import adr as _adr
from oto.cli import COMMANDS, GROUPS, main
import contextlib
import io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_COMMANDS = {"init", "status", "lock", "sandbox", "ingest", "capture", "clipboard", "ontology", "lexicon", "pack", "registry", "rules", "tools",
                 "curate", "decide", "deploy", "connectors", "draft", "vet", "build", "preview", "query", "publish", "publishable", "bench",
                 "feedback", "audit", "graph", "version"}
PACK_COMMANDS = {"arch": "architecture"}   # ddd, work, data and policy are the registry's (ADR-0010)


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _help():
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            main(["--help"])
        except SystemExit:
            pass
    return out.getvalue()


def test_adr_0006_narrows_the_core_and_makes_frameworks_and_domains_packs():
    text = _read("docs", "adr", "0006-the-core-and-the-packs.md")
    record = _adr.parse(text)
    assert _adr.problems(record) == [], _adr.problems(record)
    front = record["front"]
    assert front["id"] == "ADR-0006" and front["status"] == "accepted"
    assert set(front["governs"]) >= {"workitem.epic-c", "workitem.epic-e", "workitem.epic-h", "workitem.epic-i", "workitem.epic-j", "workitem.epic-m", "workitem.epic-n"}, \
        "the epics whose features become packs, and the one whose framework becomes an adapter"
    decision = _adr.first_sentence(record["sections"]["Decision"]).lower()
    assert "core" in decision and "pack" in decision
    body = text.lower()
    assert "calm" in body and "c4" in body and "adapter" in body, "a framework is a pack plus an adapter"
    assert "reified" in body or "relationship, a control and a flow" in body, "the reified model stays in core"
    assert "deploy" in body


def test_the_architecture_document_draws_the_line_between_the_engine_and_the_packs():
    text = _read("docs", "ARCHITECTURE.md")
    assert "## The core and the packs" in text and "ADR-0006" in text
    core_at, packs_at = text.index("## The lifecycle, and the code behind each step"), text.index("## The packs, and the tools each brings")
    assert core_at < packs_at
    core_table, packs_table = text[core_at:packs_at], text[packs_at:text.index("## ", packs_at + 5)]
    for row in ("| Create |", "| Ingest |", "| Author |", "| Build |", "| Serve |", "| Decisions |", "| Audit |", "| Graphs |"):
        assert row in core_table and row not in packs_table, row
    for row in ("| Work |", "| Data |", "| Policy |", "| Architecture |", "| Domain (ddd) |", "| Use cases of the graph |"):
        assert row in packs_table and row not in core_table, row
    intro = text[text.index("## The core and the packs"):core_at]
    assert "deploy" in intro.lower() and "C4" in intro, "deploying the graph is core; a framework is swappable"
    assert "swappable" in packs_table.lower() or "adapter" in packs_table.lower(), "a framework is swappable: CALM is the first adapter"


def test_the_e2e_document_says_which_sections_are_the_core_and_which_a_pack():
    text = _read("docs", "E2E-TESTING.md")
    assert "## How to read this document" in text
    section = text[text.index("## How to read this document"):text.index("## What needs your accounts")]
    assert "core" in section.lower() and "pack" in section.lower()
    numbers = {int(n) for n in re.findall(r"\b(\d{1,2})\b", section)}
    for a, b in re.findall(r"\b(\d{1,2}) to (\d{1,2})\b", section):
        numbers |= set(range(int(a), int(b) + 1))
    declared = {int(m) for m in re.findall(r"^## (\d{1,2})\.", text, re.MULTILINE)}
    assert declared <= numbers, "every section is placed: %s" % sorted(declared - numbers)


def test_the_command_line_groups_the_core_commands_and_the_pack_commands():
    from oto.cli import CORE_COMMANDS as core_modules
    names = {m.__name__.rsplit(".", 1)[-1] for m in core_modules}
    pack_names = {name for name, _pack in GROUPS["packs"]}
    grouped = set(GROUPS["core"]) | pack_names
    assert "graphs" in names and "graph" in GROUPS["core"], "the graphs module registers `oto graph`"
    assert set(GROUPS["core"]) >= (names - {"graphs"}) | {"graph", "version"}, sorted((names - {"graphs"}) - set(GROUPS["core"]))
    assert len(COMMANDS) == len(core_modules) + len(pack_names), "every pack command module registers one command"
    assert set(GROUPS["core"]) == CORE_COMMANDS
    assert dict(GROUPS["packs"]) == PACK_COMMANDS
    assert not set(GROUPS["core"]) & pack_names, "a command is in one group"
    text = _help()
    assert "core:" in text.lower() and "packs:" in text.lower()
    for command in CORE_COMMANDS:
        assert command in text, command
    for command, pack in PACK_COMMANDS.items():
        assert "%s" % command in text and pack in text, (command, pack)


def test_the_readme_says_what_the_core_is_and_that_the_rest_are_packs():
    text = _read("README.md")
    assert "ADR-0006" in text or "docs/adr/0006" in text
    assert "core" in text.lower() and "pack" in text.lower()
    paragraph = text[text.index("## What is core"):text.index("## What makes it different")]
    assert "deploy" in paragraph.lower() and "CALM" in paragraph and "C4" in paragraph
