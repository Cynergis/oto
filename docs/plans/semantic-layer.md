# A semantic layer that means something: RDFS, SKOS and readable answers

Status: decided 2026-10-05 with Chiheb (see Decisions). On the `semantic-layer` branch: steps 1
to 5 are done. Written from a build of the shipped
`software-architecture` ontology and a comparison with the report ontology (Turtle, SHACL and SPARQL
questions), whose terms OTO cannot import today.

OTO's graph is right about facts and thin about meaning. An answer says `part_of → Payments
platform` and stops: it does not say what a Component is, what `part_of` means, what the thing is also
called, or what kind of thing it is a kind of. The RDF it exports cannot be read by anything but OTO.
This plan gives terms labels, definitions and a hierarchy, gives controlled values a home (SKOS concept
schemes), makes the export correct RDF, and puts the meaning into every card and every answer. The
compile path stays stdlib-only.

## What "dry" is, measured

Built from `oto init --ontology software-architecture`, unchanged:

| Where | What it does | Why it matters |
|---|---|---|
| `graph/triples.nt` | `<…/component.payment-api> <…/rel/type> "Component"`: the type is a string under a private predicate | No RDF tool finds a single Component: there is no `rdf:type` |
| `graph/triples.nt` vs `ontology/<slug>.ttl` | edges use `<BASE>rel/part_of`, the ontology declares `<BASE>part_of` | The exported ontology describes no triple of the exported graph; the two never join |
| `ontology/<slug>.ttl` | a union domain is written `rdfs:domain arch:Component, arch:Interface, arch:DataStore` | Several `rdfs:domain` values mean *all* of them: a reasoner infers every subject of `part_of` is a Component **and** an Interface **and** a DataStore. A union is `owl:unionOf` |
| `graph/triples.nt` | attributes, `summary` and `aliases` are not exported; dates are plain strings | Half of what a node says is missing from the RDF, and what is there is untyped |
| `ontology/<slug>.ttl` | `rdfs:label "part_of"`, `rdfs:label "Component"` | Labels are identifiers. No language, no human wording, no reading of the inverse |
| `ontology.rationale.json` | question, why, alternatives, validated_by | Never leaves the file: not in the Turtle, not in `ontology.md`, not in an answer |
| cards, `kg_entity` | `part_of → Payments platform`; incoming `Payment API → part_of` | Neither shows the class definition, the relation's meaning or a natural reading ("Payments platform **contains** Payment API") |
| the model | no `subClassOf`, no `subPropertyOf`; `enum:open\|closed` values are bare strings | "every Asset" cannot include its Components; a state has no label, definition or parent |
| `oto ontology import --file x.ttl` | reads only the one-line Turtle OTO writes; reads `rdfs:comment`, not `skos:definition` | The report ontology imports with 18 of 34 classes and no definitions |

## Goals

1. Every term carries a **preferred label per language**, alternative labels, a **definition**, and
   optionally a scope note and an example, exported as SKOS on the OWL terms.
2. Terms form a **hierarchy** (`rdfs:subClassOf`, `rdfs:subPropertyOf`) that queries honour.
3. **Controlled values are concepts**: a SKOS concept scheme with labels, definitions and
   broader/narrower, usable as an attribute type and as a roll-up in counts.
4. The **RDF export is correct**: typed instances, one set of term IRIs, typed literals, unions as unions.
5. **Answers read like knowledge**: cards, `kg_entity` and `ontology.md` show what a thing is, what each
   relation means in both directions, and what each value means.
6. **Import reads real ontologies**: Turtle, RDF/XML and JSON-LD with OWL, RDFS and SKOS, through an
   optional extra, and says what it could not map instead of dropping it.

Not goals: OWL reasoning beyond the subclass closure, SHACL, a SPARQL endpoint, SKOS-XL. SHACL and
executable competency questions are the next plan; they build on this one.

## The formats

Every declaration is written in one form, an object: a class `{definition}`, a property `{domain,
range, inverse, definition}`, an attribute `{type, definition}`, a temporal term `{type,
definition}`. The labels, notes and hierarchy keys below are optional additions to it. The string
and list forms are gone and refused with the reason (done, first half of step 2); the shipped
ontologies are converted.

### Classes and properties

```json
"languages": ["en", "fr"],
"classes": {
  "Asset": {"definition": "Anything the estate runs or stores."},
  "Component": {
    "definition": {"en": "A part of a system deployed or released as a unit.", "fr": "…"},
    "label": {"en": "Component", "fr": "Composant"},
    "alt_labels": {"en": ["service", "deployable"]},
    "subclass_of": ["Asset"],
    "scope_note": "A library linked into a component is not a component of its own.",
    "example": "the payments API, the nightly settlement job"
  }
},
"properties": {
  "part_of": {
    "domain": "Component|Interface|DataStore", "range": "System", "inverse": "contains",
    "definition": "This belongs to that system.",
    "label": {"en": "part of"}, "inverse_label": {"en": "contains"},
    "subproperty_of": null
  }
}
```

A string `definition` or `label` is English; a map gives one per language.

### Concept schemes

```json
"schemes": {
  "ClaimState": {
    "definition": "Where a claim is in its handling.",
    "concepts": {
      "open":     {"label": {"en": "Open"}, "definition": "Reported, not yet assessed."},
      "assessed": {"label": {"en": "Assessed"}, "broader": "open"},
      "closed":   {"label": {"en": "Closed"}, "alt_labels": {"en": ["settled", "done"]}}
    }
  }
},
"attributes": {"Claim": {"state": {"type": "scheme:ClaimState", "definition": "Where the claim is in its handling."}}}
```

`scheme:<Name>` is a new attribute type beside `enum:a|b`. A value is a concept key; `oto build`
refuses one the scheme does not declare, exactly as it refuses an enum value today. `enum:` stays for
lists too small to deserve meaning.

### Entity labels

A node may carry `labels` (`{"fr": "API de paiement"}`), and `hidden_labels` (misspellings and codes,
for resolution only, never shown). `aliases` stays and means alternative labels in the default
language. A lexicon entry becomes an alternative or hidden label of its targets in the export.

## The export

| Output | Change |
|---|---|
| term IRIs | each ontology declares its namespace in its `manifest.json` (`oto-core` gets one for the temporal vocabulary, shared by every project); instances move under `<BASE>id/` so a node never shares an IRI space with a class. Composing records which ontology brought each term in the vocabulary's `namespaces` section, which is all the build reads; a term no ontology claims is the project's own and lives under `<BASE>ont/`, which is also the namespace `oto ontology export` gives the ontology it writes |
| `graph/triples.nt` | `rdf:type` to the class IRI; predicates are the ontology's IRIs; attributes as typed literals (`xsd:date`, `xsd:decimal`, `xsd:boolean`), a list as an RDF collection, a structured value as one `rdf:JSON` literal, an attribute the vocabulary does not declare under the project's own namespace; scheme values as concept IRIs; `skos:prefLabel` / `skos:altLabel` with language tags; `summary` as `rdfs:comment`; temporal fields under the `oto-core` namespace |
| `graph/graph.ttl` | new: the same triples as prefixed Turtle, for people |
| `ontology/<slug>.ttl` | unions as `owl:unionOf`; `rdfs:subClassOf`, `rdfs:subPropertyOf`; on every term `skos:prefLabel`, `skos:altLabel`, `skos:definition`, `skos:scopeNote`, `skos:example` (and `rdfs:label` / `rdfs:comment` for RDFS-only tools); the rationale as `meta:question`, `meta:rationale`, `meta:alternatives`, `meta:validatedBy` (`https://cynergis.ai/ont/meta#`, the vocabulary the report ontology already uses); each scheme as `skos:ConceptScheme` with `skos:Concept`s, `skos:inScheme`, `skos:topConceptOf`, `skos:broader` / `skos:narrower` |
| `ontology/<slug>.context.jsonld` | the term IRIs above, so the JSON-LD and the Turtle agree |

