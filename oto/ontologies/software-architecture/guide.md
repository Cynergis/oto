# Reading a software-architecture graph

## What this graph is for

It answers the questions people ask about a software estate under pressure, from documents that
were written to describe it at rest: what breaks if this changes, who owns it, why it is the way
it is, what is fragile, and what the business loses when a part fails. Every answer cites the
document that states it and the date it was true.

## The questions it answers well

- **Change impact.** "What depends on the payments interface?" follows `consumes` and `exposes`,
  and the rule `consumer-depends-on-provider` derives the dependency between components so it can
  be asked directly: `oto query neighbors "<component>" depends_on`.
- **Ownership.** "Who do I call about the ledger?" follows `owned_by` to a `Team`. If the answer
  is a person, the graph is recording the wrong thing.
- **Reasons.** "Why one ledger?" follows `about` from the product's `Decision` and quotes its rationale.
  A decision without a recorded document is flagged by `decision-is-documented`.
- **Fragility.** "What threatens production?" follows `threatens` and `mitigated_by` from `Risk`.
  The rule `risk-reaches-system` lifts a risk to a component up to its system.
- **Business exposure.** "What can customers not do if payments is down?" follows `enables` to
  `Capability`, the one class written in the business's words.

## Where to start reading

Open the explorer (`oto serve --http 8765`) and read the `System` column first: each system is a
unit of ownership. Then one system's components and the interfaces between them. Read
`Decision` entries last: they explain what the rest shows. A dashed edge was derived by a
rule; `oto rules explain <rule>` says why the rule exists and what it derived.

## What can be done

The ontology ships three actions, listed by `oto actions list` and never invoked by OTO: a daily
check that a repository exists (read-only; it realises an intended `Repository` and re-attests a
current one), the creation of a repository an intended fact describes (it changes the world, so a
person confirms it by name), and a weekly read of what an `Interface` answers at its URL. Record a
run with `oto actions record`, and the response enters the graph through the gates with the run as
its evidence. The act skill is the protocol.

## Common mistakes

- Recording a person as an owner. Use the team; people move.
- Recording every server. This is not a configuration database; add `Environment` only where a
  question needs it, and point at the catalog that holds the rest.
- Two components writing one store without a decision that says so. `writes_to` is separate from
  `reads_from` so this can be asked: `oto query neighbors "<store>" writes_to`.
- Leaving `validated_by` empty on a rule for months. A rule nobody confirmed derives facts nobody
  asked for.
