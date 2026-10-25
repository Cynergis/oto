# -*- coding: utf-8 -*-
"""Tools: the graph's hands, described and never invoked. (Called actions until 2026-10; the old
names are still read.)

A tool is a description in MCP shape (name, description, input schema, annotations)
bound to the graph: the class it acts on, how its inputs are filled from the subject entity, the
preconditions under which it is ready, the declared way to invoke it, and how its result becomes
knowledge. OTO lists tools, checks them, computes readiness and records results as evidence.
The caller, an agent, a person or a workflow, invokes them.
"""
