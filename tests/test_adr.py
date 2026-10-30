"""Decisions as graph nodes (roadmap G1-G3): an ADR is markdown with frontmatter under docs/adr/,
and it compiles into a `Decision` deterministically: `oto curate propose --from <adr.md>` reads the
frontmatter and writes a proposal that goes through the same gates as everything else. A decision
has a `status` (proposed, accepted) and `governs` what it shaped; one that reverses another
supersedes it, the engine's own way, so the graph shows the current decision and its history."""
import contextlib
import io
import json
import os

import pytest

from oto import adr
from oto.cli import main
from oto.curate import session
from oto.model import ontologies
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ADR = """---
id: ADR-0017
title: Returns net of fees, month-end NAV
status: accepted
decided_on: 2026-10-20
decided_by: Payments team
governs: [component.payment-api, component.settlement-job]
resolves: [openquestion.q-evidence]
supersedes: ADR-0009
---

# Returns net of fees, month-end NAV

## Context

The gross figure and the net figure were both called "return" in the reports.

## Decision

Returns are reported net of fees, computed on the month-end NAV.

## Consequences

The settlement job carries the fee schedule; the gross figure is kept for reconciliation only.
"""

OLD = """---
id: ADR-0009
title: Gross returns
status: accepted
decided_on: 2026-09-01
governs: [component.payment-api]
---

# Gross returns

## Decision

Returns are reported gross, before fees.
"""


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


# ---- the file ----

def test_frontmatter_is_read_without_a_yaml_library_and_the_body_kept():
    record = adr.parse(ADR)
    assert record["front"]["id"] == "ADR-0017" and record["front"]["status"] == "accepted"
    assert record["front"]["governs"] == ["component.payment-api", "component.settlement-job"]
    assert record["front"]["resolves"] == ["openquestion.q-evidence"] and record["front"]["supersedes"] == "ADR-0009"
    assert record["body"].startswith("# Returns net of fees") and "## Decision" in record["body"]
    assert record["sections"]["Decision"] == "Returns are reported net of fees, computed on the month-end NAV."
    assert record["sections"]["Context"].startswith("The gross figure")
    block = "---\\nid: ADR-1\\ngoverns:\\n  - a.b\\n  - c.d\\n---\\n\\n# T\\n\\n## Decision\\n\\nX.\\n".replace("\\\\n", "\\n")
    assert adr.parse(block.replace("\\n", "\n"))["front"]["governs"] == ["a.b", "c.d"], "a dashed list reads too"
    assert adr.is_adr(ADR) and not adr.is_adr("# Just a note\n\nNo frontmatter.\n") and not adr.is_adr("---\ntitle: x\n---\n# no id, no decision\n")


def test_what_is_wrong_with_an_adr_is_named():
    assert adr.problems(adr.parse(ADR)) == []
    bad = adr.parse(ADR.replace("status: accepted", "status: maybe"))
    assert any("status" in p and "maybe" in p for p in adr.problems(bad))
    bad = adr.parse(ADR.replace("id: ADR-0017\n", ""))
    assert any("id" in p for p in adr.problems(bad))
    bad = adr.parse(ADR.replace("decided_on: 2026-10-20", "decided_on: last week"))
    assert any("decided_on" in p and "YYYY-MM-DD" in p for p in adr.problems(bad))
    bad = adr.parse(ADR.replace("## Decision\n\nReturns are reported net of fees, computed on the month-end NAV.\n", ""))
    assert any("Decision" in p for p in adr.problems(bad))
    bad = adr.parse("---\nid: ADR-1\nstatus: accepted\nnested:\n  key: value\n---\n# T\n## Decision\nX.\n")
    assert any("nested" in p for p in adr.problems(bad))


# ---- the proposal ----

