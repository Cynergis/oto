# Reading a platform binding

## What this graph is for

It answers what an implementing agent, an on-call engineer and a tester need before they touch the
running product: where each part runs, on what, built with what, with which secrets from where, how
it gets there, and who decided each of those choices.

## The questions it answers well

- **Can this component be built, deployed, tested?** The briefs say READY or BLOCKED, naming what is
  missing: `oto query brief deploy-component COMPONENT=<id>`.
- **Where is it?** The platform, account, region, console and logs of each environment (PL1, PL2).
- **Who decided this, and what else was considered?** Each choice, its authority, its limits and the
  decision that settled it (PL9, PL10).

## Where to start reading

Start from the choices: the ones still unsettled are what stops the build. Then each environment,
then each component's service, stack, secrets and pipeline.

## Common mistakes

- Recording a secret's value. Record its name and where it is kept; the form has no field for a value.
- Leaving a choice to the builder without saying within what. Give the allowed options, or the
  constraints and decisions that bound it.
- Marking the builder's pick accepted before a person has confirmed it.
