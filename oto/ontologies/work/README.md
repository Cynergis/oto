# Work — what is planned, by whom, blocked by what, deployed where

On `software-architecture` (and so on `product` and `portfolio`): a work item delivers a requirement,
a feature or a component; it is scheduled in a milestone or a release, assigned to a team or a role.

**Three states, never written on the item.** An item is `open`, `blocked` or `deployed`. Nobody sets
`state`: a `Transition` is appended (to which state, when, by whom; for a deployment, to which
environment), the previous transition is superseded, and the rule
`state-follows-the-current-transition` derives the state from the current one. An item with no
transition is open (the attribute's default). The superseded chain is the history: `oto query
entity <transition> --as-of <date>` says what the state was. `deployed` is set by events, a merged
pull request or a promotion, never by hand; `oto work set` refuses it.

**A milestone is reached when a person says so.** `Milestone.state` (planned, reached, missed) is a
`decision` attribute (release 6): `oto decide milestone.<id> state=reached --by <who> --at <date>` records
the named person's assertion and moves it under the gates; it is never derived from a count of merges,
because a phase is done when its owner says so. The OTO roadmap's own phases are recorded that way.

**A block carries its context.** A `Block` is a transition to blocked that must carry a `reason`
and a `waiting_on` (a person, a team, an item, a decision, a question, a risk): the class requires
both, so a block without them is refused at the gate. `oto work set <item> --state blocked
--reason ... --waiting-on ...` writes one; `--state open` lifts it.

The delivery lead's questions (WK1–WK10, confirmed by Chiheb Dkhil on 2026-10-07): what is planned
for a milestone, what a team is working on and what of it is blocked, what blocks an item and who
owns the blocker, which requirements in scope nobody delivers, **which requirements slip if a
component is late** (the question that crosses every level), what is overdue, which decisions work
waits on, and whether a deployed item's requirement is satisfied in the design (trace closure).
Release 2 adds the board's questions (WK11–WK13, awaiting confirmation): what is blocked, since
when, why and on whom; what is deployed and where; where an item is now and who set it.

**Upgrading from release 1.** `planned` and `in-progress` read as `open`, `done` as `deployed`
(the attribute's `was`); a `dropped` item has no state and is retired instead. Items that still
assert a state keep it, and that asserted value wins over any transition: remove it when you start
recording transitions. There are no sprints; `estimate` stays optional and nothing runs on it.

This is a first draft of a delivery plan's vocabulary: edit it. The one thing to keep is the rule
that state comes from transitions, because the events of Epic B and a factory's verdict set it the same way
a person does.
