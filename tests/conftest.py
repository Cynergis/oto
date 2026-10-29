"""Make the package importable when the suite runs without an install.

CI installs the package, which is the proper fix. This keeps a plain `pytest` working from any
directory during development, so a test never passes or fails because of the current directory.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# The suite must see only the shipped ontologies, never whatever the developer keeps in ~/.oto, the
# packs installed there, or the packs Claude Code installed (whose embedded ontologies resolve by name).
os.environ.setdefault("OTO_ONTOLOGIES", os.path.join(REPO_ROOT, ".no-user-ontologies"))
os.environ.setdefault("OTO_PACKS", os.path.join(REPO_ROOT, ".no-user-packs"))
os.environ.setdefault("CLAUDE_CONFIG_DIR", os.path.join(REPO_ROOT, ".no-claude-config"))


# The engine ships no architecture framework (ADR-0008). The tests that need one, for what the core
# does with any framework's model, use the `plain` framework under tests/fixtures/frameworks: its
# adapter reads a model that is already the reified model (tests/fixtures/arch/*.model.json).
import pytest  # noqa: E402

FRAMEWORKS = os.path.join(REPO_ROOT, "tests", "fixtures", "frameworks")
PLAIN_MODEL = os.path.join(REPO_ROOT, "tests", "fixtures", "arch", "invoice-platform.model.json")


@pytest.fixture
def plain_framework(monkeypatch):
    """The `plain` framework pack discovered through OTO_ONTOLOGIES, its code put on the path by the engine."""
    monkeypatch.setenv("OTO_ONTOLOGIES", FRAMEWORKS)
    sys.modules.pop("plain_model", None)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if not p.endswith(os.path.join("plain", "code"))])
    return PLAIN_MODEL
