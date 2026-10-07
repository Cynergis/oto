"""The capture schema (what an elicitation tool asks for, rendered from the ontology) and the
proposals a capture written against it becomes: the two seams between a tool that interviews
people and the engine that keeps what they said."""
import json
import os
import tempfile

from oto.builder import build
from oto.cli import main
from oto.compile import capture as _capture
from oto.curate import propose as _propose, session
from oto.project import Project
from oto.scaffold import init


def _project(root):
    init(root, slug="claims", name="Claims", ontology="auto-claims")
    return Project.standard(root)


def test_the_capture_schema_renders_the_questions_by_asker_and_the_classes_with_their_terms():
    schema = _capture.for_ontology("auto-claims")
    assert schema["capture_schema"] == 1 and schema["pack"] == "auto-claims" and schema["namespace"] == "https://cynergis.ai/ont/auto-claims#"
    who = {s["who"]: [a["id"] for a in s["asks"]] for s in schema["sections"]}
    assert "AC1" in who["a claims handler"] and "AC12" in who["finance"] and "CORE2" in who["anyone"], "the core's questions compose in"
    ask = next(a for s in schema["sections"] for a in s["asks"] if a["id"] == "AC1")
    assert ask["gate"] == "non_empty" and ask["may_continue"] is False and ask["params"] == {"CLAIM": "Claim"}
    assert {"Claim", "Policy", "Coverage", "Party"} <= set(ask["captures"])
    claim = schema["types"]["Claim"]
    assert claim["x-term"] == "https://cynergis.ai/ont/auto-claims#Claim" and claim["id_prefix"] == "claim" and "AC1" in claim["asked_by"]
    state = claim["fields"]["state"]
    assert state["x-term"].endswith("#state") and state["type"] == "scheme" and state["choices"] == ["open", "reopened", "closed", "denied"] and state["required"] is True
    assert claim["fields"]["claim_number"]["required"] is True
    link = claim["links"]["claims_under"]
    assert link["to"] == ["Policy"] and link["min"] == 1 and link["max"] == 1 and link["x-term"].endswith("#claims_under")
    assert "decides" not in claim["links"], "a link belongs to the class of its domain"
    assert "part_of_claim" in schema["types"]["Payment"]["links"]
    doc = schema["types"]["Document"]
    assert doc["x-term"] == "https://cynergis.ai/ont/oto-core#Document", "an inherited class keeps its IRI"
    assert any(s["kind"] == "min" and s["subject"] == "claims_under" for s in schema["shapes"])


def test_the_build_writes_the_capture_schema_beside_the_questions():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        build(project)
        path = os.path.join(project.layout.ontology, "capture.json")
        schema = json.load(open(path, encoding="utf-8"))
        assert schema["pack"] == "claims" and "Claim" in schema["types"]
        assert main(["ontology", "capture", "--project", root]) == 0
        assert os.path.exists(os.path.join(root, "capture.json"))


CAPTURE = {
    "doc": "intake-memo", "as_of": "2026-09-01",
    "items": [
        {"type": "Claim", "id": "C-9", "label": "Claim C-9", "summary": "A rear-end collision claim.",
         "fields": {"claim_number": "C-9", "state": "open"},
         "links": {"claims_under": ["policy.p-1001"], "claims_against": ["coverage.collision"], "filed_by": ["party.policyholder"], "arises_from": ["INC-9"]},
         "where": "p.1", "quote": "C-9 was opened on 1 September."},
        {"type": "Incident", "id": "INC-9", "label": "Collision of 28 August", "fields": {"occurred_on": "2026-08-28"},
         "links": {"involves": ["vehicle.insured"]}, "where": "p.1", "quote": "The insured vehicle was hit on 28 August."},
        {"type": "Task", "id": "T-9", "label": "Intake of C-9", "fields": {"state": "open"},
         "links": {"part_of_claim": ["C-9"], "assigned_to": ["role.adjuster"], "follows": ["procedure.fnol"]}, "where": "p.2", "quote": "Intake assigned to the adjuster."},
    ],
}


