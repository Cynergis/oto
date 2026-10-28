# CALM: the FINOS architecture framework, as an adapter

On `architecture`: the pack adds no term. A CALM 1.x model (the FINOS Common Architecture Language
Model, [release 1.0](https://calm.finos.org/release/1.0/meta/core.json); the core schema is unchanged
through 1.3) maps onto the architecture pack's reified model, and what the pack brings is the adapter
its manifest provides (`provides.adapters`, `oto/packs/calm.py`), chosen by name:

    oto arch import --framework calm --file model.json --at <date> [--environment environment.<id>]
    oto arch export --framework calm [--out model.json]
    oto arch migrate --framework calm --by <who>        # a graph written before the architecture pack's release 5

**How CALM maps.** A CALM node is an estate node by its `node-type`: a `system` or `ecosystem` is a
`System`, a `service` or `webclient` a `Component`, a `database`, `data-asset`, `datastore` or `ldap`
directory (a store of identities) a `DataStore`, a `network` an `Environment`, an `actor` a `Role`,
and any other type a `Component`, since CALM allows any string. The node carries `external_id`
(CALM's `unique-id`), `external_type` (the `node-type` as given) and `external_payload` (CALM's
`metadata` and `details`, kept as the JSON it gave). A CALM relationship is a `Relationship` node
with its `kind` (interacts, connects, deployed-in, composed-of, options), its `protocol` from CALM's
list and its ends; controls and flows are `Control` and `Flow` nodes with their steps; the plain
estate edges are derived beside them (`part_of` from composed-of in a system, `runs_in` from
deployed-in in a network, `exposes` from a node's interfaces, `consumes` and `depends_on` from
connects) so the estate's own questions answer. The model's document carries `framework: calm` and
the model's header as `external_payload`, which is how the export finds the model.

**In and out.** `import` writes a document in the corpus (`build/documents/calm-<slug>.md`, kept in
`archive/`: one line per node, interface, relationship, control, flow and step, each the evidence its
fact quotes) and a proposal in the architecture vocabulary that goes through the gates like any other
change; what CALM does not say is not invented (a node deployed nowhere runs nowhere unless
`--environment` names the estate's environment; a node composed in nothing is part of nothing, which
the estate's shape names at the gate). `export` walks the live graph back into a CALM model: export
of import equals the input, up to what the graph cannot tell from absence. A control a person or a
command authored in the graph (the policy pack's generated IAM controls) comes out under the node it
safeguards when it carries an `external_id`.

**Migration.** Release 5 of the architecture pack renamed `calm_id`, `calm_type`, `calm_metadata`,
`calm_details`, `calm_header` and `calm_option` to `external_id`, `external_type`, `external_payload`
and `framework`. A graph written before it reads as before once migrated:
`oto arch migrate --framework calm --by <who>` rewrites the live graph in place (the previous one kept
as `graph.previous.json`), records an audit record naming the nodes, and refuses while a candidate is
open; then `oto build`.

**Another framework** is another pack of this shape: a manifest whose `provides.adapters` names a
module with `import` and `export` functions of the same signatures, and whatever terms the framework
adds to the reified model. The engine names none of them.

This is a first draft; edit it.
