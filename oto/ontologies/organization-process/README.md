# Organization and process — starter vocabulary

The smallest useful vocabulary. Use it when no other ontology fits, or when you want to add only what
you turn out to need.

A first draft, not a finished model. **Edit it.** An ontology adopted unchanged is a worse outcome than
no ontology, because nobody owns it and nobody recognizes the words.

## Nine classes on purpose

A first ontology is almost always too big. Someone lists every noun in the domain, declares forty
classes, and then nobody can hold the model in their head or say which class a new fact belongs to.
The model stops being used and starts being argued about.

Nine classes will feel too few. Add the tenth when a real question needs it, and write down which
question. That habit is worth more than any starting vocabulary.

## What is deliberately absent

- **`Person`.** Ownership points at a `Role`. Add `Person` only when you must trace an individual's
  decisions, and then hold nothing about them beyond that. A roster is easy to build and hard to
  justify.
- **`Risk`, `Project`, `Customer`, `Product`.** Each is reasonable and none is universal. Add the one
  your questions need.
- **Anything a system of record already owns.** If your human resources system knows the reporting
  lines, reference it, do not copy it. A copy is wrong within a month, and nothing tells you.

## Growing it

```bash
oto ontology check --project <project>     # what changed, and what it breaks
# raise ontology_version, then:
oto ontology accept --project <project>
```

Bump `ontology_version` whenever you remove a class or a relation, or narrow a domain or a range.
Those are the changes that invalidate data you already have.
