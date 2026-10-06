# -*- coding: utf-8 -*-
"""Why each class and relation exists, and who confirmed it.

A vocabulary without recorded reasoning cannot be reviewed. A domain expert looking at a list of
sixteen class names has no way to tell a deliberate choice from an accident, so the review that
matters most never happens, and the model gets re-litigated instead.

So the interview produces two files, not one:

    ontology.config.json      the vocabulary
    ontology.rationale.json   why each class exists, and who validated it

The `validated_by` field is the point. It records whether a person who knows the domain has actually
confirmed a class, and when. That turns "the model looks reasonable" into a countable claim:
"4 of 16 classes confirmed by a claims professional, 12 not yet".

Rationale is REQUIRED for classes and optional for relations. Classes are where the modelling
decisions live: whether something is its own kind of thing, or an attribute, or two things merged.
Relations mostly follow from the classes, and their description usually says enough. A relation entry
is for the ones where it does not.

An empty or copied rationale is worse than none, because it looks like the review happened. The
checker rejects a rationale that merely repeats the description, or that is too short to say anything.
"""
import json
import os

RATIONALE_NAME = "ontology.rationale.json"
MIN_WHY_CHARS = 40


def path_for(project):
    return os.path.join(project.data, RATIONALE_NAME)


def load(project):
    """The recorded rationale, or an empty one when a project has none."""
    path = path_for(project)
    if not os.path.exists(path):
        return {"classes": {}, "properties": {}}
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    return {"classes": payload.get("classes") or {},
            "properties": payload.get("properties") or {}}


def save(project, record):
    payload = {
        "_about": ("Why each class and relation exists, and who confirmed it. Written by the ontology "
                   "interview and edited by hand. `validated_by` is empty until a person who knows the "
                   "domain has actually confirmed the entry; leave it empty rather than guessing."),
        "classes": record.get("classes") or {},
        "properties": record.get("properties") or {},
    }
    path = path_for(project)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    return path


def _entry_problems(kind, name, entry, definition):
    """What is wrong with one rationale entry."""
    problems = []
    if not isinstance(entry, dict):
        return ["%s %r rationale must be an object" % (kind, name)]
    question = (entry.get("question") or "").strip()
    why = (entry.get("why") or "").strip()
    if not question:
        problems.append("%s %r has no `question`: what does it exist to answer?" % (kind, name))
    if not why:
        problems.append("%s %r has no `why`" % (kind, name))
    elif definition and why == (definition or "").strip():
        # Checked BEFORE the length test on purpose. Most class definitions are short, so a copied
        # one would otherwise be reported as "too short", which sends the reader the wrong way.
        problems.append("%s %r repeats its definition instead of giving a reason" % (kind, name))
    elif len(why) < MIN_WHY_CHARS:
        problems.append("%s %r has a `why` too short to say anything (%d characters)"
                        % (kind, name, len(why)))
    return problems


def report(vocabulary_config, record):
    """Coverage and problems, for `oto ontology rationale`."""
    classes = vocabulary_config.get("classes") or {}
    properties = vocabulary_config.get("properties") or {}
    class_rationale = record.get("classes") or {}
    property_rationale = record.get("properties") or {}

    problems = []
    missing_classes = []
    validated_classes = []
    for name in sorted(classes):
        entry = class_rationale.get(name)
        if not entry:
            missing_classes.append(name)
            continue
        problems += _entry_problems("class", name, entry, (classes.get(name) or {}).get("definition"))
        if (entry.get("validated_by") or "").strip():
            validated_classes.append(name)

    # A rationale for something no longer declared is stale and misleading.
    for name in sorted(set(class_rationale) - set(classes)):
        problems.append("rationale for class %r, which is no longer declared" % name)
    for name in sorted(set(property_rationale) - set(properties)):
        problems.append("rationale for relation %r, which is no longer declared" % name)

    validated_properties = []
    for name in sorted(property_rationale):
        if name not in properties:
            continue
        entry = property_rationale[name]
        problems += _entry_problems("relation", name, entry, (properties.get(name) or {}).get("definition"))
        if (entry.get("validated_by") or "").strip():
            validated_properties.append(name)

    return {
        "classes": len(classes),
        "classes_with_rationale": len(classes) - len(missing_classes),
        "classes_missing": missing_classes,
        "classes_validated": validated_classes,
        "properties": len(properties),
        "properties_with_rationale": len([n for n in property_rationale if n in properties]),
        "properties_validated": validated_properties,
        "problems": problems,
    }
