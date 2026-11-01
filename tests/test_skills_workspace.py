"""The skills, split along the line the ontology workspace draws (docs/plans/ontology-workspace.md, phase 3).

The ontology-interview skill works in a workspace, a pack in the making: it reads the trial project's
documents, writes the pack's ontology/<name>/ files and closes with the pack's gates. The
build-knowledge-base skill composes packs and authors facts; its vocabulary phase points at the
workspace, and it never edits a knowledge project's derived vocabulary. The concierge and the start
skill route by what the person is making: an ontology, or a graph on one."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _skill(name):
    with open(os.path.join(ROOT, "skills", name, "SKILL.md"), encoding="utf-8") as f:
        return f.read()


def test_the_interview_works_in_a_workspace_and_closes_with_the_pack_s_gates():
    text = _skill("ontology-interview")
    for words in ("workspace", "oto pack new", "--to", "--extends", "trial/", "ontology/<name>/", "oto pack check", "--strict",
                  "oto pack try", "oto pack publish", "sample.graph.json", "--from-project"):
        assert words in text, words
    assert "questions before nouns" in text.lower() and "Never fill `validated_by` yourself" in text, "the discipline stays"
    assert "not edited there" in text and "derived" in text, "it says a knowledge project's vocabulary is derived and not edited there"
    assert "oto ontology export" not in text, "the export is no longer the way an ontology leaves a project; the workspace is"
    assert "oto init --ontology" not in text.replace("oto init --ontology <name>` or `oto init --pack", ""), \
        "the interview does not start a knowledge project from an ontology to edit it there"


def test_build_knowledge_base_composes_packs_and_does_not_edit_a_derived_vocabulary():
    text = _skill("build-knowledge-base")
    for words in ("oto pack list", "oto pack add", "--pack <name>", "derived", "ontology workspace", "oto pack new", "--from-project"):
        assert words in text, words
    assert "## Phase 2 — The packs" in text, "the vocabulary phase is the packs phase now"
    assert "oto ontology export" not in text, "a vocabulary leaves for a workspace, not through export"
    assert "references/draft-proposal.md" in text and "in series" in text and "references/pipeline-run.md" in text, "the drafting rules stay"


def test_the_concierge_and_start_route_by_what_is_being_made():
    concierge = _skill("concierge")
    assert "ontology workspace" in concierge and "oto pack new" in concierge and "derived" in concierge, concierge[:200]
    assert re.search(r"\| Make or change an ontology.*\| ontology-interview", concierge), "a row for making an ontology, in a workspace"
    assert "ontology/<name>/" in concierge, "the map says where a vocabulary is made"
    start = _skill("start")
    assert "workspace" in start and "oto pack new" in start and "oto init --pack" in start, "the start skill knows the two kinds"
    with open(os.path.join(ROOT, "skills", "README.md"), encoding="utf-8") as f:
        readme = f.read()
    assert re.search(r"\[ontology-interview\].*workspace.*pack", readme), "the table says the interview makes a pack, in a workspace"
