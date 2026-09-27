# -*- coding: utf-8 -*-
"""Word documents to a Document, preserving the order of paragraphs and tables.

Heading styles become headings; list styles become bullets. Embedded images are counted but not
written: in transcript exports they are almost always speaker-avatar thumbnails, which add noise to
retrieval. An extractor that wants them can set `keep_images`.
"""
import os

from ..document import (BULLET, HEADING, TABLE, TEXT, Block, Document, clean_cell,
                        slugify, table_to_markdown)
from ..registry import Extractor, register

# Word style name to markdown heading depth. The depths match the legacy corpus exactly.
_HEADING_DEPTH = [("heading 1", 2), ("title", 2), ("heading 2", 3), ("heading 3", 4)]
_OTHER_HEADING_DEPTH = 5


def _classify(style_name):
    """Return (kind, level) for a paragraph style."""
    s = (style_name or "").lower()
    for prefix, depth in _HEADING_DEPTH:
        if s == prefix or (prefix != "title" and s.startswith(prefix)):
            return HEADING, depth
    if s.startswith("heading"):
        return HEADING, _OTHER_HEADING_DEPTH
    if "list" in s or "bullet" in s:
        return BULLET, 0
    return TEXT, 0


def _iter_blocks(document):
    """Yield paragraphs and tables in document order. python-docx cannot do this on its own."""
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


@register
class Docx(Extractor):
    name = "docx"
    extensions = (".docx",)
    media_type = "Word document"
    requires = ("docx",)
    keep_images = False

    def extract(self, path, style, assets_dir=None):
        from docx import Document as WordDocument
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        filename = os.path.basename(path)
        doc = Document(slug=slugify(filename),
                       title=os.path.splitext(filename)[0],
                       source_name=filename,
                       media_type=self.media_type)

        word = WordDocument(path)
        tables = 0
        for item in _iter_blocks(word):
            if isinstance(item, Paragraph):
                text = item.text.strip()
                if not text:
                    continue
                kind, level = _classify(item.style.name if item.style else "")
                doc.add(Block(kind, text=text, level=level))
            elif isinstance(item, Table):
                rows = [[clean_cell(c.text) for c in r.cells] for r in item.rows]
                if rows:
                    tables += 1
                    doc.add(Block(TABLE, rows=rows))

        doc.extra = {"n_images": 0, "n_tables": tables}
        return doc


def render(doc, style):
    """Render to markdown. Byte-compatible with the legacy docx extractor."""
    lines = ["# %s\n" % doc.title,
             "> **Source:** `%s` · **Type:** %s · Converted to Markdown by the %s extraction "
             "pipeline.\n" % (style.ref(doc.source_name), doc.media_type, style.pipeline_name)]
    for b in doc.blocks:
        if b.kind == HEADING:
            lines.append("%s %s" % ("#" * b.level, b.text))
        elif b.kind == BULLET:
            lines.append("- %s" % b.text)
        elif b.kind == TABLE:
            md = table_to_markdown(b.rows)
            if md:
                lines.append("\n" + md + "\n")
        else:
            lines.append(b.text)
    return "\n".join(lines) + "\n"
