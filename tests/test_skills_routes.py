"""The skills, the documents and the decision behind the three routes into main
(docs/plans/graph-journeys.md, phase 5; ADR-0013).

The curate skill records the person's confirmation at its fourth gate and opens the pull request;
the capture skill says a capture travels the reviewed route; the concierge and build-knowledge-base
skills name the routes; the architecture and end-to-end documents describe them; ADR-0013 is
accepted and recorded in the roadmap graph."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _skill(name):
    return _read("skills", name, "SKILL.md")


def test_the_curate_skill_records_the_confirmation_and_opens_the_pull_request_in_the_persons_name():
    text = _skill("curate")
    for words in ("--confirm", "session route", "fingerprint", "auto-merge", "oto route rebase", "oto route show"):
        assert words in text, words
    assert "Never write a confirmation the person did not give" in text, "the confirmation is theirs, never the agent's"
    assert "their git identity" in text or "the person's git identity" in text, "the commits are the confirmer's, or the route does not hold"
    assert "verified" in text, "it says why the commits must be verified"


def test_the_capture_skill_says_a_capture_is_reviewed_and_offers_to_draft_now():
    text = _skill("capture")
    assert "reviewed route" in text, "nobody has confirmed the drafted facts yet"
    assert "offer" in text.lower() and "curate" in text, "it offers the curate skill, which drafts and confirms in the session"
    assert "session route" in text


def test_the_concierge_and_build_knowledge_base_name_the_routes():
    concierge = _skill("concierge")
    assert "oto route check" in concierge or "oto route show" in concierge
    assert "session" in concierge and "guardrailed" in concierge and "reviewed" in concierge, "the three routes, where it says how a change reaches main"
    build = _skill("build-knowledge-base")
    assert "reviewed route" in build and "session route" in build


def test_adr_0013_is_accepted_and_recorded_in_the_roadmap_graph():
    adr = _read("docs", "adr", "0013-three-routes-into-main.md")
    assert "id: ADR-0013" in adr and "status: accepted" in adr and "decided_on: 2026-11-02" in adr
    for words in ("session", "guardrailed", "reviewed", "oto route", "fingerprint", "--confirm", "guardrails", "oto route rebase", "ADR-0012"):
        assert words in adr, words
    graph = json.loads(_read("roadmap", "graph.json"))
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["decision.adr-0013"]["attributes"]["status"] == "accepted" and nodes["decision.adr-0013"]["as_of"] == "2026-11-02"
    assert "document.0013-three-routes-into-main" in nodes
    edges = {(e["from"], e["rel"], e["to"]) for e in graph["edges"]}
    assert ("decision.adr-0013", "documented_in", "document.0013-three-routes-into-main") in edges
    assert any(f == "decision.adr-0013" and r == "governs" for f, r, _t in edges), "it governs an epic"
    assert ("decision.adr-0013", "decided_by", "person.chiheb-dkhil") in edges


def test_the_documents_describe_the_routes():
    arch = _read("docs", "ARCHITECTURE.md")
    for words in ("oto-route", "oto-preview", "oto-rules.json", "oto route check", "fingerprint", "--confirm", "guardrail", "oto lock --check", "oto route rebase", "ADR-0013"):
        assert words in arch, words
    e2e = _read("docs", "E2E-TESTING.md")
    assert "Three routes into main" in e2e
    for words in ("oto curate apply", "--confirm", "oto route show", "oto route check", "oto route guardrails", "oto route rebase", "oto repo rules --apply", "preview/pr-"):
        assert words in e2e, words
    readme = _read("README.md")
    assert "three routes" in readme.lower() and "oto route" in readme
    plan = _read("docs", "plans", "graph-journeys.md")
    assert "phase 5" in plan.lower() and "ADR-0013" in plan
