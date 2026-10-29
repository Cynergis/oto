# Plain: a framework the tests carry

The engine ships no architecture framework (ADR-0008): a framework is a pack of the registry, a
manifest whose `provides.adapters` names a module in the pack's `code/`, chosen by
`oto arch import --framework <name>`. The engine's own tests still need a framework's model to
exercise what the core does with one: the document in the corpus, the proposal through the gates,
`oto arch compile` on merge, the code map beside it, the export back out.

This pack is that framework. Its model file is already the architecture pack's reified model, the
document and the proposal an adapter writes, held in `tests/fixtures/arch/*.model.json`; the adapter
in `code/plain_model.py` writes them where a real adapter would and returns what `oto arch import`
prints. The tests reach it by pointing `OTO_ONTOLOGIES` at `tests/fixtures/frameworks` (the
`plain_framework` fixture in `tests/conftest.py`). It is a test fixture, not a pack: nothing in the
engine's package or its marketplace names it.
