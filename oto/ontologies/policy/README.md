# Policy — access policy as facts, compiled into Cedar

On `data` and `agent` (and so on `software-architecture`, `product` and `portfolio`): a `PolicyRule` permits or
forbids one `Permission` for the roles and teams it names, a `Permission` is an action (read, write,
export, delete, admin) on a kind of resource (a `Table`, a `Column`, a `DataStore`, a `Component`, an
`Interface`) narrowed by a selector over the resource's attributes, and a `Table` or a `Column`
carries its `classification` and whether it holds personal data (`pii`). The policy and the data
layer are one vocabulary: a selector that says `pii=false` reads the column the data pack describes.

**What the rules say, and what the engine does with them.** A rule is a draft until a named person
activates it (`oto decide policyrule.<id> status=active --by <who> --at <date>`); a retired one stays
as history. Only the active rules compile. `oto policy compile` (and the `policy` build stage, when
the vocabulary declares `PolicyRule`) writes `build/policy/`: `policies.cedar`, the rules in
[Cedar](https://www.cedarpolicy.com/), one policy per rule and principal, annotated with the rule's
id and its rationale as a comment; `policies.json`, the same rules as plain data for the engine's own
evaluator and the hooks, which stay plain Python and need no Cedar engine on the machine that runs
them; and `manifest.json`, with the bundle's version (the build sequence, the graph's hash, the
vocabulary's version), the hash of each file, a hash of the content and, when the project says
`"policy": {"sign_with": "<ENV VAR>"}`, an HMAC-SHA256 signature with the key that variable holds,
never the key itself. `oto policy verify` checks the files against the manifest and the signature
against the key. The deploy pipeline carries the bundle beside the store (`oto publish`).

**Why Cedar, and why a JSON form beside it.** ADR-0004 records the choice: Cedar is an open policy
language with a verified evaluator, a principal, an action and a resource per policy, `forbid`
outranking `permit`, which is the shape these rules already have; the JSON form exists so a hook on
a runner's machine can evaluate a snapshot with the standard library alone, and so a reader can diff
the bundle without parsing Cedar.

**Principals, agents and the snapshot (release 2).** A `Principal` is an identity that holds a
session, a person's account or a service account, and `holds_role` the roles and teams the identity
provider says. The agent pack's `Agent` is `granted_role` the roles it may exercise on its own
account. `oto policy snapshot --agent <id> --principal <id>` writes `.factory/policy.json`: the
intersection of what the two may do (a permission is in it when an active rule permits it to a role
of each, and no rule forbids it to either; the resources a rule singles out narrow it), the write
paths it reaches through the code map (a permitted `write` on a `Component` reaches its
`CodeModule`s' paths; a forbidden one marks them denied), hashed and signed like the bundle. The
engine plugin's PreToolUse guard (`hooks/policy_guard.py`), and the guard of any run that copies the
same reader (the factory's, in Cynergis/oto-factory), read it in plain Python, refuse what it does
not permit, and append every refusal to `.factory/events.jsonl`; `oto policy denials --events <file>`
turns those into audit records,
each once, so "who tried what, and was it allowed" is in the chain.

**The derivation.** A table holds personal data when one of its columns does (`pii` derived true), so
a selector `pii=false` never admits a table whose column is an email. A column of personal data in a
table classified public is flagged (warn), since a public classification lets every reader in.

Questions (PL1–PL7, awaiting confirmation): what a role may do, where the personal data is and how it
is classified, which rules are drafts or retired and so do not compile, one rule in full, who may
do what on a table, what a principal may do through its roles, and which roles an agent was granted.

The sample is on the ledger the data sample describes: a customers table whose email column is
personal data, compliance reading everything but that, the reports team exporting the daily balances
and refused every write on the postings, and an owner-administers-the-store rule still a draft.

**The generated system's IAM (release 3, roadmap E7, ADR-0005; on its own since release 4, ADR-0006).**
The system OTO helps build has access control of its own, on the platform it runs on, and the same
rules give it. A `Component` (or a `System`) `runs_as` a `Principal`, the service account it runs
under; a `Permission` names the platform role it maps to (`cloud_role`, `roles/bigquery.dataViewer`),
a fact the organisation states rather than a catalogue in the engine; a `Table`, a `DataStore`, a
`Component` and an `Interface` say where they are on the platform (`resource_uri`). Read through the
roles each principal holds, the active rules give the bindings: a member (`serviceAccount:<identity>`,
`user:<identity>`), a role, a resource. A forbid withholds the binding a permit would have made for
the same member, resource and action; what cannot bind (no platform role, no place on the platform,
no identity) is named and left out. `oto policy iam` and the `iam` build stage write `build/iam/`:
`bindings.json`, `gcp.json` (one policy per resource, in the shape `set-iam-policy` takes),
`bindings.proposal.json`, `iam-bindings.md` and a manifest hashed and signed like the policy bundle,
verified by `oto policy verify build/iam` and carried by `oto publish`. The bindings are written
back as nodes of this pack's own: one `IamBinding` per resource, carrying the `provider`, the
`resource_uri`, the `bindings` and what was `withheld` as the JSON the platform takes, and
`generated_by`; it `binds` the resource, `grants` the principals and `derives_from` the rules it
came from. `oto policy iam --apply --by <who>` takes the binding nodes through the gates. The pack
depends on no framework: when the calm pack is composed too, its adapter exports a binding node as a
control on the bound node and on the components that run as the granted principals, so
`oto arch export --framework calm` carries the IAM the policy implies. OTO never enforces these
bindings: they ship with the system and the platform enforces them; the write hook, the snapshot
and the served read hook keep enforcing the policy on OTO's own actions. PL8 asks what runs as a
principal and which binding nodes grant it, from which rules; PL9 what is bound on a resource. The
sample's invoice intake service runs as its own account, which holds the invoice writer role
permitted to write the invoices table; the binding node the generator derives on that table is in
the sample as it writes it.

**Where the code is.** The compiler, the snapshot, the IAM derivation, the two build stages, the
command, the write hook before `curate apply`, `decide` and `promote`, and the read hook before the
served native read live in `oto/packs/policy/`, and reach the engine only through this pack's
manifest (`provides`, ADR-0006). The two plain-Python guards stay in the plugins' `hooks/`.

This is a first draft of the vocabulary; edit it. Release 4 awaits confirmation of its terms.
