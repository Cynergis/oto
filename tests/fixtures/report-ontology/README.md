# The report ontology, as a fixture

`report.ttl` (`rpt:`, 2.1.0) and `ontology.ttl` (`flow:` and `dt:`, 0.1.1) copied on 2026-10-06 from the
report-ontology package: a vocabulary written in OWL with SKOS definitions, union domains, a class that
is a kind of an external one (`prov:Activity`), seven names declared in two namespaces, and three
namespaces in two files. It is what `oto ontology import --file` has to read without losing a term, and
what the export has to give back: the acceptance test of the rdflib reader (`tests/test_rdf_import.py`).