SKOS annotates the OWL classes; classes are not punned into concepts. Concepts are reserved for
controlled values.

## Reading: cards, answers, the reference

```
=== Payment API  [Component — a part of a system deployed or released as a unit]  (component.payment-api) ===
aka: payments service  ·  fr: API de paiement  ·  a kind of Asset
status=current  ·  as_of=2026-01-01  ·  source_doc=sample

The service that accepts payment requests.

  state: Live (deployed and taking traffic)

Part of → Payments platform
Exposes → Payments API v2
Payments team owns this
```

- The class is named with its label and definition, and its ancestors ("a kind of Asset").
- Each relation is read with its label; incoming edges with the inverse label ("Payments platform
  **contains** Payment API"), falling back to today's form when no inverse label is declared.
- A scheme value is shown with its label and definition; `kg_group_by --by state --level top` rolls
  values up to their top concept.
- Cards carry the same, so retrieval matches the words people use, in every declared language.
- `ontology.md` gains the hierarchy as a tree, the schemes, and a rationale column.
- A new `kg_define <class|relation|concept>`: labels per language, definition, scope note, example,
  hierarchy, the rationale and who confirmed it, and how many nodes or edges use it. `kg_explain`
  stays about derived facts. (Done in step 2, without the hierarchy and the concepts, which steps
  3 and 4 add.)
- `kg_by_type`, `kg_count` and the domain/range conformance check include subclasses. The closure is
  computed at build into a `class_ancestors` table; no reasoner at query time.
- `kg_resolve` matches preferred, alternative and hidden labels in every language, ranked in that order.

## Import

`oto ontology import --file x.ttl|.rdf|.jsonld` reads real ontologies through a new `[rdf]` extra
(rdflib, BSD-3-Clause). It maps `owl:Class` / `rdfs:Class`, object and datatype properties, unions,
`subClassOf`, `subPropertyOf`, `inverseOf`, SKOS labels and notes (`rdfs:comment` as a fallback
definition), and concept schemes. It lists what it could not map (restrictions, cardinalities, property
chains) instead of dropping them. Without the extra, the one-line reader stays as it is.

Acceptance: the report ontology (`rpt:`, `flow:`, `dt:`, with `skos:definition`, union domains and
`subClassOf`) imports with every term, label, definition, union and parent, and exports back to an
equivalent graph.

## Change control

`oto ontology check` learns the new keys:

| Change | Severity |
|---|---|
| a parent class removed, a class moved to another parent | breaking; counted as the nodes that lose an ancestor |
| a parent added | additive |
| a domain or range widened (a union that gains members) | additive (today: breaking) |
| a domain or range narrowed | breaking |
| a concept removed | breaking; counted as the values that use it |
| a concept added, re-parented | additive |
| a label, definition, note or example, in any language | cosmetic |

A class or concept that a person confirmed (`validated_by`) and whose definition then changes is
listed for confirmation again: the confirmation covers the text it was given for.

## Order of work

| Step | What | Size |
|---|---|---|
| 1 (done) | The export is correct RDF: `rdf:type`, one set of term IRIs, `owl:unionOf`, typed literals, attributes and summaries exported. A test loads the export with rdflib (dev dependency) and asserts every predicate and type is declared, and that a SPARQL count of each class equals `knowledge-graph.json`'s | S |
| 2 (done) | Every declaration in the object form, across the engine, the shipped ontologies, the explorer and the tests; labels, definitions, languages and SKOS annotations on terms; the rationale in the Turtle (the `meta:` vocabulary, `https://cynergis.ai/ont/meta#`) and `ontology.md`; `graph/graph.ttl`; readable cards, `kg_entity` and explorer edges; `kg_define`. The shipped ontologies carry English only; a term is read by its name unless a label is written, so the shipped files write a label only where the name does not read well (`url` → "URL") | M |
| 3 (done) | Hierarchy: `subclass_of`, `subproperty_of`, the closure computed from the vocabulary, subclass-aware `kg_by_type`/`kg_count`/`kg_group_by`, rule and action patterns, relation filters, conformance and inherited attributes, the check rules (parent added additive, removed breaking and counted), RECONFIRM for a confirmed term whose definition changed, `rdfs:subClassOf`/`rdfs:subPropertyOf` in the Turtle and back through the importer. `software-architecture` gains `Asset`, the parent of System, Component, Interface and DataStore, with its rationale | M |
| 4 (done) | Concept schemes: the `schemes` section, `scheme:` attributes checked at the gates, values read by their concept in cards and answers, `kg_group_by level=top`, `kg_define` for a scheme and for a concept, the export as `skos:ConceptScheme`/`skos:Concept` with the attribute an object property onto them and each value its concept IRI, back through the importer, the check rules (concept removed breaking and counted; a note on each enum once languages are declared). `auto-claims`' claim and task states are the first schemes | M |
| 5 (done) | Import through the `[rdf]` extra (`model/rdf_import.py`, rdflib): classes, parents, relations with unions, inverses and parents, attributes with their types, schemes, labels and notes in every language, the `meta:` reasoning, each term keeping its IRI (a name two namespaces declare is imported under a prefixed name and `renamed` keeps its local name); what cannot be held is reported. With rdflib installed it also reads OTO's own Turtle; without it the one-line reader stays for `.ttl`. The report ontology (both files, three namespaces, 79 classes, 67 relations, 145 attribute declarations) imports and exports back with every class, label, definition, union, parent within the file and inverse equal; the two parents outside the file (`prov:Activity`, `prov:wasGeneratedBy`) are reported and left out. The temporal terms are now exported as `owl:AnnotationProperty`, so a reader skips them | M |

Step 1 is a correctness fix and stands alone. Steps 2 to 4 each ship with the shipped ontologies
updated to use them (labels and inverse labels first; `auto-claims` states as the first scheme).

## No backward compatibility

Nothing has been released and nobody depends on the current formats, so none of them is kept
alive beside its replacement: one form, one code path. Where a step changes a format, the shipped
ontologies, the registry's ontologies and packs, and the tests are rewritten in the new form in the
same change; what is not rewritten stops working and says why.

- An ontology states its `namespace`. One that does not, in a registry, a pack or a user
  directory, is reported as not usable. (Step 1.)
- The RDF export has one shape. Nothing reads the old `rel/` predicates or the comma-list unions.
  (Step 1.)
- Steps 2 to 4 pick one form for a class, a property and a controlled value and convert the shipped
  ontologies to it, rather than accepting the old form beside the new one.
- The compile path stays stdlib-only. rdflib is a dev dependency (tests) and the `[rdf]` extra (import).

## Decisions

Taken with Chiheb on 2026-10-05.

1. **Term namespace: each ontology unit declares its own** in `manifest.json`, so a project merged
   from two ontologies keeps both IRI sets and `oto-core`'s temporal terms are the same everywhere.
   One `<BASE>ont/` per project was simpler and would break every shared IRI.
2. **Every term carries both `skos:definition` and `rdfs:comment`**, generated from the one
   definition in the config. SKOS-aware tools read the first, RDFS-only tools the second, and readers
   of today's export keep working.
3. **English is the default language**: `en` unless `languages` says otherwise; a string definition or
   label is English.
4. **`enum:` and `scheme:` both stay.** An enum is a closed list of codes whose meaning needs no
   words (`in|out`, `pdf|png`); a scheme is for values people ask about, translate, roll up or share.
   Inside the engine an enum is a scheme whose concepts carry nothing but their key, so there is one
   code path, and promoting an enum to a scheme keeps every stored value (an additive change).
   `oto ontology check` notes an enum whose values carry no meaning once a project declares languages.
5. **No backward compatibility** (2026-10-05, after step 1): see the section above. It replaces the
   plan's earlier promises that existing configs, locks and exports would keep working unchanged.

## Not done here

- SHACL shapes in the curate gates, and executable competency questions (`questions.yaml`, `kg_ask`):
  the next plan, which reads the hierarchy and the schemes this one adds.
- Structured sources: a YAML or JSON file with an annotated schema compiled into a proposal without a
  model.
- OWL restrictions and reasoning beyond the subclass closure.
