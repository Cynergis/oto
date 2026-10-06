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

Every one is permissive and compatible with Apache-2.0, with no obligation beyond attribution.

`pip install 'oto-kg[neo4j]'` adds the Neo4j Python driver (`neo4j`, Apache-2.0), used only by the
optional Neo4j target to load a copy of the built graph. `pip install 'oto-kg[draft]'` adds the Anthropic Python SDK (`anthropic`, MIT), used only by `oto draft`
to have a model write a document's first proposal. The compile, curate and serve paths never import it.

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
