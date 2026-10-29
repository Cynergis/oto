"""The data pack's tools out (ADR-0006, step 5b). Introspection, lineage, usage and meaning live in
oto/packs/data with the pack's command, loaded through its manifest; the engine keeps the two helpers
every pack and its own tools share (oto/naming.py: a slug for a node id, the ids the live graph
holds), which were the data module's. The engine imports nothing else of the pack."""
import contextlib
import io
import os

from oto import naming
from oto.cli import main
from oto.model import ontologies
from oto.packs import data as _data
from oto.packs.data import lineage, meaning, usage
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GONE = ("oto/data.py", "oto/lineage.py", "oto/usage.py", "oto/meaning.py", "oto/cli/data.py")
ENGINE = ("oto/arch.py", "oto/packs/ddd/__init__.py", "oto/cli/__init__.py", "oto/builder.py", "oto/serve/engine.py",
          "oto/packs/policy/iam.py", "oto/naming.py")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def test_the_helpers_are_the_engine_s_and_the_tools_are_behind_the_pack():
    for path in GONE:
        assert not os.path.exists(os.path.join(ROOT, path)), path
    for name in ("__init__.py", "lineage.py", "usage.py", "meaning.py", "cli.py"):
        assert os.path.exists(os.path.join(ROOT, "oto", "packs", "data", name)), name
    for path in ENGINE:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            imports = "\n".join(l for l in f.read().splitlines() if l.lstrip().startswith(("from ", "import ")))
        assert "packs.data" not in imports and ".data import" not in imports and "import data" not in imports and "lineage" not in imports and "meaning" not in imports, path
    assert naming.slug("Ledger DB (prod)") == "ledger-db-prod" and naming.slug("") == ""
    assert _data._slug is naming.slug and _data._graph_ids is naming.graph_ids, "the pack keeps its names for the engine's helpers"
    assert _data.introspect and lineage.lineage and usage and meaning
    provides = ontologies.manifest_for("data")["provides"]
    assert provides == {"commands": [{"name": "data", "module": "oto.packs.data.cli", "label": "data"}]}


def test_the_ids_the_graph_holds_come_from_the_engine(tmp_path):
    root = str(tmp_path / "ledger")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="ledger", name="Ledger", ontology="data")
    ids = naming.graph_ids(Project.standard(root))
    assert "datastore.ledger" in ids and all(isinstance(i, str) for i in ids)
    code, out = _cli("data", "--help")
    assert code == 0 and "introspect" in out, out


def test_the_docs_point_at_the_pack_and_the_naming_module():
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "packs/data" in text and "naming.py" in text
