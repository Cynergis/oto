# -*- coding: utf-8 -*-
"""The one intermediate format.

Every source type, whatever it is, becomes a `Document`: an ordered list of typed blocks with
provenance. Everything downstream reads a Document, never a source file. That is what keeps the
engine domain agnostic and format agnostic at the same time.

Markdown is a *rendering* of a Document, not the canonical form. The canonical form is structured, so
a graph builder can read blocks instead of re-parsing prose.

Nothing here records a timestamp. Extraction must be reproducible, so two runs over the same input
produce identical output.
"""
import os
import re

# Block kinds. Keep this list small: a kind earns its place by changing how a reader treats the text.
HEADING = "heading"
TEXT = "text"
BULLET = "bullet"
TABLE = "table"
IMAGE = "image"
PAGE = "page"       # a page or slide boundary in a paginated source
NOTE = "note"       # speaker notes, comments, annotations
DIAGRAM = "diagram"  # a figure that needs a description to be searchable


class Block:
    """One ordered piece of a document."""

    __slots__ = ("kind", "text", "level", "rows", "path", "meta")

    def __init__(self, kind, text="", level=0, rows=None, path=None, meta=None):
        self.kind = kind
        self.text = text
        self.level = level
        self.rows = rows or []
        self.path = path
        self.meta = meta or {}

    def to_dict(self):
        out = {"kind": self.kind}
        if self.text:
            out["text"] = self.text
        if self.level:
            out["level"] = self.level
        if self.rows:
            out["rows"] = self.rows
        if self.path:
            out["path"] = self.path
        if self.meta:
            out["meta"] = self.meta
        return out


class IntakeStyle:
    """How a Document renders its provenance header.

    This is configurable because the header text lands in every extracted file, so changing it is a
    corpus migration, not a cosmetic edit. A project that already has an extracted corpus pins its
    own wording; a new project takes the default.
    """

    def __init__(self, source_ref="inbox/{filename}", pipeline_name="OTO"):
        self.source_ref = source_ref
        self.pipeline_name = pipeline_name

    def ref(self, filename):
        return self.source_ref.format(filename=filename)


DEFAULT_STYLE = IntakeStyle()


class Document:
    """A source file, normalized."""

    def __init__(self, slug, title, source_name, media_type, blocks=None, assets=None,
                 warnings=None, extra=None):
        self.slug = slug
        self.title = title
        self.source_name = source_name
        self.media_type = media_type          # human label, e.g. "Word document"
        self.blocks = blocks or []
        self.assets = assets or []            # asset paths relative to the corpus directory
        self.warnings = warnings or []
        self.extra = extra or {}              # per-format counts, e.g. slides or pages

    def add(self, block):
        self.blocks.append(block)
        return block

    def text(self):
        """All prose, for scanning. Table cells included; asset paths excluded."""
        parts = []
        for b in self.blocks:
            if b.text:
                parts.append(b.text)
            for row in b.rows:
                parts.extend(str(c) for c in row)
        return "\n".join(parts)

    def to_dict(self):
        return {
            "slug": self.slug,
            "title": self.title,
            "source_name": self.source_name,
            "media_type": self.media_type,
            "extra": self.extra,
            "assets": self.assets,
            "warnings": self.warnings,
            "blocks": [b.to_dict() for b in self.blocks],
        }


def slugify(name):
    """Filename to slug. Must match the legacy rule exactly: existing corpora depend on it."""
    s = os.path.splitext(name)[0].lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def table_to_markdown(rows):
    """Render a table. Pads short rows, escapes pipes, flattens newlines."""
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    padded = [list(r) + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(padded[0]) + " |",
           "| " + " | ".join(["---"] * width) + " |"]
    for r in padded[1:]:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def clean_cell(value):
    return str(value or "").replace("\n", " ").replace("|", "\\|").strip()
