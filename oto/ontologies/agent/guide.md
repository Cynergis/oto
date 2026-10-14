# Reading an agent graph

## What this graph is for

It answers what people ask before they trust an agent with their work: what it is for, what it can
touch, what it will never do, who has to say yes before it acts, and how we know it works. Every
answer cites the document that states it.

## The questions it answers well

- **What can I ask it?** The jobs, each with when it applies and what it produces (AG2).
- **What can it touch?** Its tools and everything they reach; the agent's own reach is derived
  from its tools (AG4, AG11).
- **What is guarded, and by whom?** Every tool that changes or sends something, with its guardrail
  and who confirms (AG5, AG6).
- **Does it work?** The test conversations of each job and how each last ran (AG9).

## Where to start reading

Start from the agent and its jobs, then each job's tools. Read the guardrails next to the tools they
protect: a tool that changes something with no guardrail is the first thing to settle.

## Common mistakes

- Writing how a platform runs the agent (a prompt, a model, a framework) as part of the design. That
  is the platform binding; record a choice of platform as a decision of the architecture.
- A job that "does everything". Split it until each job has one result a person can check.
- Marking a job ready before a test conversation proves it. The rules refuse it.
