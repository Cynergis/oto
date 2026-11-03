"""The skills, the documents and the decision behind the three routes into main
(docs/plans/graph-journeys.md, phase 5; ADR-0013).

The curate skill records the person's confirmation at its fourth gate and opens the pull request;
the capture skill says a capture travels the reviewed route; the concierge and build-knowledge-base
skills name the routes; the architecture and end-to-end documents describe them; ADR-0013 is
accepted and recorded in the roadmap graph.

Phase 6: the pack carries the routes' policy, so the skills that end in a change on main say what it
means where they work: the pipeline's references hold the transcripts run, act and spec say which
route their records take, the sandbox, packs, start and concierge skills say where the policy came
from, the curate skill says when the pack sends a session change to a reviewer, and the ontology
interview says how a pack author writes the policy."""
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
    for words in ("CODEOWNERS", "oto-main", "deploy key", "[skip ci]"):
        assert words in arch, "the rules' code owners and main's key: " + words
    e2e = _read("docs", "E2E-TESTING.md")
    assert "Three routes into main" in e2e
    for words in ("CODEOWNERS", "OTO_MAIN_DEPLOY_KEY", "code owner's review", "git push origin HEAD:main"):
        assert words in e2e, "section 34 verifies what GitHub holds: " + words
    for words in ("oto curate apply", "--confirm", "oto route show", "oto route check", "oto route guardrails", "oto route rebase", "oto repo rules --apply", "preview/pr-"):
        assert words in e2e, words
    readme = _read("README.md")
    assert "three routes" in readme.lower() and "oto route" in readme
    plan = _read("docs", "plans", "graph-journeys.md")
    assert "phase 5" in plan.lower() and "ADR-0013" in plan


def _reference(name):
    return _read("skills", "build-knowledge-base", "references", name)


def test_the_pipeline_reference_holds_the_transcripts_run_and_the_route_its_pull_request_takes():
    text = _reference("pipeline-run.md")
    assert "## A transcripts run" in text, "the rules the author agent follows for transcripts are in the reference, not only in the prompt"
    for words in ("routes.guardrailed", "oto curate assert --by", "human_assertion", "additive", "max_facts",
                  "oto route guardrails", "--strict-privacy"):
        assert words in text, words
    assert "allowed" in text and "classes" in text, "only the classes the policy allows"
    for words in ("guardrailed route", "reviewed route"):
        assert words in text, words
    assert "**Route**" in text, "the report says which route the pull request will take"
    assert "never `--confirm`" in text, "the pipeline never writes a confirmation"


def test_the_draft_reference_says_a_fact_from_a_transcript_is_the_speakers_assertion_with_its_shape():
    text = _reference("draft-proposal.md")
    for words in ('"source_type": "human_assertion"', '"assertion:a-', "the speaker", "transcript", "oto curate assert"):
        assert words in text, words
    assert "in the speaker's words" in text, "a number or a date must be in what the speaker said"


def test_act_says_the_tools_pull_request_is_reviewed_and_a_record_made_in_a_session_is_confirmed():
    text = _skill("act")
    for words in ("--confirm", "session route", "reviewed route", "oto route show"):
        assert words in text, words


def test_spec_says_a_decision_recorded_in_a_session_is_confirmed_and_one_the_pipeline_drafted_is_reviewed():
    text = _skill("spec")
    for words in ("--confirm", "session route", "reviewed route"):
        assert words in text, words


def test_the_sandbox_skill_says_the_branch_rules_and_the_packs_routes_come_with_a_knowledge_project():
    text = _skill("sandbox")
    assert "branch rules" in text, "the repository gets the branch rules when the sandbox makes it"
    assert "the pack's routes" in text, "the routes' policy comes with the project, from the pack"
    readback = text.split("Read the answers back", 1)[1].split("## 3.", 1)[0]
    assert "route" in readback, "the read-back says how changes will reach main"


def test_the_packs_skill_says_pack_show_prints_the_routes_and_a_pack_without_them_leaves_everything_to_a_reviewer():
    text = _skill("packs")
    assert "oto pack show" in text and "routes" in text
    assert "reviewer" in text, "a pack without routes leaves every pull request to a reviewer"


def test_start_and_the_concierge_say_where_the_routes_policy_came_from():
    concierge = _skill("concierge")
    assert "`routes`" in concierge and "from the pack" in concierge and "set here" in concierge, "the status line, read in plain words"
    start = _skill("start")
    assert "routes" in start and "from the pack" in start


def test_the_curate_skill_says_when_the_packs_policy_sends_a_session_change_to_a_reviewer():
    text = _skill("curate")
    assert "session.classes" in text or "classes a session may change" in text
    assert "routes.allowed" in text or "routes it allows" in text


def test_the_ontology_interview_says_how_a_pack_author_writes_the_routes_policy():
    text = _skill("ontology-interview")
    assert '"routes"' in text and '"allowed"' in text and '"guardrailed"' in text, "the manifest section, with its shape"
    assert "oto pack show" in text, "where the author sees it back"
    assert "reviewed" in text, "reviewed is always allowed"


def test_the_end_to_end_guide_walks_the_packs_routes_from_the_manifest_to_the_gate():
    e2e = _read("docs", "E2E-TESTING.md")
    assert "33 to 35" in e2e, "the guide's index counts the section among the core's"
    assert "## 35. " in e2e
    section = e2e.split("## 35. ", 1)[1]
    for words in ('"routes"', "oto pack new", "oto pack check", "oto pack show", "--pack", "routes_from", "oto status",
                  "set here", "oto ontology update", "kept guardrailed", "oto route check", "routes.session.classes",
                  "rewrites the routes' policy", "oto.lock.json", ".github/", "oto pack rm"):
        assert words in section, words
    assert "Pass when" in section
