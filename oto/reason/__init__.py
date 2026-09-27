"""Rules over the graph: derive facts a person would otherwise infer, and flag what a policy forbids.
Derived facts are never asserted facts: they carry the rule and the premises, and vanish when a
premise is superseded. Standard library, deterministic, explainable."""
