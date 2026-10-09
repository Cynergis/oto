"""The ontology contract: the manifest, composition through `extends`, what a project records,
and what the self-check refuses. Every ontology here is built in a temporary directory, so the
cases say exactly what they exercise."""
import json
import os
import tempfile

import pytest

from oto import __version__
from oto.cli import main
from oto.model import ontology_compose as compose, ontology_manifest as manifest, ontologies
from oto.project import Project
from oto.scaffold import init

TEMPORAL = {"asOf": {"type": "date", "definition": "recorded"}, "validFrom": {"type": "date", "definition": "true from"}, "validTo": {"type": "date", "definition": "true until"},
            "status": {"type": "string", "definition": "current | superseded | proposed."}, "supersedes": {"type": "ref", "definition": "replaces"},
            "supersededBy": {"type": "ref", "definition": "replaced by"}, "sourceDoc": {"type": "string", "definition": "the document"}}
STAMP = {"as_of": "2026-01-01", "valid_from": "2026-01-01", "source_doc": "sample", "status": "current", "sources": ["sample"]}


def _node(nid, kind, label, **attrs):
    return dict(id=nid, type=kind, label=label, aliases=[], summary="s", attributes=attrs, tags=[], **STAMP)


WHY = "It answers a question the documents keep raising, and nothing else in the vocabulary does."


def _rationale(classes, properties=()):
    return {"classes": {k: {"question": "What is this?", "why": WHY, "alternatives": "", "validated_by": ""} for k in classes},
            "properties": {p: {"question": "How is it linked?", "why": WHY, "alternatives": "", "validated_by": ""} for p in properties}}


def coverage_questions(classes, properties, attributes=None):
    """One informational question per class and per relation, so a test ontology satisfies the rule
    that every term is cited by a question that runs, without pretending to be a real question set."""
    out = {}
    for kind in classes:
        out["Q-%s" % kind] = {"who": "anyone", "question": "Which %s are there?" % kind, "why": "a test asks it",
                              "validated_by": "", "ask": {"when": [{"node": "x", "type": kind}], "select": ["x.label"]},
                              "gate": "any"}
    for relation in properties:
        out["Q-%s" % relation] = {"who": "anyone", "question": "What is %s what?" % relation, "why": "a test asks it",
                                  "validated_by": "", "ask": {"when": [{"edge": ["a", relation, "b"]}], "select": ["a.label", "b.label"]},
                                  "gate": "any"}
    terms = ["%s.%s" % (kind, attr) for kind, declared in (attributes or {}).items() for attr in declared]
    if terms:
        out["Q-attributes"] = {"who": "anyone", "question": "What is recorded on things?", "why": "a test asks it",
                               "validated_by": "", "ask": {"when": [{"node": "x"}], "select": ["x.label"]},
                               "gate": "any", "terms": terms}
    return out


def with_questions(carries):
    """A carries list with 'questions' in its place, for a manifest a test writes by hand."""
    if "questions" in carries:
        return carries
    out = list(carries)
    out.insert(out.index("sample") if "sample" in out else len(out), "questions")
    return out


