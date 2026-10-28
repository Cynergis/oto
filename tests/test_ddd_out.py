"""The ddd pack's tools out (ADR-0006, step 5c). The storming importer and the ddd command live in
oto/packs/ddd, loaded through the pack's manifest; nothing in the engine imports them, and the pack
reaches the engine's helpers (a slug, the graph's ids) through oto/naming.py like every pack."""
import contextlib
import io
import os

from oto.cli import main
from oto.model import ontologies
from oto.packs import ddd as _ddd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GONE = ("oto/ddd.py", "oto/cli/ddd.py")
ENGINE = ("oto/arch.py", "oto/factory.py", "oto/cli/__init__.py", "oto/builder.py", "oto/serve/engine.py", "oto/naming.py")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def test_the_storming_importer_is_behind_the_pack_and_the_engine_imports_none_of_it():
    for path in GONE:
        assert not os.path.exists(os.path.join(ROOT, path)), path
    for name in ("__init__.py", "cli.py"):
        assert os.path.exists(os.path.join(ROOT, "oto", "packs", "ddd", name)), name
    for path in ENGINE:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            imports = "\n".join(l for l in f.read().splitlines() if l.lstrip().startswith(("from ", "import ")))
        assert "packs.ddd" not in imports and "import ddd" not in imports and ".ddd import" not in imports, path
    assert _ddd.storm and _ddd.TYPES and _ddd.DddError
    with open(os.path.join(ROOT, "oto", "packs", "ddd", "__init__.py"), encoding="utf-8") as f:
        source = f.read()
    assert "from ...naming import" in source, "the pack uses the engine's helpers through the naming module"
    provides = ontologies.manifest_for("ddd")["provides"]
    assert provides == {"commands": [{"name": "ddd", "module": "oto.packs.ddd.cli", "label": "ddd"}]}
    code, out = _cli("ddd", "--help")
    assert code == 0 and "storm" in out, out
    code, out = _cli("--help")
    assert "  ddd " in out, out


def test_the_docs_point_at_the_pack():
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "packs/ddd" in text
