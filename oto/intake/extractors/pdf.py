# -*- coding: utf-8 -*-
"""PDF to a Document: page text, plus a rendered image per page.

Two libraries, on purpose. pdfplumber reads the text. pypdfium2 rasterizes pages and inspects image
and vector objects. pypdfium2 (BSD-3-Clause and Apache-2.0, wrapping Google's PDFium) replaced
PyMuPDF, which is AGPL-3.0 or commercially licensed; the AGPL network clause reaches software offered
as a service, which does not suit an Apache-2.0 engine intended to run hosted. Parity was measured
rather than assumed: see THIRD-PARTY-LICENSES.md.

Exported slide decks are the common case, so every page may be a figure. A page is flagged as a
diagram when it carries embedded images or very little text, which marks it for a description pass.
Without a description a figure is invisible to search.
"""
import os

from ..document import DIAGRAM, PAGE, TEXT, Block, Document, slugify
from ..registry import Extractor, register

DPI = 150
SPARSE_TEXT_CHARS = 350        # below this, a page is probably a picture with a caption

# An embedded image only marks a page as a figure when it covers at least this share of the page.
#
# Without a threshold, ANY embedded image flags the page. Every corporate page carries a logo, and
# some carry a mascot, so a whole corpus gets flagged: measured on one real corpus, 38 of 75 flagged
# pages had a largest image under 2% of the page, and the pages were plain tables and title slides.
# Each false positive asks a person to describe a figure that does not exist.
#
# 0.20 matches the rule the slide extractor already used. Set 0.0 to reproduce the old behaviour,
# which is what a corpus extracted before this fix requires.
DOMINANT_IMAGE_AREA = 0.20

# A sparse-text page is only a figure if it actually carries something visual. Without this, every
# divider qualifies: measured on one real corpus, pages titled "Appendix", "Thank you." and bare
# section titles were all reported as undescribed figures. They have no content at all.
#
# Vector-drawing count separates them cleanly: dividers carried 1 to 4 drawings, genuine figures 6 or
# more. It is not perfect. A decoratively drawn title page can carry many drawings and still hold no
# data, and only a person or a vision pass can tell. This rule removes the certain cases, not all.
MIN_VECTOR_DRAWINGS = 5


@register
class Pdf(Extractor):
    name = "pdf"
    extensions = (".pdf",)
    media_type = "PDF deck"
    requires = ("pdfplumber", "pypdfium2")

    dominant_image_area = DOMINANT_IMAGE_AREA
    min_vector_drawings = MIN_VECTOR_DRAWINGS

    def extract(self, path, style, assets_dir=None):
        import pdfplumber
        import pypdfium2 as pdfium

        filename = os.path.basename(path)
        slug = slugify(filename)
        doc = Document(slug=slug, title=os.path.splitext(filename)[0],
                       source_name=filename, media_type=self.media_type)

        rendered = pdfium.PdfDocument(path)
        doc.extra["n_pages"] = len(rendered)
        try:
            if assets_dir:
                os.makedirs(assets_dir, exist_ok=True)
            with pdfplumber.open(path) as plumbed:
                for number, page in enumerate(plumbed.pages, 1):
                    text = (page.extract_text() or "").strip()
                    pdf_page = rendered[number - 1]
                    n_images, biggest, n_paths = _page_objects(pdf_page)
                    image_name = "page-%02d.png" % number
                    if assets_dir:
                        _render(pdf_page, DPI).save(os.path.join(assets_dir, image_name))

                    dominant = n_images > 0 and biggest >= self.dominant_image_area
                    sparse = len(text) < SPARSE_TEXT_CHARS
                    if self.min_vector_drawings <= 0:
                        visual = True                     # legacy: sparse text alone was enough
                    else:
                        visual = dominant or n_paths >= self.min_vector_drawings
                    is_diagram = dominant or (sparse and visual)
                    reasons = []
                    if dominant:
                        if self.dominant_image_area <= 0:
                            reasons.append("%d embedded image(s)" % n_images)
                        else:
                            reasons.append("image covering %d%% of the page" % round(biggest * 100))
                    if sparse and visual:
                        reasons.append("sparse text / visual layout")

                    title = ""
                    for line in text.splitlines():
                        if line.strip():
                            title = line.strip()[:90]
                            break

                    doc.add(Block(PAGE, text=title, level=number,
                                  meta={"n_text_chars": len(text), "n_embedded_imgs": n_images}))
                    if is_diagram:
                        asset = "assets/%s/%s" % (slug, image_name)
                        doc.assets.append(asset)
                        doc.add(Block(DIAGRAM, path=asset,
                                      meta={"page": number, "reasons": reasons}))
                    if text:
                        doc.add(Block(TEXT, text=text))
        finally:
            rendered.close()
        return doc


def _page_objects(page):
    """Return (image count, largest image share of the page, vector path count).

    One pass over the page objects. PDFium recurses into form XObjects by default, so an image nested
    inside a form is still found.
    """
    import pypdfium2.raw as raw

    width, height = page.get_size()
    page_area = abs(width * height)
    n_images = n_paths = 0
    biggest = 0.0
    for obj in page.get_objects():
        if obj.type == raw.FPDF_PAGEOBJ_IMAGE:
            n_images += 1
            if page_area:
                try:
                    left, bottom, right, top = obj.get_bounds()
                    biggest = max(biggest, abs((right - left) * (top - bottom)) / page_area)
                except Exception:
                    pass
        elif obj.type == raw.FPDF_PAGEOBJ_PATH:
            n_paths += 1
    return n_images, biggest, n_paths


def _render(page, dpi):
    """Rasterize one page to a PIL image.

    The scale is derived from the ROUNDED target pixel width, not from dpi/72 directly. PDFium rounds
    up where the previous backend rounded to nearest, and a one-pixel difference would make every
    re-rendered asset differ for no reason.
    """
    width_pt, _height_pt = page.get_size()
    target_px = max(1, int(round(width_pt * dpi / 72.0)))
    scale = target_px / width_pt if width_pt else dpi / 72.0
    return page.render(scale=scale).to_pil()


def render(doc, style):
    """Render to markdown. Byte-compatible with the legacy pdf extractor."""
    lines = ["# %s\n" % doc.title,
             "> **Source:** `%s` · **Type:** %s · **Pages:** %d · Converted to Markdown by the %s "
             "extraction pipeline.\n" % (style.ref(doc.source_name), doc.media_type,
                                         doc.extra.get("n_pages", 0), style.pipeline_name)]
    for b in doc.blocks:
        if b.kind == PAGE:
            suffix = (" — " + b.text) if b.text else ""
            lines.append("\n---\n\n## Page %d%s\n" % (b.level, suffix))
        elif b.kind == DIAGRAM:
            lines.append("> **[DIAGRAM]** (%s) — see `%s`. _Description added in review pass._\n"
                         % (", ".join(b.meta["reasons"]), b.path))
            lines.append("![Page %d](%s)\n" % (b.meta["page"], b.path))
        elif b.kind == TEXT:
            lines.append(b.text)
            lines.append("")
    return "\n".join(lines) + "\n"