def write_ontology(root, name, classes, properties, sample, manifest_body=None, temporal=True, rules=None,
                   rationale=None, lexicon=None, interview=None, gold=None, readme="# T\n\nA first draft; edit it.\n",
                   questions="auto", attributes=None):
    base = os.path.join(root, name)
    os.makedirs(base, exist_ok=True)
    config = {"name": name, "ontology_version": 1, "strict_domains": False, "_summary": "about %s" % name,
              "classes": classes, "properties": properties}
    if temporal:
        config["temporal"] = TEMPORAL
    if attributes:
        config["attributes"] = attributes
    for filename, payload in (("ontology.config.json", config), ("sample.graph.json", sample),
                              ("ontology.rationale.json", rationale or _rationale(classes, properties))):
        with open(os.path.join(base, filename), "w", encoding="utf-8") as f:
            json.dump(payload, f)
    with open(os.path.join(base, "README.md"), "w", encoding="utf-8") as f:
        f.write(readme)
    if questions == "auto":
        questions = coverage_questions(classes, properties, attributes)
    if questions:
        with open(os.path.join(base, "questions.json"), "w", encoding="utf-8") as f:
            json.dump({"questions": questions}, f)
    if manifest_body is not False:          # False: a directory with no manifest at all
        body = dict(manifest_body or {})
        if questions and body.get("carries"):
            body["carries"] = with_questions(body["carries"])
        with open(os.path.join(base, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(dict({"name": name, "namespace": "https://example.org/ont/%s#" % name}, **body), f)
    if rules is not None:
        with open(os.path.join(base, "rules.json"), "w", encoding="utf-8") as f:
            json.dump({"rules": rules}, f)
    if lexicon is not None:
        with open(os.path.join(base, "lexicon.json"), "w", encoding="utf-8") as f:
            json.dump(lexicon, f)
    if interview is not None:
        with open(os.path.join(base, "interview.md"), "w", encoding="utf-8") as f:
            f.write(interview)
    if gold is not None:
        os.makedirs(os.path.join(base, "gold"), exist_ok=True)
        with open(os.path.join(base, "gold", "patterns.jsonl"), "w", encoding="utf-8") as f:
            f.write(gold)
    return base


def base_ontology(root, **extra):
    return write_ontology(root, "base", {"Document": {"definition": "a doc"}, "Party": {"definition": "a party"}},
                          {"cites": {"domain": "Document", "range": "Document", "definition": "cites"}},
                          {"nodes": [_node("doc.a", "Document", "A"), _node("party.x", "Party", "X")], "edges": []},
                          manifest_body={"release": 2, "summary": "the base", "engine": ">=0.1",
                                         "carries": ["vocabulary", "rationale", "sample", "readme"],
                                         "changelog": [{"release": 2, "at": "2026-09-01", "note": "second"},
                                                       {"release": 1, "at": "2026-08-01", "note": "first"}]}, **extra)


@pytest.fixture
def ontologies_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        monkeypatch.setenv(ontologies.USER_DIR_ENV, root)
        yield root


# ---- the manifest ----

def test_an_ontology_must_state_its_namespace(ontologies_dir):
    sample = {"nodes": [_node("t.1", "Thing", "One")], "edges": []}
    write_ontology(ontologies_dir, "plain", {"Thing": {"definition": "t"}}, {"near": {"domain": "Thing", "range": "Thing", "definition": "n"}}, sample)
    m = ontologies.manifest_for("plain")
    assert m["name"] == "plain" and m["release"] == 1 and m["extends"] == []
    assert m["summary"] == "about plain", "the vocabulary's _summary is the fallback"
    assert m["carries"] == ["vocabulary", "rationale", "questions", "sample", "readme"]
    assert ontologies.self_check("plain") == []

    write_ontology(ontologies_dir, "bare", {"Thing": {"definition": "t"}}, {"near": {"domain": "Thing", "range": "Thing", "definition": "n"}}, sample,
                   manifest_body=False)
    assert any("no manifest.json" in p for p in ontologies.self_check("bare"))
    write_ontology(ontologies_dir, "nameless", {"Thing": {"definition": "t"}}, {"near": {"domain": "Thing", "range": "Thing", "definition": "n"}}, sample,
                   manifest_body={"namespace": ""})
    assert any("states no namespace" in p for p in ontologies.self_check("nameless"))
    with tempfile.TemporaryDirectory() as root, pytest.raises(ValueError, match="not usable"):
        init(root, name="Bare", ontology="bare")


def test_manifest_problems_are_named_precisely(ontologies_dir):
    base = base_ontology(ontologies_dir)
    bad = {"name": "Base", "release": 0, "extends": "oto-core", "engine": "latest", "carries": ["vocabulary", "lexicon", "gold"],
           "changelog": [{"release": 9, "note": "future"}, {"note": ""}]}
    with open(os.path.join(base, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(bad, f)
    problems = manifest.problems(base)
    text = "\n".join(problems)
    for expected in ("lowercase", "positive integer", "list of ontology names", "not a spec this engine reads",
                     "says it carries 'gold'", "holds ontology.rationale.json but manifest.json does not list",
                     "entry 1 is for release 9", "entry 2 needs"):
        assert expected in text, (expected, problems)


def test_engine_spec_is_compared_numerically():
    assert manifest.satisfies(">=0.1", "0.1.0.dev0") is True
    assert manifest.satisfies(">=0.1.0", "0.1.0.dev0") is True
    assert manifest.satisfies(">=0.2", "0.1.0.dev0") is False
    assert manifest.satisfies(">=1", "0.9.9") is False
    assert manifest.satisfies("~=0.1", "0.1.0") is None
    assert manifest.satisfies(">=0.1", __version__) is True


def test_a_ontology_written_for_a_newer_engine_is_refused_by_init(ontologies_dir):
    write_ontology(ontologies_dir, "future", {"Thing": {"definition": "t"}}, {"near": {"domain": "Thing", "range": "Thing", "definition": "n"}},
                   {"nodes": [_node("t.1", "Thing", "One")], "edges": []}, manifest_body={"engine": ">=99.0"})
    assert any("upgrade the engine" in p for p in ontologies.self_check("future"))
    with tempfile.TemporaryDirectory() as root, pytest.raises(ValueError, match="needs engine >=99.0"):
        init(root, slug="x", name="X", ontology="future")


# ---- composition ----

def test_extends_composes_bases_first_and_the_extender_wins(ontologies_dir):
    base_ontology(ontologies_dir)
    write_ontology(ontologies_dir, "claims", {"Document": {"definition": "a claims document"}, "Claim": {"definition": "a claim"}},
                   {"filed_by": {"domain": "Claim", "range": "Party", "definition": "filed"}, "cites": {"domain": "Document", "range": "Document", "inverse": "cited_by", "definition": "cites"}},
                   {"nodes": [_node("claim.1", "Claim", "One"), _node("doc.a", "Document", "A, revised")],
                    "edges": [{"from": "claim.1", "rel": "filed_by", "to": "party.x"}]},
                   manifest_body={"release": 1, "extends": ["base"], "carries": ["vocabulary", "rationale", "sample", "readme"]},
                   temporal=False)
    assert ontologies.parts("claims") == ["base", "claims"]
    result = ontologies.composed("claims")
    config = result["config"]
    assert list(config["classes"]) == ["Document", "Party", "Claim"], "bases first, then the extender"
    assert config["classes"]["Document"] == {"definition": "a claims document"}, "the extender wins a definition"
    assert config["temporal"] == TEMPORAL and result["report"]["temporal_from"] == "base"
    assert config["properties"]["cites"]["inverse"] == "cited_by"
    ids = [n["id"] for n in result["sample"]["nodes"]]
    assert ids == ["doc.a", "party.x", "claim.1"] and result["sample"]["nodes"][0]["label"] == "A, revised"
    assert result["sample"]["edges"] == [{"from": "claim.1", "rel": "filed_by", "to": "party.x"}]
    lines = compose.report_lines(result["report"])
    assert any("Document redescribed by claims" in l for l in lines)
    assert any("inverse changed by claims" in l for l in lines)
    assert any("sample node doc.a overridden by claims" in l for l in lines)
    assert ontologies.self_check("claims") == [], ontologies.self_check("claims")
    # load() is the composed form; load_raw() an ontology's own files.
    assert "Party" in ontologies.load("claims")[0]["classes"]
    assert "Party" not in ontologies.load_raw("claims")["config"]["classes"]


def test_widening_is_reported_and_narrowing_is_refused(ontologies_dir):
    base_ontology(ontologies_dir)
    write_ontology(ontologies_dir, "wider", {"Organisation": {"definition": "an org"}},
                   {"cites": {"domain": "Document|Organisation", "range": "Document", "definition": "cites"}},
                   {"nodes": [_node("org.1", "Organisation", "Org")], "edges": []},
                   manifest_body={"extends": ["base"]}, temporal=False)
    report = ontologies.composed("wider")["report"]
    assert report["widened"] == [("cites", "domain", "wider", ["Organisation"])]
    assert ontologies.self_check("wider") == []
    write_ontology(ontologies_dir, "narrower", {"Memo": {"definition": "a memo"}},
                   {"cites": {"domain": "Document", "range": "Memo", "definition": "cites"}},
                   {"nodes": [_node("memo.1", "Memo", "M")], "edges": []},
                   manifest_body={"extends": ["base"]}, temporal=False)
    with pytest.raises(ontologies.OntologyError, match="changes the range of 'cites'"):
        ontologies.composed("narrower")
    write_ontology(ontologies_dir, "narrower", {"Memo": {"definition": "a memo"}},
                   {"cites": {"domain": "Document", "range": "Document|Memo", "definition": "cites"}},
                   {"nodes": [_node("memo.1", "Memo", "M")], "edges": []},
                   manifest_body={"extends": ["base"]}, temporal=False)
    assert ontologies.self_check("narrower") == []
    write_ontology(ontologies_dir, "narrowest", {"Memo": {"definition": "a memo"}},
                   {"cites": {"domain": "Document", "range": "Document|Memo", "definition": "cites"}},
                   {"nodes": [_node("memo.1", "Memo", "M")], "edges": []},
                   manifest_body={"extends": ["narrower"]}, temporal=False)
    with open(os.path.join(ontologies_dir, "narrowest", "ontology.config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["properties"]["cites"] = {"domain": "Document", "range": "Document", "definition": "cites"}
    with open(os.path.join(ontologies_dir, "narrowest", "ontology.config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    problems = ontologies.self_check("narrowest")
    assert any("narrows the range of 'cites' from Document|Memo to Document" in p for p in problems), problems


def test_rules_merge_by_id_and_a_different_body_is_refused(ontologies_dir):
    rule = {"id": "r1", "kind": "policy", "severity": "warn", "when": [{"node": "d", "type": "Document"}],
            "then": {"flag": "hello"}, "why": "w", "validated_by": ""}
    base_ontology(ontologies_dir, rules=[rule])
    with open(os.path.join(ontologies_dir, "base", "manifest.json"), encoding="utf-8") as f:
        m = json.load(f)
    m["carries"].append("rules")
    with open(os.path.join(ontologies_dir, "base", "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(m, f)
    write_ontology(ontologies_dir, "same", {}, {}, {"nodes": [], "edges": []},
                   manifest_body={"extends": ["base"], "carries": ["vocabulary", "rationale", "rules", "sample", "readme"]},
                   temporal=False, rules=[rule])
    result = ontologies.composed("same")
    assert [r["id"] for r in result["rules"]] == ["r1"] and result["report"]["rules_shared"] == [("r1", "base", "same")]
    write_ontology(ontologies_dir, "other", {}, {}, {"nodes": [], "edges": []},
                   manifest_body={"extends": ["base"], "carries": ["vocabulary", "rationale", "rules", "sample", "readme"]},
                   temporal=False, rules=[dict(rule, then={"flag": "goodbye"})])
    with pytest.raises(ontologies.OntologyError, match="declares rule 'r1' differently from 'base'"):
        ontologies.composed("other")


def test_a_cycle_and_an_unknown_base_are_refused_with_the_chain(ontologies_dir):
    write_ontology(ontologies_dir, "a", {"A": {"definition": "a"}}, {"r": {"domain": "A", "range": "A", "definition": "r"}}, {"nodes": [_node("a.1", "A", "a")], "edges": []},
                   manifest_body={"extends": ["b"]})
    write_ontology(ontologies_dir, "b", {"B": {"definition": "b"}}, {"s": {"domain": "B", "range": "B", "definition": "s"}}, {"nodes": [_node("b.1", "B", "b")], "edges": []},
                   manifest_body={"extends": ["a"]})
    with pytest.raises(ontologies.OntologyError, match="extends itself through a -> b -> a"):
        ontologies.parts("a")
    write_ontology(ontologies_dir, "c", {"C": {"definition": "c"}}, {"t": {"domain": "C", "range": "C", "definition": "t"}}, {"nodes": [_node("c.1", "C", "c")], "edges": []},
                   manifest_body={"extends": ["nowhere"]})
    assert any("unknown ontology 'nowhere' (extended by 'c')" in p for p in ontologies.self_check("c"))


def test_rationale_for_an_inherited_class_is_ignored_and_reported(ontologies_dir):
    base_ontology(ontologies_dir)
    write_ontology(ontologies_dir, "ext", {"Claim": {"definition": "a claim"}}, {"about": {"domain": "Claim", "range": "Party", "definition": "about"}},
                   {"nodes": [_node("claim.1", "Claim", "One")], "edges": []},
                   manifest_body={"extends": ["base"]}, temporal=False,
                   rationale={"classes": {"Claim": {"question": "What is a claim?", "why": WHY, "alternatives": "", "validated_by": ""},
                                          "Party": {"question": "mine", "why": "an override that must not take", "alternatives": "", "validated_by": "me"}},
                              "properties": {"about": {"question": "How?", "why": WHY, "alternatives": "", "validated_by": ""}}})
    result = ontologies.composed("ext")
    assert result["rationale"]["classes"]["Party"]["why"] == WHY, "the declaring ontology's rationale stands"
    assert result["report"]["rationale_ignored"] == [("classes", "Party", "ext")]
    assert ontologies.self_check("ext") == []


# ---- the optional files ----

def test_a_guide_is_composed_leaf_first_checked_and_installed(ontologies_dir, capsys):
    base_ontology(ontologies_dir)
    base = os.path.join(ontologies_dir, "base")
    with open(os.path.join(base, "guide.md"), "w", encoding="utf-8") as f:
        f.write("# Base\n\n## What every graph here is for\n\nBase reasons.\n")
    write_ontology(ontologies_dir, "guided", {"Claim": {"definition": "a claim"}}, {"about": {"domain": "Claim", "range": "Party", "definition": "about"}},
                   {"nodes": [_node("claim.1", "Claim", "One")], "edges": []},
                   manifest_body={"extends": ["base"], "carries": ["vocabulary", "rationale", "sample", "readme", "guide"]},
                   temporal=False)
    with open(os.path.join(ontologies_dir, "guided", "guide.md"), "w", encoding="utf-8") as f:
        f.write("# Claims\n\n## What this graph is for\n\nClaims reasons.\n\n## Common mistakes\n\nNone yet.\n")
    assert ontologies.self_check("guided") == []
    guide = ontologies.guide_for("guided")
    assert guide.startswith("# Claims") and guide.index("Claims reasons") < guide.index("## Inherited from `base`") < guide.index("Base reasons")
    with tempfile.TemporaryDirectory() as root:
        assert main(["init", "--slug", "c", "--name", "C", "--project", root, "--ontology", "guided"]) == 0
        text = open(os.path.join(root, "GUIDE.md"), encoding="utf-8").read()
        assert "Claims reasons" in text and "Base reasons" in text and "Installed from the `guided` ontology" in text
    # a guide with no sections is named
    with open(os.path.join(ontologies_dir, "guided", "guide.md"), "w", encoding="utf-8") as f:
        f.write("Just prose.\n")
    assert any("guide.md has no sections" in p for p in ontologies.self_check("guided"))


def test_lexicon_interview_and_gold_are_checked_and_composed(ontologies_dir):
    base_ontology(ontologies_dir)
    write_ontology(ontologies_dir, "rich", {"Claim": {"definition": "a claim"}}, {"about": {"domain": "Claim", "range": "Party", "definition": "about"}},
                   {"nodes": [_node("claim.1", "Claim", "One")], "edges": []},
                   manifest_body={"extends": ["base"], "carries": ["vocabulary", "rationale", "sample", "readme", "lexicon", "interview", "gold"]},
                   temporal=False,
                   lexicon={"entries": [{"term": "the claim", "targets": ["claim.1"], "status": "current", "note": ""},
                                        {"term": "the mill", "targets": [], "status": "not_ingested", "note": "no doc"}]},
                   interview="# Claims\n\n## What is a claim here?\n\nAsk because...\n\n## Who files it?\n\nBecause...\n",
                   gold='{"class": "Claim", "pattern": "Who filed {label}?"}\n{"class": "Party", "pattern": "What did {label} file?"}\n')
    assert ontologies.self_check("rich") == []
    result = ontologies.composed("rich")
    assert [e["term"] for e in result["lexicon"]["entries"]] == ["the claim", "the mill"]
    assert result["interview"].count("## ") == 2 and len(result["gold"]) == 2
    # and each kind of mistake is named
    write_ontology(ontologies_dir, "poor", {"Claim": {"definition": "a claim"}}, {"about": {"domain": "Claim", "range": "Party", "definition": "about"}},
                   {"nodes": [_node("claim.1", "Claim", "One")], "edges": []},
                   manifest_body={"extends": ["base"], "carries": ["vocabulary", "rationale", "sample", "readme", "lexicon", "interview", "gold"]},
                   temporal=False,
                   lexicon={"entries": [{"term": "ghost", "targets": ["claim.9"], "status": "current", "note": ""}, {"aka": ["x"]}]},
                   interview="Just prose, no questions.\n",
                   gold='{"class": "Nope", "pattern": "x"}\nnot json\n{"class": "Claim"}\n')
    problems = "\n".join(ontologies.self_check("poor"))
    for expected in ("targets 'claim.9', which the sample does not hold", "lexicon entry 2 has no `term`",
                     "interview.md has no questions", "names class 'Nope'", "line 2 is not JSON", "needs a `pattern` string"):
        assert expected in problems, (expected, problems)


def test_a_deny_term_or_personal_data_makes_a_ontology_unpublishable(ontologies_dir, monkeypatch):
    monkeypatch.setenv("OTO_DENY_TERMS", "acmecorp, secretclient")
    write_ontology(ontologies_dir, "leaky", {"Thing": {"definition": "a thing for AcmeCorp"}}, {"near": {"domain": "Thing", "range": "Thing", "definition": "n"}},
                   {"nodes": [_node("t.1", "Thing", "One", card="4111 1111 1111 1111")], "edges": []})
    problems = ontologies.self_check("leaky")
    assert any("ontology.config.json in leaky names a deny term (acmecorp)" in p for p in problems), problems
    assert any("the sample holds personal data or a credential" in p for p in problems), problems
    monkeypatch.delenv("OTO_DENY_TERMS")
    problems = ontologies.self_check("leaky")
    assert not any("deny term" in p for p in problems) and any("personal data" in p for p in problems)


# ---- what a project records, and what init installs ----

def test_init_records_the_ontology_and_installs_what_it_carries(ontologies_dir):
    base_ontology(ontologies_dir)
    write_ontology(ontologies_dir, "rich", {"Claim": {"definition": "a claim"}}, {"about": {"domain": "Claim", "range": "Party", "definition": "about"}},
                   {"nodes": [_node("claim.1", "Claim", "One")], "edges": []},
                   manifest_body={"release": 4, "extends": ["base"],
                                  "carries": ["vocabulary", "rationale", "sample", "readme", "lexicon", "interview", "gold"]},
                   temporal=False,
                   lexicon={"entries": [{"term": "the claim", "targets": ["claim.1"], "status": "current", "note": ""}]},
                   interview="# Claims\n\n## What is a claim here?\n\nAsk.\n",
                   gold='{"class": "Claim", "pattern": "Who filed {label}?"}\n')
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="KB", ontology="rich")
        cfg = json.load(open(os.path.join(root, "project.config.json"), encoding="utf-8"))
        record = cfg["ontology"]
        assert record["name"] == "rich" and record["release"] == 4 and record["extends"] == ["base"]
        assert record["origin"] == ontologies.USER and record["source"] == ontologies.USER
        assert record["commit"] is None and record["registry"] is None and record["installed_at"]
        assert json.load(open(os.path.join(root, "lexicon.json"), encoding="utf-8"))["entries"][0]["term"] == "the claim"
        assert "## What is a claim here?" in open(os.path.join(root, "INTERVIEW.md"), encoding="utf-8").read()
        assert open(os.path.join(root, "gold", "patterns.jsonl"), encoding="utf-8").read().startswith('{"class": "Claim"')
        vocabulary = json.load(open(os.path.join(root, "ontology.config.json"), encoding="utf-8"))
        assert set(vocabulary["classes"]) == {"Document", "Party", "Claim"} and vocabulary["temporal"] == TEMPORAL
        assert vocabulary["name"] == "KB", "the project keeps its own name"
        from oto.builder import build
        build(Project.standard(root))


def test_init_records_a_built_in_ontology_and_a_merge(ontologies_dir):
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="a", name="A", ontology="software-architecture")
        record = json.load(open(os.path.join(root, "project.config.json"), encoding="utf-8"))["ontology"]
        assert record["name"] == "software-architecture" and record["origin"] == ontologies.BUILTIN
        assert record["extends"] == ["oto-core", "portfolio", "product"] and record["release"] >= 1
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="b", name="B", ontology="software-architecture,organization-process")
        record = json.load(open(os.path.join(root, "project.config.json"), encoding="utf-8"))["ontology"]
        assert record["source"] == "merge" and [p["name"] for p in record["parts"]] == ["software-architecture", "organization-process"]
        assert [p["extends"] for p in record["parts"]] == [["oto-core", "portfolio", "product"], ["oto-core"]]


def test_init_empty_installs_the_vocabulary_and_no_sample(ontologies_dir):
    """A real product's graph holds what its people said, not the pack's example; it still builds."""
    from oto.builder import build
    from oto.project import Project
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="e", name="E", ontology="software-architecture", empty=True)
        graph = json.load(open(os.path.join(root, "graph.json"), encoding="utf-8"))
        assert graph["nodes"] == [] and graph["edges"] == []
        assert not os.path.exists(os.path.join(root, "lexicon.json")), "the seed names the sample"
        config = json.load(open(os.path.join(root, "ontology.config.json"), encoding="utf-8"))
        assert "Component" in config["classes"] and "Requirement" in config["classes"]
        build(Project.standard(root))


def test_the_shipped_ontologies_extend_oto_core_and_keep_their_vocabulary():
    """The split must not change what a project gets: every shipped ontology still declares
    Document and the temporal fields, now inherited. software-architecture sits on product,
    which sits on the core."""
    assert "oto-core" in ontologies.available()
    core = ontologies.load_raw("oto-core")["config"]
    assert set(core["classes"]) == {"Document", "Action"} and "temporal" in core
    chain = {"portfolio": ["oto-core"], "product": ["portfolio"], "software-architecture": ["product"], "ddd": ["software-architecture"], "work": ["software-architecture"]}
    for name in ("auto-claims", "organization-process", "professional-services", "portfolio", "product", "software-architecture", "ddd", "work"):
        raw = ontologies.load_raw(name)
        assert raw["manifest"]["extends"] == chain.get(name, ["oto-core"]), name
        assert "temporal" not in raw["config"], name
        config, sample, _ = ontologies.load(name)
        assert "Document" in config["classes"] and config["temporal"] == core["temporal"], name
        assert "cites" in config["properties"]
        assert ontologies.self_check(name) == [], name


def test_export_writes_a_manifest_and_the_ontology_shows(ontologies_dir, capsys):
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="src", name="Source", ontology="organization-process")
        project = Project.standard(root)
        path, problems = ontologies.export(project, "my-org", summary="mine")
        assert problems == [], problems
        m = json.load(open(os.path.join(path, "manifest.json"), encoding="utf-8"))
        assert m["name"] == "my-org" and m["release"] == 1 and m["summary"] == "mine" and m["engine"].startswith(">=")
        assert m["carries"] == ["vocabulary", "rationale", "rules", "questions", "sample", "readme"] and m["changelog"][0]["release"] == 1, \
            "the core's rule is inherited, so the export carries rules"
        # exporting over it again is its next release, with the changelog kept
        path, problems = ontologies.export(project, "my-org", summary="mine again", force=True)
        assert problems == [], problems
        m = json.load(open(os.path.join(path, "manifest.json"), encoding="utf-8"))
        assert m["release"] == 2 and [e["release"] for e in m["changelog"]] == [2, 1]
        assert main(["ontology", "show", "my-org"]) == 0
        out = capsys.readouterr().out
        assert "my-org @2  (user)" in out and "self-check: clean" in out and "carries:  vocabulary, rationale, rules, questions, sample, readme" in out
        assert main(["ontology", "show", "no-such"]) == 1
        assert main(["ontology", "list"]) == 0
        assert "extends oto-core" in capsys.readouterr().out


def test_actions_are_carried_composed_checked_installed_and_exported(ontologies_dir, capsys):
    """An ontology ships actions like it ships rules: merged by id with the extender's winning,
    checked against the composed vocabulary and the sample, installed by `oto init`, carried
    by an export with the team remapped to the synthetic sample."""
    base_ontology(ontologies_dir)
    # the base is not oto-core: give it the core's Action vocabulary by hand
    config_path = os.path.join(ontologies_dir, "base", "ontology.config.json")
    with open(config_path, encoding="utf-8") as f:
        base_config = json.load(f)
    base_config["classes"]["Action"] = {"definition": "something that can be done"}
    base_config["properties"]["acts_on"] = {"domain": "Action", "definition": "acts on"}
    base_config["properties"]["executed_by"] = {"domain": "Action", "definition": "executed by"}
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(base_config, f)
    rationale_path = os.path.join(ontologies_dir, "base", "ontology.rationale.json")
    with open(rationale_path, encoding="utf-8") as f:
        base_rationale = json.load(f)
    base_rationale["classes"]["Action"] = {"question": "what can be done?", "why": "the hands need a description that is a fact",
                                           "alternatives": "", "validated_by": ""}
    with open(rationale_path, "w", encoding="utf-8") as f:
        json.dump(base_rationale, f)
    questions_path = os.path.join(ontologies_dir, "base", "questions.json")
    with open(questions_path, encoding="utf-8") as f:
        base_questions = json.load(f)
    base_questions["questions"].update(coverage_questions(["Action"], ["acts_on", "executed_by"]))
    with open(questions_path, "w", encoding="utf-8") as f:
        json.dump(base_questions, f)
    action = {"id": "action.ping-party", "label": "Ping a party", "description": "Calls the party's endpoint.",
              "subject": "Party", "executed_by": "party.x",
              "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
              "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
              "bind": {"name": "$label"}, "when": [{"node": "p", "type": "Party"}],
              "invoke": {"transport": "http", "method": "GET", "url": "https://parties.example/{name}"},
              "needs": [], "result": {"kind": "document"}}
    # the base ships one action; the extender ships the same id (its version wins) and a second one
    os.makedirs(os.path.join(ontologies_dir, "base", "actions"))
    with open(os.path.join(ontologies_dir, "base", "actions", "action.ping-party.json"), "w", encoding="utf-8") as f:
        json.dump(action, f)
    write_ontology(ontologies_dir, "acting", {"Claim": {"definition": "a claim"}}, {"about": {"domain": "Claim", "range": "Party", "definition": "about"}},
                   {"nodes": [_node("claim.1", "Claim", "One"), _node("party.x", "Party", "X")], "edges": []},
                   manifest_body={"extends": ["base"], "carries": ["vocabulary", "rationale", "sample", "readme", "actions"]},
                   temporal=False)
    os.makedirs(os.path.join(ontologies_dir, "acting", "actions"))
    with open(os.path.join(ontologies_dir, "acting", "actions", "action.ping-party.json"), "w", encoding="utf-8") as f:
        json.dump(dict(action, description="Calls the party's endpoint, the extender's way."), f)
    with open(os.path.join(ontologies_dir, "acting", "actions", "action.check-claim.json"), "w", encoding="utf-8") as f:
        json.dump(dict(action, id="action.check-claim", label="Check a claim", subject="Claim", when=[{"node": "c", "type": "Claim"}],
                       executed_by="party.x"), f)
    assert ontologies.self_check("acting") == []
    composed = ontologies.composed("acting")
    assert [a["id"] for a in composed["actions"]] == ["action.ping-party", "action.check-claim"]
    assert composed["actions"][0]["description"].endswith("the extender's way.")
    assert any("action action.ping-party from base replaced by acting" in l for l in compose.report_lines(composed["report"]))
    assert main(["ontology", "show", "acting"]) == 0
    assert ", 2 action(s)" in capsys.readouterr().out
    # a mistake in a shipped action, and a team the sample lacks, are named
    with open(os.path.join(ontologies_dir, "acting", "actions", "action.bad.json"), "w", encoding="utf-8") as f:
        json.dump(dict(action, id="action.bad", subject="Nope", executed_by="party.ghost"), f)
    problems = "\n".join(ontologies.self_check("acting"))
    assert "subject class 'Nope' is not declared" in problems and "executed_by 'party.ghost', which the sample does not hold" in problems
    os.remove(os.path.join(ontologies_dir, "acting", "actions", "action.bad.json"))
    with tempfile.TemporaryDirectory() as root:
        assert main(["init", "--slug", "a", "--name", "A", "--project", root, "--ontology", "acting"]) == 0
        out = capsys.readouterr().out
        assert "actions/action.ping-party.json" in out and "actions/action.check-claim.json" in out
        assert sorted(os.listdir(os.path.join(root, "actions"))) == ["action.check-claim.json", "action.ping-party.json"]
        assert main(["actions", "check", "--project", root]) == 0
        capsys.readouterr()
        # exported: the actions ride along, executed_by remapped to the invented sample's Party
        project = Project.standard(root)
        path, problems = ontologies.export(project, "acting-copy")
        assert problems == [], problems
        exported = ontologies.actions_for("acting-copy")
        assert [a["id"] for a in exported] == ["action.check-claim", "action.ping-party"]
        sample_ids = {n["id"] for n in ontologies.composed("acting-copy")["sample"]["nodes"]}
        assert all(a["executed_by"] in sample_ids for a in exported)
