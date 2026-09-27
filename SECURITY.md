# Security policy

## Reporting a vulnerability

Report security issues privately to security@cynergis.ai. Do not open a public issue.

## Scope and design intent

OTO is an engine. It ships **no data**.

- An OTO project holds your data. Keep that repository private.
- OTO never writes credentials to disk in this repository.
- The pre-ingest privacy gate scans candidate documents for personal data and secrets before they
  enter a corpus. It reduces risk. It is not a substitute for your own review.
- Access control is enforced by the serving layer, not by the graph file. A graph file grants full
  read access to whoever holds it. Treat it as confidential.
