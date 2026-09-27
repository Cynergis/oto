# Plan: the template contract and the template registry

A template today is what a project starts from: a vocabulary, its rationale, rules, a sample graph
and notes, shipped inside the engine or exported from a project. This plan makes a template a
unit that can be written by a domain team, versioned, composed from parts, distributed from a
repository the engine does not ship, and recorded by every project that starts from it. The same
unit later carries how a graph is read (the UI's view configuration) and how it is built (the
guide's questions), so the contract reserves those slots now and fills them in later plans.

Status: all four phases delivered on 2026-09-19. Superseded in words on 2026-09-24: what this plan calls a template is an ontology, `oto templates` is `oto ontology` and `oto registry`, the manifest is `manifest.json` with a `release`; see docs/plans/ontology.md. The design stands. The Cynergis registry is `Cynergis/oto-registry`.

One word is kept throughout: **template**. The command stays `oto templates`; the manifest is
`template.json`; a registry lists templates.

## What exists, and what changes

| Today | After this plan |
|---|---|
| Four files plus `rules.json`, no manifest; name is the directory name | The same files, plus `template.json` naming, versioning and composing the template |
| Shipped in `oto/templates/`, user copies in `~/.oto/templates/` (`OTO_TEMPLATES`), any directory by path | The same three, plus templates fetched from git into `~/.oto/templates/` by name, from one or more registries |
| `oto init --template a,b` merges by name; the merge report is printed once and lost | `extends` in the manifest composes a template from parts; a project records what it started from |
| A project records nothing about its template | `project.config.json` records template name, version, source and commit; `oto templates diff` shows what the upstream template changed since |
| `oto templates export` writes a directory | `oto templates publish` pushes it to a template repository, the way `oto publish` pushes a store |
| Self-check on load | Self-check plus the publishability scan, so a template with client data in its sample never leaves a machine |

Nothing a project holds changes shape. `ontology.config.json`, the lock, the rules and the graph
are untouched; a template is only ever an input to `oto init` and to `oto templates diff`.

## Part 1. The template contract

### Layout

```
<name>/
  template.json             manifest: identity, version, what it extends, what it carries
  ontology.config.json      the vocabulary (as today)
  ontology.rationale.json   why each class exists, who confirmed it (as today)
  rules.json                derive and policy rules (as today, optional)
  sample.graph.json         a tiny valid graph so a fresh project builds (as today)
  README.md                 what to edit, what to have validated (as today)
  lexicon.json              optional: seed jargon and synonyms for the domain
  interview.md              optional: the questions the interview asks in this domain, in order
  guide.md                  optional: what this domain's graph is for and how to read it (added 2026-09-21)
  gold/patterns.jsonl       optional: question patterns per class, for the evaluate skill
  views/                    reserved for the reader UI's view configuration (a later plan)
  .claude-plugin/           optional: makes the template installable as a Claude Code plugin
```

A directory without `template.json` is still a template: the manifest defaults are derived from
the directory (name from the directory, version 1, extends nothing). Every user template exported
so far keeps working unchanged.

### The manifest

```json
{
  "name": "insurance-claims",
  "version": 3,
  "summary": "Auto and property claims: parties, policies, losses, adjusters, reserves, decisions.",
  "extends": ["oto-core", "insurance-party"],
  "engine": ">=0.2",
  "carries": ["vocabulary", "rationale", "rules", "sample", "lexicon", "interview", "gold"],
  "maintainer": "Claims knowledge team <claims-kb@example.com>",
  "changelog": [
    {"version": 3, "at": "2026-10-02", "note": "Reserve became a class; reserved_by relation added."},
    {"version": 2, "at": "2026-09-20", "note": "Adjuster attributes typed."}
  ]
}
```

| Field | Meaning |
|---|---|
| `name` | Lowercase, hyphenated, unique within a registry. Also the directory name. |
| `version` | An integer that rises on every published change. The vocabulary's own `ontology_version` inside `ontology.config.json` keeps its meaning (the vocabulary's edition) and is independent. |
| `summary` | One line, shown by `oto templates`. Replaces the `_summary` key currently read from the vocabulary; that key stays accepted as a fallback. |
| `extends` | Templates this one composes on top of, in order. Resolved by name through the same lookup as `--template`. Empty for a leaf. |
| `engine` | The minimum engine version whose contract it was written for. `oto init` refuses a newer contract with a clear message rather than installing half a template. |
| `carries` | What the directory holds, so a listing can say "ships rules and a lexicon" without opening files. Checked against the directory by the self-check. |
| `changelog` | What each version changed. `oto templates diff` shows the entries a project has not seen. |

