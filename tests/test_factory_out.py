"""The factory's engine-side commands out (ADR-0006, step 5d, the last pack of step 5). The spec,
the plan, the run scope, the run graph, criteria, deviations and metrics live in oto/packs/factory
with the factory command, loaded through the factory-run pack's manifest. One thing stays with the
engine: measuring a requirement from a report or a stated value (`oto arch measure`, H6) is the
architecture's, so it moves into the arch module. Nothing in the engine imports the pack."""
import contextlib
import io
import os

from oto import arch as _arch
from oto.cli import main
from oto.model import ontologies
from oto.packs import factory as _factory

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GONE = ("oto/factory.py", "oto/cli/factory.py")
ENGINE = ("oto/arch.py", "oto/cli/arch.py", "oto/cli/__init__.py", "oto/builder.py", "oto/serve/engine.py", "oto/naming.py", "oto/assertion.py")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def test_the_factory_is_behind_its_pack_and_the_measurement_is_the_architecture_s():
    for path in GONE:
        assert not os.path.exists(os.path.join(ROOT, path)), path
    for name in ("__init__.py", "cli.py"):
        assert os.path.exists(os.path.join(ROOT, "oto", "packs", "factory", name)), name
    for path in ENGINE:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            imports = "\n".join(l for l in f.read().splitlines() if l.lstrip().startswith(("from ", "import ")))
        assert "packs.factory" not in imports and "import factory" not in imports and ".factory import" not in imports, path
    assert _factory.spec and _factory.plan and _factory.scope and _factory.criteria and _factory.run_start and _factory.deviate and _factory.FactoryError
    assert not hasattr(_factory, "measure") and not hasattr(_factory, "measure_from"), "measuring a requirement left the factory"
    assert callable(_arch.measure) and callable(_arch.measure_from), "and is the architecture's (H6)"
    with open(os.path.join(ROOT, "oto", "packs", "factory", "__init__.py"), encoding="utf-8") as f:
        source = f.read()
    assert "from .. import policy as _policy" in source, "the factory reads the policy's denials through the pack: a pack on a pack"
    provides = ontologies.manifest_for("factory-run")["provides"]
    assert provides == {"commands": [{"name": "factory", "module": "oto.packs.factory.cli", "label": "factory"}]}
    code, out = _cli("factory", "--help")
    assert code == 0 and "spec" in out and "plan" in out, out
    code, out = _cli("arch", "--help")
    assert code == 0 and "measure" in out, out


def test_a_report_still_reads_as_a_measurement_through_the_arch_module(tmp_path):
    k6 = tmp_path / "summary.json"
    k6.write_text('{"metrics": {"http_req_duration": {"values": {"p(95)": 870.2}}, "http_reqs": {"values": {"count": 5000}}}}')
    kind, text = _arch.measure_from(str(k6))
    assert kind == "k6" and "870" in text and "5000" in text


def test_the_docs_point_at_the_pack_and_keep_the_measurement_with_the_architecture():
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "packs/factory" in text and "oto arch measure" in text
