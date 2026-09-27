"""The compile stages honour their contract: importable without side effects, one `run(project)`
each, no built-in vocabulary, no paths of their own."""
import importlib

import pytest

STAGE_MODULES = [
    "oto.compile.knowledge",
    "oto.compile.ontology",
    "oto.compile.semantic",
    "oto.targets.sqlite",
]


@pytest.mark.parametrize("path", STAGE_MODULES)
def test_stage_exposes_run(path):
    """Importing a stage must have no side effects, and it must expose run(project)."""
    module = importlib.import_module(path)
    assert callable(getattr(module, "run", None)), "%s has no run()" % path


def test_schema_sql_is_not_indented():
    """SQLite stores DDL text verbatim, so the schema must never carry added indentation."""
    from oto.targets.sqlite import SCHEMA_SQL

    for line in SCHEMA_SQL.splitlines():
        if line.strip():
            assert not line.startswith("    "), "indented DDL line would change the database bytes"


def test_missing_config_fails_loudly():
    """A missing project config must raise, never fall back to another project's defaults."""
    import tempfile

    from oto.project import Project, ProjectError

    with tempfile.TemporaryDirectory() as root:
        import os
        os.makedirs(os.path.join(root, "src"))
        project = Project(data=root, src=os.path.join(root, "src"))
        with pytest.raises(ProjectError):
            project.config()


def test_no_builtin_vocabulary():
    """A stage must never carry a fallback vocabulary. Ontology comes only from the config."""
    import inspect

    from oto.compile import ontology

    source = inspect.getsource(ontology)
    # A built-in vocabulary would appear as a large literal mapping of class names to descriptions.
    assert "CLASSES = {" not in source, "ontology stage still carries a built-in class list"
    assert "PROPS = {" not in source or "_cfg" in source


def test_identity_defaults_derive_from_slug():
    """No generated name may be inherited from another project."""
    import json
    import os
    import tempfile

    from oto.project import Project

    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, "src"))
        with open(os.path.join(root, "project.config.json"), "w", encoding="utf-8") as f:
            json.dump({"slug": "acme", "name": "Acme"}, f)
        identity = Project(data=root, src=os.path.join(root, "src")).identity()
        assert identity["db_name"] == "acme.db"
        assert identity["prefix"] == "acme"
        assert identity["server_name"] == "acme-kg"
        assert "acme" in identity["namespace"]


def test_missing_ontology_config_raises():
    """A project with no declared vocabulary must fail, not inherit one."""
    import json
    import os
    import tempfile

    from oto.compile import ontology
    from oto.project import Project, ProjectError

    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, "build"))
        with open(os.path.join(root, "project.config.json"), "w", encoding="utf-8") as f:
            json.dump({"slug": "acme", "name": "Acme"}, f)
        project = Project.standard(root)
        # The graph the stage reads lives wherever the LAYOUT says, not at a hardcoded path.
        os.makedirs(project.layout.graph, exist_ok=True)
        with open(os.path.join(project.layout.graph, "knowledge-graph.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"meta": {"node_types": [], "relationship_types": []},
                       "nodes": [], "edges": []}, f)
        with pytest.raises(ProjectError):
            ontology.run(project)