### Composition: `extends`

`oto init --template a,b` already merges two templates and prints a report. `extends` makes that
composition part of the template itself, so an insurance-claims template can say it is built on
a core temporal vocabulary and a party template, and a project that starts from it gets all three.

Rules, in order of precedence when two parts declare the same name:

1. The extending template wins over anything it extends, for a class description, a relation
   signature or an attribute type. A silent widening is not allowed: if a part declares
   `filed_by: [Claim, Party]` and the extender says `[Claim, Party|Organisation]`, the merge
   accepts it and the report says so; if the extender narrows, the merge refuses with the names.
2. Rationale entries merge per class; the extender's `validated_by` does not carry to a class it
   did not declare (confirmation is per vocabulary, as today).
3. Rules merge by `id`; a duplicate id with a different body is refused.
4. Samples merge by node id; the extender's sample must reference only classes the composition
   declares, which the self-check enforces.
5. The lexicon, interview and gold patterns concatenate, extender last.

`oto templates show <name>` prints the resolved composition and its report, so a person sees what
`oto init` will install before running it. The temporal vocabulary (`temporal` in the config) is
taken from the first part that declares it and never merged, because supersession depends on it
being one thing.

### Versioning and what a project records

`oto init --template <name>` writes into `project.config.json`:

```json
"template": {
  "name": "insurance-claims",
  "version": 3,
  "source": "https://github.com/Cynergis/oto-registry",
  "commit": "8f1c2d9",
  "installed_at": "2026-10-04",
  "extends": ["oto-core", "insurance-party"]
}
```

`source` and `commit` are recorded when the template came from a registry; a built-in or path
template records `"source": "built-in"` or the path. This is what makes two later commands
possible:

- `oto templates diff --project <root>`: fetch the template's current version, compose it, and
  diff it against the project's **lock** (the last accepted vocabulary and rules), not against the
  working config. It reports what the upstream template changed since the recorded version,
  classified with the same severity as `oto ontology check` (breaking, widening, additive), the
  changelog entries the project has not seen, and which changes `oto ontology widen` could take.
  It never edits the project.
- `oto status` gains one line when a newer template version exists: "template insurance-claims
  3 -> 5 available; oto templates diff". Advisory, never blocking, following the rule that a
  passing build must not fail because someone else published something.

### The self-check, extended

`self_check` today validates the vocabulary, the relation signatures, typed attributes, rules,
rationale coverage and the sample. It gains:

- the manifest: fields present and well-formed, `carries` matches the directory, `extends`
  resolves and composes without refusal, `engine` is satisfiable;
- the lexicon: the existing lexicon shape check, plus every target must exist in the sample or be
  marked `not_ingested`;
- the interview: parseable as ordered questions (one `##` per question, prose under it);
- gold patterns: each names a class the composition declares;
- publishability: `tools/check_publishable.py` runs over the template directory with the machine's
  deny terms, so a sample or a README that names a client cannot be published. `oto templates
  publish` refuses on any problem; `oto init` refuses on the vocabulary problems and warns on the
  rest.

## Part 2. The registry

### What a registry is

A git repository with one index file and, usually, the templates themselves:

```
oto-registry/
  registry.json
  oto-core/           template.json, ...
  insurance-party/
  insurance-claims/
  banking-lending/
  telco-network/
```