def test_an_adr_proposes_a_decision_with_its_evidence_edges_and_supersession():
    graph_ids = {"component.payment-api", "component.settlement-job", "openquestion.q-evidence", "team.payments", "decision.adr-0009"}
    proposal = adr.propose(adr.parse(ADR), "0017-returns-net-of-fees", graph_ids, labels={"Payments team": "team.payments"})
    assert proposal["source_doc"] == "0017-returns-net-of-fees" and proposal["as_of"] == "2026-10-20"
    nodes = {n["id"]: n for n in proposal["nodes"]}
    decision = nodes["decision.adr-0017"]
    assert decision["type"] == "Decision" and decision["label"] == "Returns net of fees, month-end NAV"
    assert decision["attributes"] == {"status": "accepted", "decided_on": "2026-10-20", "rationale": "Returns are reported net of fees, computed on the month-end NAV."}
    assert decision["evidence"] == [{"doc": "0017-returns-net-of-fees", "where": "Decision", "quote": "Returns are reported net of fees, computed on the month-end NAV."},
                                    {"doc": "0017-returns-net-of-fees", "where": "frontmatter", "quote": "decided_on: 2026-10-20"}], "the date is quoted too"
    paper = nodes["document.0017-returns-net-of-fees"]
    assert paper["type"] == "Document" and paper["attributes"] == {"kind": "adr"} and paper["label"] == decision["label"], "the ADR is the document that records it"
    assert decision["valid_from"] == "2026-10-20" and decision["supersedes"] == "decision.adr-0009" and decision["change_note"]
    old = nodes["decision.adr-0009"]
    assert old == {"id": "decision.adr-0009", "status": "superseded", "valid_to": "2026-10-20", "superseded_by": "decision.adr-0017",
                   "change_note": decision["change_note"]}
    edges = {(e["rel"], e["to"]) for e in proposal["edges"] if e["from"] == "decision.adr-0017"}
    assert edges == {("governs", "component.payment-api"), ("governs", "component.settlement-job"),
                     ("resolves", "openquestion.q-evidence"), ("decided_by", "team.payments"), ("documented_in", "document.0017-returns-net-of-fees")}
    assert proposal["unresolved"] == []
    missing = adr.propose(adr.parse(ADR), "x", {"component.payment-api"}, labels={})
    assert sorted(missing["unresolved"]) == ["Payments team", "component.settlement-job", "decision.adr-0009", "openquestion.q-evidence"]
    assert all(e["to"] in {"component.payment-api", "document.x"} for e in missing["edges"]), "an edge to nothing is not proposed; the gap is named"


# ---- end to end, in a project ----

@pytest.fixture
def plan(tmp_path):
    root = str(tmp_path / "plan")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="plan", name="The plan", ontology="software-architecture")
    return root


