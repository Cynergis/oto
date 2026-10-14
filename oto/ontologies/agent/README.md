# Agent: a part of a product that people give work to

Sits on `software-architecture` and so on `product`. The third kind of part a product can have,
beside an application (`ddd`) and a data pipeline (`medallion`): an agent people hand work to
in their own words, instead of using a screen. It says **what** the agent does, never **how** a
given platform runs it; the plugin, tool server or app is how it is packaged (`Agent.packaging`).

- **The jobs** a person can hand it (`Job`): when each applies, what it produces, how far the agent
  may act alone, and the requirement it meets (`satisfies`).
- **The tools** it has (`Tool`): whether each reads, changes or sends something, whether that can be
  undone, and what it reaches in the architecture (`reaches`).
- **What it draws on** before it acts (`KnowledgeSource`), where that is kept, and how current it must be.
- **Its guardrails** (`Guardrail`): what it must never do, what it may do only after a named person
  confirms, what bounds it keeps; each may uphold one of the organisation's policies.
- **How it talks** (`ConversationStyle`), and **where it hands work over** (`hands_off_to`).
- **The test conversations** that prove each job (`Evaluation`).

What it does not carry, because the product and the estate do: the people (`Persona`, `Role`), the
obligations (`Requirement`, `Policy`), the reasons (`Decision`), the open questions, the team that
owns the agent and the component that carries it (`deployed_as`).

The rules refuse a design that contradicts itself: a job acting alone with a tool that needs a
person's confirmation, a job using a tool the agent must never use, a job acting alone with a tool
that changes or sends something while nothing protects it, a job marked ready that meets no
requirement, has no test conversation, or fails one. They warn when a confirmation names nobody,
when the agent would show technical details without being asked, and when a ready job still has an
open question.

The sample is the merchant assistant on the payments platform the other samples describe: it
explains a day's settlement on its own and refunds a payment only after the clerk confirms.
