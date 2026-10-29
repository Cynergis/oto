"""A framework adapter the engine's tests carry (ADR-0008: the engine ships none). The `plain`
framework's model is already the architecture pack's reified model: a JSON file holding the
document an adapter writes and the proposal it makes, as `tests/fixtures/arch/*.model.json`. What
the engine does with any framework's model (the corpus, the proposal, the gates, compile on merge,
the code map beside it) is tested through this one; what CALM is, is the calm pack's own tests."""
import json
import os

from oto.arch import ArchError, CONTROL, FLOW, INTERFACE, ISO_DATE, PREFIX, RELATIONSHIP

FRAMEWORK = "plain"


def model_slug(path, name=None):
    stem = os.path.basename(path)
    for suffix in (".json", ".model"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
    return name or stem


def read_model(project, path, at, name=None, environment=None):
    """Write the model's document into the corpus and its proposal under proposals/. Returns what
    `oto arch import` prints, as any adapter does."""
    if not at or not ISO_DATE.match(str(at)):
        raise ArchError("--at YYYY-MM-DD is required: the date the model was read is never defaulted")
    if not os.path.isfile(path):
        raise ArchError("no such model: %s" % path)
    with open(path, encoding="utf-8") as f:
        try:
            model = json.load(f)
        except ValueError as exc:
            raise ArchError("%s is not JSON: %s" % (path, exc))
    if environment:
        from oto.naming import graph_ids
        if environment not in graph_ids(project):
            raise ArchError("the graph holds no %s: --environment names an Environment the estate declares" % environment)
    doc = model_slug(path, name)
    proposal = model["proposal"]
    corpus = os.path.join(project.layout.corpus, doc + ".md")
    archive = os.path.join(project.layout.archive, doc + ".md")
    for target in (corpus, archive):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(model["document"])
    out_dir = os.path.join(project.data, "proposals")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, doc + ".json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(proposal, f, indent=2, ensure_ascii=False)
        f.write("\n")
    count = lambda kind: sum(1 for n in proposal["nodes"] if n["type"] == kind)  # noqa: E731
    return {"doc": doc, "document": corpus, "archive": archive, "proposal": out, "schema": None,
            "nodes": sum(1 for n in proposal["nodes"] if n["type"] in PREFIX), "relationships": count(RELATIONSHIP),
            "controls": count(CONTROL), "flows": count(FLOW), "interfaces": count(INTERFACE), "gaps": list(model.get("gaps") or [])}


def write_model(project):
    """The live graph's framework facts back out: every node with an external_id, as it stands."""
    from oto.curate import session
    graph = session.live(project)
    nodes = [{"id": n["id"], "external_id": n["attributes"]["external_id"], "type": n["type"]}
             for n in graph["nodes"] if (n.get("attributes") or {}).get("external_id")]
    if not nodes:
        raise ArchError("the graph holds no %s facts: nothing to export" % FRAMEWORK)
    return {"framework": FRAMEWORK, "nodes": nodes}
