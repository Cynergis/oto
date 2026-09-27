# -*- coding: utf-8 -*-
"""MHTML web archives (.mht, .mhtml): one MIME file holding a page and every image it showed.

Browsers and Outlook save pages this way, and it is the common export from an intranet wiki. The
archive is a multipart message: the HTML part is the page, and the other parts are its images,
each named by the URL the page referenced. This extractor parses the message with the standard
library, hands the HTML to the web-page block builder, and answers its image lookups from the
archive's parts, so every image the page showed becomes a figure with a placeholder.
"""
import email
import os
from email import policy
from urllib.parse import unquote

from ..registry import Extractor, register
from .html import build_document
from .html import render as _render_html


def _parts(message):
    html, images = None, {}
    for part in message.walk():
        ctype = (part.get_content_type() or "").lower()
        if part.is_multipart():
            continue
        payload = part.get_payload(decode=True) or b""
        if ctype == "text/html" and html is None:
            charset = part.get_content_charset() or "utf-8"
            html = payload.decode(charset, errors="replace")
        elif ctype.startswith("image/"):
            for key in (part.get("Content-Location"), part.get("Content-ID")):
                if key:
                    key = key.strip().strip("<>")
                    images[key] = (payload, ctype)
                    images[os.path.basename(unquote(key))] = (payload, ctype)
    return html, images


@register
class Mht(Extractor):
    name = "mht"
    extensions = (".mht", ".mhtml")
    media_type = "Web archive"
    requires = ("bs4",)

    def extract(self, path, style, assets_dir=None):
        with open(path, "rb") as f:
            message = email.message_from_binary_file(f, policy=policy.default)
        html, images = _parts(message)
        if html is None:
            html = ""

        def resolver(src):
            src = (src or "").strip()
            if src.lower().startswith("cid:"):
                src = src[4:]
            return images.get(src) or images.get(os.path.basename(unquote(src)))

        doc = build_document(html, os.path.basename(path), self.media_type,
                             assets_dir=assets_dir, resolver=resolver)
        doc.extra["n_parts"] = len(images)
        return doc


def render(doc, style):
    return _render_html(doc, style)
