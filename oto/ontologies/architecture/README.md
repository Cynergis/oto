# Architecture — the graph agents consult before they change code

On `software-architecture` (and so on `product` and `portfolio`): the architecture as implementation
reads it, aligned with **CALM 1.0**, the FINOS Common Architecture Language Model, pinned at
`https://calm.finos.org/release/1.0/meta/core.json`. CALM stays the contract the gates check; this graph is the derived copy an
agent queries before it edits, so it avoids a violation instead of a gate rejecting one (roadmap
Epic H).

**A CALM node is an estate node.** No `Node` class: a CALM `system` or `ecosystem` is a `System`, a
`service` or `webclient` is a `Component`, a `database`, `data-asset` or `ldap` directory is a
`DataStore`, a `network` is an `Environment`, an `actor` is a `Role`. Each carries `calm_id` (the unique-id, so it
round-trips) and `calm_type` (which of the nine it was), and `calm_metadata` as the JSON the model
gave. An `Interface` carries `calm_id`, `definition_url` and `config`.

**A CALM relationship is a node.** `Relationship` has a `kind` (interacts, connects, deployed-in,
composed-of, options), a `protocol` from CALM's list, `connects_from` its source (an actor, a node,
a container) and `connects_to` each destination, `via` the interface a connection goes through, and
`offers_option` the decisions an options relationship chooses between. It is a node because a `Flow` walks
relationships in order (`FlowStep`, `sequence`, `direction`, `over`) and a `Control` `safeguards` them,
which an edge could carry neither of. A control has its own relation, apart from a decision's `governs`,
so that what no control safeguards can be asked (AR8). The plain estate edges (`consumes`, `part_of`, `runs_in`,
`depends_on`) are derived beside it by the importer, so SA1 to SA17 keep answering.

**The implementation trace.** An `NFR` is a `Requirement` with a `metric` and a `budget`; `Evidence`
(a measurement, a test, a review, a gate's verdict, a log) `measurement_of` it and is `evidence_of` what it
judged. A `Component` is `implemented_by` its `Repository` and the `CodeModule`s inside it; a `Commit`
`touches` a module. A `ChangeProposal` is `prompted_by` evidence, `proposes_change_to` nodes,
relationships or controls, is `decided_in` a `Decision` and `implemented_in` a commit.

Questions (AR1–AR9, awaiting confirmation): what a node connects to and over what (AR1), what
safeguards it (AR2), a flow's sequence (AR3), the budgets a node must meet (AR4), where it is
implemented and last changed (AR5), what measured a requirement (AR6), the open change proposals
(AR7), nodes no control safeguards (AR8), code modules nothing traces to (AR9).

**Filling it.** `oto arch import --calm model.json --at <date> [--environment environment.<id>]` reads a
CALM 1.x model into a document and a proposal cited to it, deriving the estate's edges beside the
reified ones, and `oto arch export --calm` writes it back, export of import equal to the input; `oto arch map` reads the
code map; the Epic B pipeline compiles both on every merge; `arch_context` serves a path's node,
requirements, decisions, budgets and controls.

This is a first draft: edit it. The sample is the roadmap's invoice-approval example; replace it with
your CALM model as soon as you have imported one.