def _adr_in(root, name, text):
    os.makedirs(os.path.join(root, "inbox"), exist_ok=True)
    path = os.path.join(root, "inbox", name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _through_the_gates(root, name):
    code, out = _cli("ingest", "--project", root)
    assert code == 0, out
    code, out = _cli("curate", "start", "--project", root)
    assert code == 0, out
    code, out = _cli("curate", "propose", "--from", os.path.join(root, "inbox", name) if os.path.exists(os.path.join(root, "inbox", name))
                     else os.path.join(root, "processing", name), "--project", root)
    assert code == 0, out
    proposal = os.path.join(root, "proposals", os.path.splitext(name)[0] + ".json")
    assert os.path.exists(proposal), out
    code, out = _cli("curate", "add", "--from", proposal, "--project", root)
    assert code == 0, out
    code, out = _cli("curate", "check", "--project", root)
    assert code == 0 and "blocking" not in out, out
    code, out = _cli("curate", "apply", "--by", "Sam Lee", "--note", name, "--project", root)
    assert code == 0, out
    return out


def test_an_adr_goes_through_ingest_propose_and_the_gates_and_the_graph_answers_who_governs_what(plan):
    _adr_in(plan, "0009-gross-returns.md", OLD)
    _through_the_gates(plan, "0009-gross-returns.md")
    graph = session.live(Project.standard(plan))
    assert any(n["id"] == "decision.adr-0009" and n["type"] == "Decision" for n in graph["nodes"])
    _adr_in(plan, "0017-returns-net-of-fees.md", ADR)
    _through_the_gates(plan, "0017-returns-net-of-fees.md")
    graph = session.live(Project.standard(plan))
    by_id = {n["id"]: n for n in graph["nodes"]}
    assert by_id["decision.adr-0009"]["status"] == "superseded" and by_id["decision.adr-0009"]["superseded_by"] == "decision.adr-0017"
    assert by_id["decision.adr-0017"]["status"] == "current" and by_id["decision.adr-0017"]["supersedes"] == "decision.adr-0009"
    code, out = _cli("build", "--project", plan)
    assert code == 0, out
    code, out = _cli("query", "--project", plan, "ask", "PR26", "THING=component.payment-api")
    assert code == 0 and "status: answered" in out and "Returns net of fees" in out and "Gross returns" not in out, out
    code, out = _cli("query", "--project", plan, "entity", "decision.adr-0009", "--as-of", "2026-09-15")
    assert "status=superseded" in out and "valid_to=2026-10-20" in out, out


def test_an_adr_whose_frontmatter_is_wrong_or_points_at_nothing_is_refused_before_the_gates(plan):
    path = _adr_in(plan, "bad.md", ADR.replace("status: accepted", "status: maybe"))
    code, out = _cli("curate", "propose", "--from", path, "--project", plan)
    assert code == 1 and "status" in out and "maybe" in out, out
    path = _adr_in(plan, "0017-returns-net-of-fees.md", ADR)
    code, out = _cli("curate", "start", "--project", plan)
    code, out = _cli("curate", "propose", "--from", path, "--project", plan)
    assert code == 0, out
    assert "decision.adr-0009" in out and "unresolved" in out.lower(), "ADR-0009 is not in this graph: the gap is named, the rest proposed"
    proposal = os.path.join(plan, "proposals", "0017-returns-net-of-fees.json")
    with open(proposal, encoding="utf-8") as f:
        written = json.load(f)
    assert all(n["id"] != "decision.adr-0009" for n in written["nodes"]), "a supersession of a decision the graph lacks is not written"
    assert any(n["id"] == "decision.adr-0017" and "supersedes" not in n for n in written["nodes"])


# ---- the vocabulary, the skill, the repository's own decisions ----

def test_decision_declares_status_and_governs_and_the_estate_widens_it():
    product, _s, _r = ontologies.load("product")
    assert product["attributes"]["Decision"]["status"]["type"] == "enum:proposed|accepted"
    assert product["properties"]["governs"]["domain"] == "Decision"
    arch, _s, _r = ontologies.load("software-architecture")
    assert "Component" in arch["properties"]["governs"]["range"]
    for name in ("product", "software-architecture"):
        assert ontologies.self_check(name) == [], name


def test_the_spec_skill_writes_the_frontmatter_the_engine_reads():
    with open(os.path.join(ROOT, "skills", "spec", "SKILL.md"), encoding="utf-8") as f:
        skill = f.read()
    for key in ("id:", "status:", "decided_on:", "governs:", "supersedes:", "docs/adr", "curate propose"):
        assert key in skill, key
    assert "DecisionRecord" not in skill, "the class is Decision; the skill names the term the ontologies declare"


def test_the_repository_records_its_own_decisions_as_adrs():
    directory = os.path.join(ROOT, "docs", "adr")
    files = sorted(f for f in os.listdir(directory) if f.endswith(".md") and f[0].isdigit())
    assert len(files) >= 3, files
    ids = []
    for name in files:
        with open(os.path.join(directory, name), encoding="utf-8") as f:
            record = adr.parse(f.read())
        assert adr.problems(record) == [], (name, adr.problems(record))
        assert record["front"]["status"] == "accepted" and record["front"]["governs"], name
        ids.append(record["front"]["id"])
    assert len(set(ids)) == len(ids), "one id per decision"
