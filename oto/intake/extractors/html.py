# -*- coding: utf-8 -*-
"""Web pages to a Document: headings, paragraphs, lists, tables, and the images they carry.

Images are the reason this extractor exists as more than a text scraper. An exported wiki page or
a report saved as HTML carries its diagrams as files beside it or as data URIs inside it. Each one
is written to the assets directory and gets the same figure placeholder a slide gets, so the
description pass and `oto figures` treat it like any other figure. An image that lives on the web
is recorded as a link with its alt text and nothing is downloaded: extraction never reaches the
network, so it stays reproducible.

The same block builder serves the MHTML extractor, which supplies the images from the archive.
"""
import base64
import os
import re
import shutil
from urllib.parse import unquote, urlparse

from ..document import (BULLET, DIAGRAM, HEADING, IMAGE, TABLE, TEXT, Block, Document, clean_cell,
                        slugify, table_to_markdown)
from ..registry import Extractor, register

SKIP_TAGS = ("script", "style", "noscript", "template", "svg")
IMAGE_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/gif": ".gif",
             "image/webp": ".webp"}
DATA_URI = re.compile(r"^data:(image/[a-z+]+);base64,(.*)$", re.S | re.I)


def _soup(html):
    from bs4 import BeautifulSoup
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:                                 # lxml absent: the stdlib parser will do
        return BeautifulSoup(html, "html.parser")


def _text(node):
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


class _Images:
    """Writes images into the assets directory, numbered in document order."""

    def __init__(self, slug, assets_dir, resolver=None):
        self.slug = slug
        self.assets_dir = assets_dir
        self.resolver = resolver          # src -> (bytes, content_type) or None, for archives
        self.count = 0
        self.assets = []

    def _write(self, data, ext):
        if not self.assets_dir:
            return None
        self.count += 1
        os.makedirs(self.assets_dir, exist_ok=True)
        name = "image-%02d%s" % (self.count, ext)
        with open(os.path.join(self.assets_dir, name), "wb") as f:
            f.write(data)
        asset = "assets/%s/%s" % (self.slug, name)
        self.assets.append(asset)
        return asset, self.count

    def place(self, src, base_dir):
        """Return (asset path, number) for an image that can be stored, else None."""
        if not src:
            return None
        m = DATA_URI.match(src.strip())
        if m:
            try:
                return self._write(base64.b64decode(m.group(2)), IMAGE_EXT.get(m.group(1).lower(), ".png"))
            except Exception:
                return None
        if self.resolver:
            found = self.resolver(src)
            if found:
                data, content_type = found
                return self._write(data, IMAGE_EXT.get((content_type or "").lower(),
                                                       os.path.splitext(urlparse(src).path)[1] or ".png"))
        if urlparse(src).scheme in ("http", "https", "ftp"):
            return None                               # never fetched
        if base_dir:
            local = os.path.normpath(os.path.join(base_dir, unquote(urlparse(src).path)))
            if os.path.isfile(local) and self.assets_dir:
                ext = os.path.splitext(local)[1].lower() or ".png"
                with open(local, "rb") as f:
                    return self._write(f.read(), ext)
        return None


