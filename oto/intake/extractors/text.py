# -*- coding: utf-8 -*-
"""Markdown and plain text.

Markdown passes through unchanged. The file is already in the target format and a human wrote it, so
rewriting it would fight the author. Provenance is recorded on the Document rather than injected into
the text.

This extractor needs no third-party package, so it always works. A project whose sources are notes
and specifications needs nothing installed beyond OTO itself.
"""
import os

from ..document import HEADING, TEXT, Block, Document, slugify
from ..registry import Extractor, register


@register
class Text(Extractor):
    name = "text"
    extensions = (".md", ".markdown", ".txt")
    media_type = "Markdown or text"
    requires = ()

    def extract(self, path, style, assets_dir=None):
        filename = os.path.basename(path)
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()

        doc = Document(slug=slugify(filename), title=os.path.splitext(filename)[0],
                       source_name=filename, media_type=self.media_type)
        doc.extra["verbatim"] = content

        # Blocks are recorded so downstream readers see structure, even though rendering is verbatim.
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#"):
                depth = len(stripped) - len(stripped.lstrip("#"))
                doc.add(Block(HEADING, text=stripped[depth:].strip(), level=depth))
            elif stripped:
                doc.add(Block(TEXT, text=stripped))
        return doc


def render(doc, style):
    """Return the file unchanged. A trailing newline is ensured so the corpus is uniform."""
    content = doc.extra.get("verbatim", "")
    if content and not content.endswith("\n"):
        content += "\n"
    return content
