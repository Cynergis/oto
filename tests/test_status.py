"""`oto status` reports the lifecycle position and one next step."""
import json
import os
import tempfile

from oto.cli import main
from oto.cli.status import gather
from oto.project import Project
from oto.scaffold import init


def test_a_fresh_project_asks_for_documents(capsys):
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="KB")
        s = gather(Project.standard(root))
        assert (s["corpus"], s["nodes"], s["built"]) == (0, 0, False)
        assert "inbox" in s["next"]
        assert main(["status", "--project", root]) == 0
        assert "next:" in capsys.readouterr().out


def test_documents_in_the_inbox_point_at_ingest():
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="KB")
        with open(os.path.join(root, "inbox", "a.md"), "w") as f:
            f.write("# A\n")
        assert gather(Project.standard(root))["next"].startswith("oto ingest")


def test_a_ontology_project_walks_build_then_accept_then_serve():
    with tempfile.TemporaryDirectory() as root:
        assert main(["init", "--slug", "kb", "--project", root, "--ontology", "auto-claims"]) == 0
        project = Project.standard(root)
        assert gather(project)["next"] == "oto build"
        assert main(["build", "--project", root]) == 0
        s = gather(project)
        assert s["built"] and not s["stale"]
        assert s["rationale"]["classes_with_rationale"] == s["classes"]
        assert s["next"].startswith("oto ontology accept")
        assert main(["ontology", "accept", "--project", root]) == 0
        assert "gold set" in gather(project)["next"]


def test_an_open_candidate_and_a_stale_build_are_flagged():
    with tempfile.TemporaryDirectory() as root:
        main(["init", "--slug", "kb", "--project", root, "--ontology", "auto-claims"])
        main(["build", "--project", root])
        project = Project.standard(root)
        assert main(["curate", "start", "--project", root]) == 0
        assert gather(project)["candidate"] and "candidate is open" in gather(project)["next"]
        main(["curate", "abort", "--project", root])
        # Touch the graph after the build: the database is now behind its inputs.
        graph = project.graph_path
        os.utime(graph, (os.path.getmtime(graph) + 10, os.path.getmtime(graph) + 10))
        s = gather(project)
        assert s["stale"] and s["next"].startswith("oto build")


def test_json_output_is_machine_readable(capsys):
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="KB")
        capsys.readouterr()
        assert main(["status", "--project", root, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["slug"] == "kb" and "next" in payload
