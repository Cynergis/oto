# -*- coding: utf-8 -*-
"""Excel workbooks to a Document: one table per sheet.

Empty rows and empty columns are dropped, because a spreadsheet's used range is usually much smaller
than its addressable range, and blank padding wastes retrieval space.
"""
import os

from ..document import HEADING, TABLE, Block, Document, clean_cell, slugify, table_to_markdown
from ..registry import Extractor, register


@register
class Xlsx(Extractor):
    name = "xlsx"
    extensions = (".xlsx",)
    media_type = "Excel workbook"
    requires = ("openpyxl",)

    def extract(self, path, style, assets_dir=None):
        from openpyxl import load_workbook

        filename = os.path.basename(path)
        doc = Document(slug=slugify(filename), title=os.path.splitext(filename)[0],
                       source_name=filename, media_type=self.media_type)

        workbook = load_workbook(path, read_only=True, data_only=True)
        sheets = 0
        for sheet in workbook.worksheets:
            rows = [[clean_cell(c) for c in row] for row in sheet.iter_rows(values_only=True)]
            rows = [r for r in rows if any(r)]                 # drop empty rows
            if not rows:
                continue
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            keep = [i for i in range(width) if any(r[i] for r in rows)]   # drop empty columns
            rows = [[r[i] for i in keep] for r in rows]
            if not rows or not keep:
                continue
            sheets += 1
            doc.add(Block(HEADING, text="Sheet: %s" % sheet.title, level=2))
            doc.add(Block(TABLE, rows=rows))

        doc.extra = {"n_sheets": len(workbook.worksheets), "n_tables": sheets}
        return doc


def render(doc, style):
    """Render to markdown. Byte-compatible with the legacy xlsx extractor, trailing newline included
    (the legacy writer omitted one, and the corpus records that)."""
    out = ["# %s" % doc.title, "",
           "> **Source:** `%s` · **Type:** %s · Converted to Markdown by the %s extraction "
           "pipeline." % (style.ref(doc.source_name), doc.media_type, style.pipeline_name), ""]
    for b in doc.blocks:
        if b.kind == HEADING:
            out.append("%s %s\n" % ("#" * b.level, b.text))
        elif b.kind == TABLE:
            out.append(table_to_markdown(b.rows))
            out.append("")
    return "\n".join(out)
