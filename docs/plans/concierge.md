# Plan: the concierge skill

Status: proposed and delivered 2026-09-21 (all three phases).

The ask, in the user's words: "a skill that acts as a guide or concierge to building the graph,
providing guidelines, options, explaining what is being done, answering user questions."

## What it is, and is not

The eight skills are playbooks: each does one task well. The concierge does no task. It is a
router and an explainer: it says where the project is, what the choices are at this point, why
Oto does what it does, and which playbook to load next. It never restates a rule the engine
enforces; it runs the command and quotes the output, so it cannot drift from the code.

## The skill, section by section

`skills/concierge/SKILL.md`, loaded when a user asks "where am I", "what should I do next",
"what are my options", "why did it do that", "explain", or opens a project and says nothing
specific. Six sections:

1. **Orient.** Run `oto status --project <root>` and quote it. The command already names the
   next step in lifecycle order; the skill adds one sentence of context per station (inbox,
   processing, proposal, candidate, pull request, live) and stops.
2. **The map.** The lifecycle on one screen: documents → Markdown → vocabulary → proposals →
   candidate → four gates → build → served. Which files each step reads and writes, which command
   runs it, what the gates refuse and why. Written once, short, with the commands that print the
   detail (`oto curate check`, `oto ontology check`, `oto vet`, `oto bench run`).
3. **The forks.** A table of the decisions a user meets, each with its options, the trade-off in
   one line, and the command for each choice: which template; ingest or author by hand; local
   apply or pull request; SQLite or Neo4j; live, preview or watch; a static site or a server;
   the explorer, the reader or a custom view; local install or repository mode.
4. **Why.** Where Oto records its reasons, and the command that prints each: the vocabulary's
   rationale (`ontology.rationale.json`, `oto ontology check`), each rule's `why` (`rules.json`,
   `oto rules explain`), a derived fact's premises (`kg_explain`), a gate's refusal
   (`oto curate check`), the ledger's notes (`kg_overview`, `oto query overview`), the decisions
   convention (`DecisionRecord` facts), and the architecture notes for the design itself.
5. **Hand-off.** One row per playbook: the moment to load it and the words a user tends to say.
   The concierge ends its turn by naming the skill, not by doing its work.
6. **Answering questions about the graph.** Route to query-knowledge. Route questions about a
   pending fact to `oto query pending`, and never present a pending fact as believed.

Constraints written into the skill: quote commands, do not paraphrase them; offer at most three
options at a fork, recommend one; never weaken a gate to make a step feel faster; never touch a
secret; say plainly when the project is a published query store and not a knowledge project.

## Domain specialisation, through the template

The template contract already lets a template carry `interview.md` and a `skills/` directory. A
template adds `guide.md`: what this domain's graph is for, the questions it answers well, the
classes a newcomer should read first, the common mistakes. The concierge reads the project's
template record, loads that guide when it exists, and quotes it. The software-architecture
template gets the first guide; the registry's check validates the file like the others.

## Engine work, kept small

- `oto status --json`, so the skill and a future chat pane read the same fields the text shows.
- `oto rules explain <rule-id>`: the rule's `why`, its premises and what it derived last build,
  for section 4. `kg_explain` already covers a single derived fact.
- `guide` added to what a template may carry; `oto templates show` lists it.

Nothing else. The concierge must work on the engine as it is.

## Tests

- Every `oto <command>` the skill names parses against the real CLI (a test reads SKILL.md).
- Every next-step string `oto status` can print appears in the skill's fork or orient table, so
  a new station in the code fails the test until the skill knows it.
- The guide file passes the template self-check and is carried by `oto templates publish`.
- The skill passes the plugin's skill checks (frontmatter, description length, no secrets).

## Delivery

| Phase | Delivers | Size |
|---|---|---|
| 1. The skill | `skills/concierge/SKILL.md`, the plugin manifest and skills index updated, the two drift tests | 1 day |
| 2. The domain guide | `guide` in the template contract, the software-architecture guide, registry v4 | half a day |
| 3. Explain commands | `oto status --json`, `oto rules explain` | half a day |

Each phase ends green on the suite and the gates, committed and pushed, usable on its own.