```json
{
  "name": "cynergis",
  "summary": "Cynergis domain templates.",
  "templates": [
    {"name": "insurance-claims", "version": 3, "summary": "Auto and property claims ...",
     "path": "insurance-claims", "extends": ["oto-core", "insurance-party"]},
    {"name": "telco-network", "version": 1, "summary": "...",
     "source": "https://github.com/Cynergis/telco-kb-template", "ref": "v1"}
  ]
}
```

An entry names a directory in the same repository (`path`) or another repository (`source`, with
an optional `ref` and `path`). The index is regenerated by `oto templates publish`, never edited
by hand, and a check in the registry's own CI refuses an index that does not match the
directories beside it.

The same repository can be a Claude Code marketplace by carrying `.claude-plugin/marketplace.json`
listing the templates that also ship `.claude-plugin/plugin.json`. Both files are generated from
the same source of truth, the template manifests, so a registry entry and a marketplace entry
cannot disagree. That is how "template, UI and guide packaged together as a plugin" will work
without a second distribution channel.

### Resolution

When a name is given to `--template`, `extends`, or `oto templates show`, it resolves in this
order, and the first match wins: an explicit path; the user directory `~/.oto/templates/<name>`
(exports and fetched copies); the registries, in the order they were added; the built-ins. A
fetched template lives at `~/.oto/templates/<name>` beside exports, with its manifest carrying
`source` and `commit`, so the user directory is one place to look and `OTO_TEMPLATES` keeps
overriding it.

A name can carry a version: `insurance-claims@3`. Without one, the registry's current version is
used and recorded; `oto init` prints the version it installed.

### Commands

```
oto templates                              list: built-in, user, and every registry entry with version and summary
oto templates show <name>                  the resolved composition, its report, the changelog
oto templates add <name>[@version]         fetch from the registries into the user directory
oto templates add <git url> [--path p]     fetch one template repository, no registry needed
oto templates update [<name>]              fetch newer versions of what was added
oto templates registry add <git url>       register a registry (first one added is the default)
oto templates registry list | remove <name>
oto templates diff --project <root>        upstream changes since the project's recorded version
oto templates export --project <root> ...  as today, plus a generated template.json
oto templates publish --project <root> --to <registry url> [--name n] [--summary s] [--from-graph N]
                                           export, self-check, publishability scan, bump version,
                                           commit into the registry, regenerate its index, push
```

Registries and fetched templates are recorded in `~/.oto/registries.json` and the fetched
manifests; nothing is written to a project except the `template` record at `init`.

### Authentication and privacy

Git is the transport, as for the engine and the query repository: `gh auth setup-git` on a
machine, the secret `OTO_TEMPLATE_TOKEN` in a workflow (used the same way `OTO_ENGINE_TOKEN` is,
through a `url.insteadOf` rewrite for the length of the job), and an https URL is the only place a
token is put. A private organisation hosts its own registry; the engine ships with none
configured, and the Cynergis registry is added by URL like any other.

The publishability scan runs before every publish with the machine's deny terms, and the
registry's CI runs it again with the registry's own secret, so a template that names a client
cannot enter the registry from any machine.

### Offline and pinning

A fetched template is a plain directory; once added it works with no network. `oto init` never
fetches on its own: an unknown name lists what is available and says `oto templates add`. A
project that must reproduce its start state pins `insurance-claims@3` and the recorded commit
lets `oto templates diff` fetch exactly that version for comparison.

## Part 3. Engine changes

