# OTO core

The base every shipped ontology extends, and the one to extend when no domain ontology fits. It
declares two things and nothing else:

- the **temporal vocabulary**: `asOf`, `validFrom`, `validTo`, `status`, `supersedes`,
  `supersededBy`, `sourceDoc`. These fields are what make a fact datable and supersedable, which
  is the property the whole system exists to protect. An ontology that extends this one inherits
  them and never merges them, so there is exactly one meaning of "current".
- **Document**, the class every fact cites, and `cites`, so a document can point at the document
  it rests on.

It is a first draft of nothing: a project started from `oto-core` alone has a vocabulary of one
class. Extend it in an ontology of your own (`"extends": ["oto-core"]` in `manifest.json`) and
declare the classes a real question needs. Edit it only to change what "a document" means for
every ontology at once.
