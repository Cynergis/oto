# Third-party licences

## The base install has no third-party dependencies

`pip install oto-kg` pulls in nothing. The compile stages, the validators and the query engine use only
the Python standard library, and CI asserts it. So an OTO build and an OTO query carry no third-party
licence obligations at all.

## Document extraction is optional, and one dependency needs a decision

`pip install 'oto-kg[intake]'` adds document parsers. Licences as declared by the packages:

| Package | Licence | Used for |
|---|---|---|
| python-docx | MIT | Word documents |
| python-pptx | MIT | PowerPoint decks |
| pdfplumber | MIT | PDF text extraction |
| openpyxl | MIT | Excel workbooks |
| lxml | BSD-3-Clause | XML parsing, pulled in by the Office parsers |
| beautifulsoup4 | MIT | Web pages and MHTML archives |
| pypdfium2 | BSD-3-Clause and Apache-2.0 | PDF page rasterization and figure detection |
| rdflib (`rdf` extra) | BSD-3-Clause | Reading a real ontology into the vocabulary with `oto ontology import --file` |
| pyshacl (`dev` extra only) | Apache-2.0 | The test that the SHACL in the export finds the same violations the engine finds |

Every one is permissive and compatible with Apache-2.0, with no obligation beyond attribution.

`pip install 'oto-kg[neo4j]'` adds the Neo4j Python driver (`neo4j`, Apache-2.0), used only by the
optional Neo4j target to load a copy of the built graph. `pip install 'oto-kg[draft]'` adds the Anthropic Python SDK (`anthropic`, MIT), used only by `oto draft`
to have a model write a document's first proposal. The compile, curate and serve paths never import it.
`pip install 'oto-kg[otel]'` adds OpenTelemetry (`opentelemetry-api`, `opentelemetry-sdk`,
`opentelemetry-exporter-otlp-proto-http`, all Apache-2.0), used only by `oto/tracing.py` when
`OTO_TRACE` or an OTLP endpoint is set; without them every span is a no-op. The `dev` extra installs the
SDK so the tests exercise real spans. `pip install 'oto-kg[postgres]'` adds `pg8000` (BSD-3-Clause, pure
Python), used only by the Postgres overlay to read a schema in place; `pip install 'oto-kg[bigquery]'`
adds `google-cloud-bigquery` (Apache-2.0), used only by the BigQuery overlay. Both overlays are tested
against recorded catalogs without the packages; the live Postgres kit runs in CI's postgres job.

## PyMuPDF was replaced

PyMuPDF is dual licensed: AGPL-3.0, or a paid commercial licence. The AGPL network clause reaches
software offered as a service, which does not suit an Apache-2.0 engine intended to run hosted. It
was replaced by **pypdfium2** (BSD-3-Clause and Apache-2.0, wrapping Google's PDFium).

The swap was measured over every page of a real corpus before it shipped: the figure-detection
decision was identical on all 215 pages, and rendered pages differed by under 0.5 of 255 per pixel.
PyMuPDF is **not** an OTO dependency and is not in any extra.

## Verifying this list

Licences here were read from the installed packages, not from memory:

```bash
python -c "import importlib.metadata as m; print(m.metadata('pymupdf')['License'])"
```

Re-check it whenever a dependency is added or upgraded. A dependency's licence can change between
versions.

## Test fixtures from other projects

`tests/fixtures/calm/trading-system.architecture.json` is the trading-system example from the FINOS
`architecture-as-code` repository (https://github.com/finos/architecture-as-code,
`docs/static/calm-example/trading-system.architecture.json`), Apache-2.0, copied unchanged as the
round-trip fixture for `oto arch import` and `export`.
