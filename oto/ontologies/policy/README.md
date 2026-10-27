# Policy — access policy as facts, compiled into Cedar

On `data` (and so on `software-architecture`, `product` and `portfolio`): a `PolicyRule` permits or
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

**The derivation.** A table holds personal data when one of its columns does (`pii` derived true), so
a selector `pii=false` never admits a table whose column is an email. A column of personal data in a
table classified public is flagged (warn), since a public classification lets every reader in.

Questions (PL1–PL5, awaiting confirmation): what a role may do, where the personal data is and how it
is classified, which rules are drafts or retired and so do not compile, one rule in full, and who may
do what on a table.

The sample is on the ledger the data sample describes: a customers table whose email column is
personal data, compliance reading everything but that, the reports team exporting the daily balances
and refused every write on the postings, and an owner-administers-the-store rule still a draft.

This is a first draft of the vocabulary; edit it. Release 1 awaits confirmation of its terms.
