"""The core, end to end, on the engine alone (docs/E2E-CORE.md): tools/e2e_core.sh creates a vocabulary by
hand, takes a document through ingest and the four gates, builds, queries and serves the graph, deploys
it through dev, test and prod, exports the vocabulary, makes a pack of it, publishes the pack to a
registry it creates, installs it and starts a second project from it, with no pack installed and no
vocabulary but oto-core in reach. The script stops at the first miss, so the suite holds what the
document promises: every "pass when" in it is a check here."""
import os
import shutil
import socket
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "tools", "e2e_core.sh")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(shutil.which("git") is None or shutil.which("bash") is None, reason="the deploy and registry steps need git; the script is bash")
def test_the_core_runs_end_to_end_on_the_engine_alone(tmp_path):
    env = dict(os.environ, OTO="%s -m oto.cli" % sys.executable, PORT=str(_free_port()), PYTHONPATH=ROOT)
    for key in ("OTO_ONTOLOGIES", "OTO_PACKS", "CLAUDE_CONFIG_DIR", "OTO_REGISTRIES"):
        env.pop(key, None)                                   # the script isolates the engine itself, under its work dir
    done = subprocess.run(["bash", SCRIPT, str(tmp_path / "work")], cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stdout[-4000:] + done.stderr[-2000:]
    assert "ALL STEPS PASSED" in done.stdout, done.stdout[-2000:]
    for promised in ("accepted vocabulary version 1", "ready to apply", "b.plate=NW-101", "promoted test -> prod",
                     "the registry was created", "added pack garage @1", "record: garage @1, origin pack, pack garage"):
        assert promised in done.stdout, promised
    work = tmp_path / "work"
    assert (work / "garage" / "oto.deploy.json").exists() and (work / "garage2" / "project.config.json").exists()
    assert sorted(os.listdir(work / "packs")) == ["garage"], "the only pack on the machine is the one the test made"


def test_the_document_and_the_script_tell_the_same_story():
    with open(os.path.join(ROOT, "docs", "E2E-CORE.md"), encoding="utf-8") as f:
        doc = f.read()
    with open(SCRIPT, encoding="utf-8") as f:
        script = f.read()
    for command in ("oto ontology accept", "oto ingest run", "oto curate apply", "oto ingest complete", "oto query", "oto serve",
                    "oto deploy init", "oto publish", "oto sync", "oto pack new", "oto pack try", "oto pack check", "oto pack publish",
                    "oto registry add", "oto pack add", "--pack garage"):
        assert command in doc, command
        assert command.replace("oto ", "$OTO ") in script or command in script, command
    assert "ADR-0011" in doc and "E2E-TESTING.md" in doc, "it says what it is: the engine alone, and where the rest is"
    assert "--source" in doc and "cannot be promoted" in doc, "the one convention a reader must know for promotion"
    with open(os.path.join(ROOT, "docs", "E2E-TESTING.md"), encoding="utf-8") as f:
        assert "E2E-CORE.md" in f.read(), "the wider guide points at the core test"
