"""oto rules, the gates, the lock, and the ontology that ships rules."""
import json
import os
import tempfile

from oto.cli import main
from oto.curate import diff, session
from oto.model import ontologies
from oto.project import Project
from oto.reason import rules as _rules
from oto.scaffold import init


PRODUCT_RULES = ["feature-serves-its-requirements-purpose", "requirement-in-scope-through-feature", "risk-reaches-product",
                 "open-question-blocks-release", "product-pursues-objective", "requirement-serves-a-purpose",
                 "value-proposition-has-success-criterion", "decision-is-documented", "scope-is-not-contradictory",
                 "shipped-release-is-not-blocked"]
ARCH_RULES = ["intended-fact-overdue"] + PRODUCT_RULES + ["risk-reaches-system", "consumer-depends-on-provider"]


def _arch(root):
    init(root, name="Arch", ontology="software-architecture")
    return Project.standard(root)


def test_the_ontology_ships_rules_that_install_and_validate(capsys):
    assert [r["id"] for r in ontologies.rules_for("software-architecture")] == ARCH_RULES, \
        "the core's rule first, then the product's, then the ontology's own"
    assert ontologies.self_check("software-architecture") == []
    with tempfile.TemporaryDirectory() as root:
        project = _arch(root)
        assert os.path.exists(_rules.path_for(project))
        capsys.readouterr()
        assert main(["rules", "check", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "13 rule(s)" in out and "risk-reaches-system" in out and "not yet confirmed" in out
        assert "have no `validated_by`" in out


def test_check_reports_problems_and_exits_non_zero(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _arch(root)
        _rules.save(project, [{"id": "bad", "kind": "derive", "when": [{"edge": ["a", "menaces", "b"]}],
                               "then": {"edge": ["a", "threatens", "b"]}, "why": "x"}])
        capsys.readouterr()
        assert main(["rules", "check", "--project", root]) == 1
        assert "relation 'menaces' is not declared" in capsys.readouterr().out


def test_accept_and_diff_track_the_rules_in_the_lock(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _arch(root)
        capsys.readouterr()
        assert main(["rules", "diff", "--project", root]) == 0
        assert "no accepted vocabulary" in capsys.readouterr().out
        assert main(["ontology", "accept", "--project", root]) == 0
        assert "13 rules" in capsys.readouterr().out
        assert len(_rules.read_lock(project)) == 13
        by_id = {r["id"]: r for r in _rules.load(project)}
        by_id["risk-reaches-system"]["then"] = {"edge": ["r", "threatens", "c"]}
        _rules.save(project, [r for r in by_id.values() if r["id"] != "decision-is-documented"]
                    + [dict(by_id["decision-is-documented"], id="new-policy")])
        assert main(["rules", "diff", "--project", root, "--strict"]) == 1
        out = capsys.readouterr().out
        assert "removed   decision-is-documented" in out and "changed   risk-reaches-system" in out and "added     new-policy" in out
        assert main(["rules", "accept", "--project", root]) == 0
        assert main(["rules", "diff", "--project", root]) == 0
        assert "no change" in capsys.readouterr().out


def test_curate_check_applies_policy_rules_to_the_candidate(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _arch(root)
        declared = _rules.load(project)
        next(r for r in declared if r["id"] == "decision-is-documented")["severity"] = "blocking"
        _rules.save(project, declared)
        assert main(["curate", "start", "--project", root]) == 0
        candidate = session.candidate(project)
        candidate["nodes"].append({"id": "decision.no-doc", "type": "Decision", "label": "Undocumented",
                                   "aliases": [], "summary": "s", "attributes": {}, "tags": [], "as_of": "2026-01-01",
                                   "valid_from": "2026-01-01", "source_doc": "sample", "status": "current",
                                   "sources": ["sample"], "evidence": [{"doc": "sample", "where": "p.1"}]})
        with open(session.candidate_path(project), "w", encoding="utf-8") as f:
            json.dump(candidate, f)
        capsys.readouterr()
        assert main(["curate", "check", "--project", root]) == 1
        out = capsys.readouterr().out
        assert "policy decision-is-documented" in out and "decision.no-doc" in out and "blocking" in out
        next(r for r in declared if r["id"] == "decision-is-documented")["severity"] = "warn"
        _rules.save(project, declared)
        assert main(["curate", "check", "--project", root]) == 0
        assert "gap" in capsys.readouterr().out


def test_ontology_check_reports_standing_findings_and_status_counts_rules(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _arch(root)
        with open(project.graph_path, encoding="utf-8") as f:
            graph = json.load(f)
        graph["edges"] = [e for e in graph["edges"] if e["rel"] != "documented_in"]
        with open(project.graph_path, "w", encoding="utf-8") as f:
            json.dump(graph, f)
        capsys.readouterr()
        assert main(["ontology", "check", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "rules: 13 declared" in out and "policy finding(s)" in out and "decision-is-documented" in out
        assert main(["status", "--project", root]) == 0
        assert "13 rule(s)" in capsys.readouterr().out


def test_export_and_merge_carry_rules(tmp_path, monkeypatch):
    monkeypatch.setenv(ontologies.USER_DIR_ENV, str(tmp_path))
    with tempfile.TemporaryDirectory() as root:
        project = _arch(root)
        declared = _rules.load(project)
        declared[0]["validated_by"] = "A. Expert, 2026-09-01"
        _rules.save(project, declared)
        _path, problems = ontologies.export(project, "arch-copy")
        assert problems == []
        shipped = ontologies.rules_for("arch-copy")
        assert len(shipped) == 13 and all(r["validated_by"] == "" for r in shipped), "confirmation does not carry over"
    config, _s, _r, _rat, _rep = ontologies.merge(["software-architecture", "organization-process"])
    assert [r["id"] for r in config["_rules"]] == ARCH_RULES
    with tempfile.TemporaryDirectory() as root:
        init(root, name="Both", ontology="software-architecture,organization-process")
        assert len(_rules.load(Project.standard(root))) == 13
        config = json.load(open(os.path.join(root, "ontology.config.json"), encoding="utf-8"))
        assert "_rules" not in config, "the merge's carrier key must not leak into the config"