def build_document(html, filename, media_type, assets_dir=None, base_dir=None, resolver=None):
    """The block builder. `resolver` lets an archive supply images by their original reference."""
    soup = _soup(html)
    for tag in soup(SKIP_TAGS):
        tag.decompose()
    slug = slugify(filename)
    title = (soup.title.get_text(strip=True) if soup.title and soup.title.get_text(strip=True)
             else (soup.h1.get_text(strip=True) if soup.h1 else os.path.splitext(filename)[0]))
    doc = Document(slug=slug, title=title, source_name=filename, media_type=media_type)
    images = _Images(slug, assets_dir, resolver)
    body = soup.body or soup

    def walk(node, list_depth=0):
        for child in list(node.children):
            name = getattr(child, "name", None)
            if name is None:
                continue
            if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                text = _text(child)
                if text and text != title:
                    doc.add(Block(HEADING, text=text, level=min(int(name[1]) + 1, 6)))
            elif name == "p":
                text = _text(child)
                if text:
                    doc.add(Block(TEXT, text=text))
                for img in child.find_all("img"):
                    _image(img)
            elif name in ("ul", "ol"):
                for li in child.find_all("li", recursive=False):
                    own = " ".join(t for t in li.find_all(string=True, recursive=False))
                    inline = " ".join(_text(c) for c in li.children
                                      if getattr(c, "name", None) not in (None, "ul", "ol"))
                    text = re.sub(r"\s+", " ", (own + " " + inline)).strip()
                    if text:
                        doc.add(Block(BULLET, text=text, level=list_depth))
                    for sub in li.find_all(("ul", "ol"), recursive=False):
                        for sli in sub.find_all("li", recursive=False):
                            st = _text(sli)
                            if st:
                                doc.add(Block(BULLET, text=st, level=list_depth + 1))
            elif name == "table":
                rows = [[clean_cell(_text(c)) for c in tr.find_all(("td", "th"))]
                        for tr in child.find_all("tr")]
                rows = [r for r in rows if any(r)]
                if rows:
                    doc.add(Block(TABLE, rows=rows))
            elif name == "img":
                _image(child)
            elif name == "pre":
                text = child.get_text().strip("\n")
                if text.strip():
                    doc.add(Block(TEXT, text="```\n%s\n```" % text))
            elif name == "blockquote":
                text = _text(child)
                if text:
                    doc.add(Block(TEXT, text="> " + text))
            else:
                walk(child, list_depth)

    def _image(img):
        src = img.get("src") or img.get("data-src") or ""
        alt = _text(img) or (img.get("alt") or "").strip() or (img.get("title") or "").strip()
        placed = images.place(src, base_dir)
        if placed:
            asset, number = placed
            doc.add(Block(DIAGRAM, path=asset, meta={"image": number, "alt": alt,
                                                    "reasons": ["embedded image"]}))
        elif src:
            doc.add(Block(IMAGE, text=alt, path=src))

    walk(body)
    doc.assets = images.assets
    doc.extra = {"n_images": images.count}
    return doc


@register
class Html(Extractor):
    name = "html"
    extensions = (".html", ".htm", ".xhtml")
    media_type = "Web page"
    requires = ("bs4",)

    def extract(self, path, style, assets_dir=None):
        with open(path, "rb") as f:
            raw = f.read()
        html = raw.decode("utf-8", errors="replace")
        return build_document(html, os.path.basename(path), self.media_type,
                              assets_dir=assets_dir, base_dir=os.path.dirname(os.path.abspath(path)))


def render(doc, style):
    lines = ["# %s\n" % doc.title,
             "> **Source:** `%s` · **Type:** %s · Converted to Markdown by the %s extraction "
             "pipeline.\n" % (style.ref(doc.source_name), doc.media_type, style.pipeline_name)]
    for b in doc.blocks:
        if b.kind == HEADING:
            lines.append("%s %s" % ("#" * b.level, b.text))
        elif b.kind == BULLET:
            lines.append(("  " * b.level) + "- %s" % b.text)
        elif b.kind == TABLE:
            md = table_to_markdown(b.rows)
            if md:
                lines.append("\n" + md + "\n")
        elif b.kind == DIAGRAM:
            lines.append("> **[DIAGRAM]** (%s) — see `%s`. _Description added in review pass._\n"
                         % (", ".join(b.meta["reasons"]), b.path))
            lines.append("![%s](%s)\n" % (b.meta.get("alt") or "Image %d" % b.meta["image"], b.path))
        elif b.kind == IMAGE:
            lines.append("![%s](%s)  _(external image, not fetched)_\n" % (b.text or "image", b.path))
        else:
            lines.append(b.text)
    return "\n".join(lines) + "\n"
