"""OTO: build, validate and serve a temporal knowledge graph.

The package follows the life of a project, and so does docs/ARCHITECTURE.md:

    scaffold.py    oto init: a project holds data only
    intake/        raw documents -> one Document -> corpus markdown, behind a privacy gate
    model/         the declared vocabulary: ontologies, versioning, conformance, rationale
    validate/      the integrity gate before a build, the privacy gate before ingest, the self-test
    compile/       the three deterministic stages: knowledge, ontology, semantic
    targets/       the fourth: the indexed SQLite store a server reads
    builder.py     runs the stages as a transaction; project.py and layout.py say where things live
    curate/        the only path that changes what the graph believes, with supersession and vetting
    serve/         the warm query engine: ten tools over JSON-RPC 2.0, or one query per call
    bench/         gold questions, three systems, deterministic metrics, and the feedback loop
    cli/           one module per command
    ontologies/     the starter vocabularies `oto init --ontology` installs
"""
__version__ = "0.8.1"
