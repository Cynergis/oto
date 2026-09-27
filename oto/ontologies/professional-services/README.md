# Professional services engagement — starter vocabulary

Derived from a real transformation engagement, generalized. A first draft to edit.

## Think hard before you use `Person`

An engagement knowledge base fills up with people, and a roster is the easiest thing in the world to
build and the hardest to justify. On the engagement this ontology came from, a roster of several
hundred named employees with reporting lines was added, then removed, and the repository history had
to be rewritten to purge it.

Ask what question needs a name to answer. Usually the answer is "who owns this", and a `Role` answers
it better: roles are stable, people move, and attaching work to a role keeps history correct. Keep
`Person` only for the handful of people whose individual decisions you must trace, and record no
personal detail beyond what that requires.

## The shape that earns its place

- **`Session` is separate from `Document`.** A workshop is an event; its transcript is a file. One
  session can be recorded in several documents, and a document can cover several sessions. Merging
  them makes "what did we decide on the 14th" unanswerable.
- **`Decision`, `ActionItem` and `Question` are nodes.** Each has a date, an owner, a state and a
  reason. As attributes on something else, none of that survives.
- **`GovernanceForum` is separate from `Session`.** The forum recurs; the session happens once.
  `instance_of` links them, which is what lets you ask "every decision this board has taken".
- **`Concept` is deliberately broad.** In a first draft it catches operating model elements, ways of
  working and capabilities. Split it as soon as you can say what the sub-kinds are.

## Where this vocabulary went wrong before

On the engagement it came from, the declared domains and ranges drifted from real use: about 15% of
edges ended up with endpoints the declaration did not allow. `part_of` was declared organization to
organization and used between concepts, sessions and deliverables. Nothing checked it for months.

`oto ontology check` now reports that. Run it early and often, and either widen the declaration or fix
the edges while it is still small.