| Area | Change |
|---|---|
| `oto/model/templates.py` | Stays, and gains three siblings under `oto/model/`: `template_manifest.py` (read, defaults, validate), `template_compose.py` (`extends` resolution and merge with the report; the existing `merge` becomes its implementation), `template_registry.py` (index read, fetch through git, the user registries file, publish with index regeneration). The public functions `available`, `load`, `self_check`, `merge`, `export` keep their signatures. |
| `oto/scaffold.py` | `init` records the `template` block; refuses an `engine` it cannot satisfy; prints the version installed. |
| `oto/cli/init.py` | The `templates` subcommands above; `--template name@version`. |
| `oto/cli/status.py` | The advisory line when a newer version exists, computed from the local registry copy, never fetching. |
| `oto/validate/preflight.py` | No change: template drift is advisory and belongs in status and diff. |
| `oto/templates/*` | The four shipped templates gain `template.json`; `oto-core` is split out of the temporal vocabulary they share so `extends` has a real base to point at. |
| `tools/check_templates.py` | Runs the extended self-check over every shipped template and over a fixture registry. |
| Docs | `docs/ARCHITECTURE.md` (Declare row, a Templates section), the README install block, `skills/ontology-interview` (reads `interview.md` when the template ships one), `skills/build-knowledge-base` (the `add` step). |

## Part 4. Tests

- **Contract.** A fixture directory per case under `tests/fixtures/templates/`: minimal (no
  manifest), full, extends-chain, narrowing conflict, duplicate rule id, sample referencing an
  inherited class, client name in the sample. `self_check` and `compose` are asserted case by
  case, with the exact refusal text for the conflicts.
- **Init records.** After `oto init --template`, `project.config.json` carries the block with
  the right version and source for built-in, path and fetched templates.
- **Registry.** Local bare git repositories, as `tests/test_publish.py` does: publish a template,
  regenerate the index, add the registry, list, add by name and by URL, update, pin a version,
  the second publish bumps the version and the index. No network in the suite.
- **Diff.** A project started from version 2; the registry moves to 3 with a widening and to 4
  with a breaking rename; `oto templates diff` classifies both and names the changelog entries;
  the project's config is byte-identical before and after.
- **Token handling.** The same three assertions as for the store: https gets the token, ssh and
  paths do not, output never contains it.
- **Gates.** `tools/check_templates.py` and the publishability scan run over the shipped templates
  and the fixture registry in `tools/run_gates.sh` and in CI.
- **Equivalence with today.** Every existing template test passes unchanged, and a user template
  directory without a manifest initialises exactly as before.

## Part 5. Delivery

| Phase | Delivers | Size |
|---|---|---|
| 1. Contract | `template.json`, defaults for manifest-less directories, extended self-check, `extends` composition with report, `oto templates show`, the `template` record at init, `oto-core` split out, shipped templates carry manifests | 3 days |
| 2. Registry | index format, `registry add/list/remove`, `add` by name and URL, `update`, pinning, user registries file, token handling, fixture-registry tests | 3 days |
| 3. Publish and diff | `oto templates publish` with checks and index regeneration, `oto templates diff` against the lock, the status advisory, changelog display | 2 days |
| 4. Marketplace convergence | `.claude-plugin` generation from manifests, one registry that is also a marketplace, the Cynergis registry repository created and seeded with the four shipped templates | 1 day |

Each phase ends green on the full suite and the gates, committed and pushed, and usable on its
own: after phase 1 a domain team can already write a template with a manifest and compose it;
after phase 2 they can fetch one; after phase 3 they can publish one and a project can see drift.

## Decisions to take before phase 1

1. **The registry repository.** Proposed: `Cynergis/oto-registry`, private, seeded with the four
   shipped templates and `oto-core`. The engine keeps shipping its four so `oto init` works with
   no registry configured.
2. **Version discipline.** Proposed: `version` rises on every publish, no semantic versioning;
   breaking or not is computed by `diff`, not declared by the author, because authors are
   optimistic about compatibility and the diff is not.
3. **The `views/` slot.** Reserved now, empty, so the UI plan can fill it without a manifest
   change. Its contents are that plan's decision.
4. **Interview format.** Proposed: Markdown, one `##` per question with the reasoning under it,
   because the guide is a skill and skills read Markdown; a JSON form can be derived later if a
   UI needs it.
