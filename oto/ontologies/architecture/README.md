# Architecture — the graph agents consult before they change code

On `software-architecture` (and so on `product` and `portfolio`): the architecture as implementation
reads it, framework-neutral. The model an organisation writes its architecture in (CALM through
the calm pack, C4 when someone writes that adapter) stays the contract its gates check; this graph
is the derived copy an agent queries before it edits, so it avoids a violation instead of a gate
rejecting one (roadmap Epic H). Which framework wrote a node is a fact on the node, never a term of
this pack.

**A framework's node is an estate node.** No `Node` class: a framework's node becomes a `System`, a
`Component`, a `DataStore`, an `Environment` or a `Role`, by the mapping its adapter declares. Each
carries `external_id` (the id the framework gave it, so it round-trips), `external_type` (the type
as the framework names it, kept as given) and `external_payload` (what the framework carries about
the node that no question asks for, as the JSON it gave, never read by the engine). An `Interface`
carries `external_id`, `definition_url` and `config`. The model's `Document` carries `framework`,
the adapter that read it, and the model's own header as `external_payload`, which is how
`oto arch export --framework <name>` finds the model to write back.

**A relationship is a node.** `Relationship` has a `kind` (interacts, connects, deployed-in,
composed-of, options), a `protocol`, `connects_from` its source (an actor, a node,
a container) and `connects_to` each destination, `via` the interface a connection goes through, and
`offers_option` the decisions an options relationship chooses between. It is a node because a `Flow` walks
relationships in order (`FlowStep`, `sequence`, `direction`, `over`) and a `Control` `safeguards` them,
which an edge could carry neither of. A control has its own relation, apart from a decision's `governs`,
so that what no control safeguards can be asked (AR8). The plain estate edges (`consumes`, `part_of`, `runs_in`,
`depends_on`) are derived beside it by the adapter, so SA1 to SA17 keep answering.

**A contract is a version of an interface.** `Contract` carries a `version`, a `kind` (event, api,
schema, file) and a `schema_url`; it is `contract_of` one `Interface`, and a new version `supersedes`
the old. Its `status` is a decision: a draft until a named person freezes it (`oto decide
contract.<id> status=frozen --by <name> --at <date>`); frozen, nobody changes it without a new
version, so a consumer and its provider build in parallel against it, which is what a factory's build
plan reads (AR10, AR11).

**The implementation trace.** An `NFR` is a `Requirement` with a `metric` and a `budget`; `Evidence`
(a measurement, a test, a review, a gate's verdict, a log) `measurement_of` it and is `evidence_of` what it
judged. A `Component` is `implemented_by` its `Repository` and the `CodeModule`s inside it; a `Commit`
`touches` a module. A `ChangeProposal` is `prompted_by` evidence, `proposes_change_to` nodes,
relationships or controls, is `decided_in` a `Decision` and `implemented_in` a commit.

Questions (AR1–AR9, awaiting confirmation): what a node connects to and over what (AR1), what
safeguards it (AR2), a flow's sequence (AR3), the budgets a node must meet (AR4), where it is
implemented and last changed (AR5), what measured a requirement (AR6), the open change proposals
(AR7), nodes no control safeguards (AR8), code modules nothing traces to (AR9).

**Filling it.** `oto arch import --framework <name> --file model.json --at <date> [--environment environment.<id>]`
reads a framework's model through the adapter its pack provides into a document and a proposal cited
to it, deriving the estate's edges beside the reified ones, and `oto arch export --framework <name>`
writes it back, export of import equal to the input; `oto arch migrate --framework <name> --by <who>`
rewrites a graph written with a framework's former attribute names (release 5 renamed the former
CALM-named attributes to `external_id`, `external_type`, `external_payload` and `framework`); `oto arch map --repo <path> --repository repo.<id> --at <date>` reads a code repository by
`oto.codemap.json` (or the default, every directory under `src/`) into modules, their commits and
the components they implement; `oto arch compile` runs both as `project.config.json` declares, and
the `oto architecture` workflow does so on every merge; `arch_context` serves a path's or a node's
requirements with their budgets and measurements, decisions, controls, connections, modules and open
proposals, and `oto arch impact` reads what a decision affects, the orphans and the untraced code.

This is a first draft: edit it. The sample is the roadmap's invoice-approval example; replace it with
your CALM model as soon as you have imported one.