def test_a_capture_is_checked_against_its_schema_and_named_when_wrong():
    schema = _capture.for_ontology("auto-claims")
    assert _propose.problems(CAPTURE, schema) == []
    bad = json.loads(json.dumps(CAPTURE))
    bad["items"][0]["type"] = "Thing"
    bad["items"][1]["fields"]["colour"] = "red"
    bad["items"][2]["fields"]["state"] = "half-done"
    bad["items"].append({"type": "Payment", "id": "P-1", "label": "A payment", "links": {"charged_to": ["coverage.collision", "coverage.other"]}})
    bad["items"].append({"type": "Policy", "id": "P-2", "label": "A policy", "fields": {}})
    found = "\n".join(_propose.problems(bad, schema))
    assert "type 'Thing' is not in the capture schema" in found
    assert "Incident captures no field 'colour'" in found
    assert "state is 'half-done'; the choices are open, in_progress, done, cancelled" in found
    assert "link charged_to has 2 targets; at most 1" in found
    assert "policy_number is required and missing" in found
    assert _propose.problems({"items": "no"}, schema) == ["a capture is {doc, as_of, items: [...]}"]


def test_a_capture_becomes_a_proposal_that_passes_the_gates(capsys):
    schema = _capture.for_ontology("auto-claims")
    proposal = _propose.propose(CAPTURE, schema, graph_ids={"policy.p-1001", "coverage.collision", "party.policyholder", "vehicle.insured", "role.adjuster", "procedure.fnol"})
    assert [n["id"] for n in proposal["nodes"]] == ["claim.c-9", "incident.inc-9", "task.t-9"]
    claim = proposal["nodes"][0]
    assert claim["type"] == "Claim" and claim["attributes"] == {"claim_number": "C-9", "state": "open"} and claim["source_doc"] == "intake-memo"
    assert claim["evidence"] == [{"doc": "intake-memo", "where": "p.1", "quote": "C-9 was opened on 1 September."}] and claim["as_of"] == "2026-09-01"
    assert {"from": "claim.c-9", "rel": "arises_from", "to": "incident.inc-9"} in proposal["edges"], "a link to another item of the capture resolves to its node"
    assert {"from": "claim.c-9", "rel": "claims_under", "to": "policy.p-1001"} in proposal["edges"], "a link to a node of the graph stays"
    assert proposal["unresolved"] == []
    loose = _propose.propose({"doc": "d", "as_of": "2026-09-01", "items": [{"type": "Claim", "id": "C-1", "label": "x", "links": {"claims_under": ["POL-404"]}}]},
                             schema, graph_ids={"policy.p-1001"})
    assert loose["edges"] == [] and loose["unresolved"] == [{"from": "claim.c-1", "rel": "claims_under", "to": "POL-404"}]
    # through the CLI, into a candidate, through the gates
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        path = os.path.join(root, "capture-intake.json")
        json.dump(CAPTURE, open(path, "w", encoding="utf-8"))
        assert main(["curate", "start", "--project", root]) == 0
        assert main(["curate", "propose", "--project", root, "--from", path]) == 0
        out = capsys.readouterr().out
        assert "proposal: proposals/intake-memo.json  (3 node(s), 8 edge(s) from 3 item(s))" in out and "next: oto curate add" in out
        assert main(["curate", "add", "--project", root, "--from", os.path.join(root, "proposals", "intake-memo.json")]) == 0
        assert main(["curate", "check", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "ready to apply" in out and "shape " not in out and "question AC" not in out
        candidate = session.candidate(project)
        assert any(n["id"] == "claim.c-9" for n in candidate["nodes"])
        bad = os.path.join(root, "capture-bad.json")
        json.dump({"doc": "d", "as_of": "2026-09-01", "items": [{"type": "Thing", "id": "x", "label": "x"}]}, open(bad, "w", encoding="utf-8"))
        assert main(["curate", "propose", "--project", root, "--from", bad]) == 1
        assert "is not a capture against this vocabulary" in capsys.readouterr().out
