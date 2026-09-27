"""Intake: the registry dispatches, the privacy gate blocks, markdown passes through."""
import json
import os
import tempfile

import pytest

from oto.intake.descriptions import auto_summary, inject, needs_injection
from oto.intake.document import Document, IntakeStyle, slugify, table_to_markdown
from oto.intake.registry import all_extractors, find, load_builtins, supported_extensions
from oto.validate.privacy import BLOCK, blocking, scan


def setup_module(module):
    load_builtins()


def test_registry_dispatches_by_extension():
    assert find("/tmp/a.docx").name == "docx"
    assert find("/tmp/a.pdf").name == "pdf"
    assert find("/tmp/a.md").name == "text"
    assert find("/tmp/a.unknown") is None


def test_office_lock_files_are_ignored():
    """A lock file is not a document. Ingesting one produces garbage."""
    assert find("/tmp/~$report.docx") is None


def test_text_extractor_needs_no_dependencies():
    """The one extractor that must always work."""
    text = [e for e in all_extractors() if e.name == "text"][0]
    assert text.requires == ()
    assert text.available() is True


def test_supported_extensions_cover_the_documented_set():
    assert set(supported_extensions()) >= {".docx", ".pdf", ".pptx", ".xlsx", ".md", ".txt",
                                           ".html", ".mht", ".doc", ".ppt", ".xls"}


def test_markdown_passes_through_unchanged():
    from oto.intake.extractors.text import Text, render

    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "notes.md")
        body = "# Notes\n\nA line.\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        doc = Text().extract(path, IntakeStyle())
        assert render(doc, IntakeStyle()) == body


def test_slugify_matches_the_corpus_rule():
    """Existing corpora depend on this exact rule. Changing it orphans every file."""
    assert slugify("Acme-Widgets Q3 - Master Plan v1.pptx") == "acme-widgets-q3-master-plan-v1"
    assert slugify("Handbook 101 - Part 1_1.pdf") == "handbook-101-part-1-1"
    assert slugify("  spaced & punctuated!.docx") == "spaced-punctuated"


def test_table_pads_short_rows():
    """A ragged table must still render as a valid grid, or the markdown breaks."""
    md = table_to_markdown([["a", "b"], ["d"]])
    assert md.splitlines()[-1] == "| d |  |"


def test_cell_escaping_protects_the_table_syntax():
    """An unescaped pipe in a cell splits it into two columns."""
    from oto.intake.document import clean_cell

    assert clean_cell("b|c") == "b\\|c"
    assert clean_cell("two\nlines") == "two lines"
    assert clean_cell(None) == ""


def test_privacy_blocks_a_social_insurance_number():
    findings = scan("SIN on file: 046 454 286")
    assert any(f.severity == BLOCK for f in findings)


def test_privacy_ignores_a_number_that_fails_its_checksum():
    """A nine-digit part number must not be reported as a social insurance number."""
    findings = scan("Part number 123456789 for the bumper.")
    assert not [f for f in findings if "social insurance" in f.kind]


def test_privacy_never_echoes_the_value():
    """A report that quotes what it found leaks it."""
    findings = scan("SIN on file: 046 454 286")
    for f in findings:
        assert "046454286" not in f.sample


def test_privacy_flags_a_vin_as_a_warning_not_a_block():
    findings = [f for f in scan("Vehicle: 1HGCM82633A004352")
                if "vehicle identification" in f.kind]
    assert findings and not blocking(findings)


def test_injection_replaces_the_placeholder():
    text = ("## Slide 3 — Operating model\n"
            "> **[DIAGRAM]** (2 chart(s)) — see `assets/deck/slide-03.png`. "
            "_Description added in review pass._\n"
            "- First label\n")
    assert needs_injection(text)
    out, n_curated, n_auto = inject(text, {})
    assert not needs_injection(out)
    assert n_auto == 1 and n_curated == 0
    assert "Operating model" in out


def test_injection_prefers_a_curated_description():
    text = ("## Slide 3 — Model\n"
            "> **[DIAGRAM]** (2 chart(s)) — see `assets/deck/slide-03.png`. "
            "_Description added in review pass._\n")
    out, n_curated, n_auto = inject(text, {"deck#3": "A curated explanation."})
    assert n_curated == 1 and n_auto == 0
    assert "A curated explanation." in out


def test_auto_summary_is_never_empty():
    assert auto_summary("", []).strip().endswith("full layout.")


def test_figures_separates_useful_from_needs_eyes():
    """A title-only summary looks like a description and adds nothing, so it must not count as one."""
    import os
    import tempfile

    from oto.intake.figures import NEEDS_EYES, USEFUL, report, scan_corpus

    with_labels = ("## Slide 1 — Operating model\n"
                   "> **[DIAGRAM]** (2 chart(s)) — see `assets/deck/slide-01.png`. "
                   "_Description added in review pass._\n"
                   "- First label\n- Second label\n")
    title_only = ("## Slide 2 — A picture\n"
                  "> **[DIAGRAM]** (dominant picture) — see `assets/deck/slide-02.png`. "
                  "_Description added in review pass._\n")
    with tempfile.TemporaryDirectory() as corpus:
        with open(os.path.join(corpus, "deck.md"), "w", encoding="utf-8") as f:
            f.write(with_labels + title_only)
        figures = scan_corpus(corpus)
        assert len(figures) == 2
        verdicts = [f["verdict"] for f in figures]
        assert USEFUL in verdicts and NEEDS_EYES in verdicts
        assert "need a real description" in report(figures)


def test_figures_reports_nothing_when_all_are_described():
    import os
    import tempfile

    from oto.intake.figures import report, scan_corpus

    with tempfile.TemporaryDirectory() as corpus:
        with open(os.path.join(corpus, "deck.md"), "w", encoding="utf-8") as f:
            f.write("## Slide 1\n> **[DIAGRAM]** (2 chart(s)) — see `assets/d/slide-01.png`.\n>\n"
                    "> **Description:** A real description.\n")
        assert scan_corpus(corpus) == []
        assert report([]) == "Every figure has a description."


def test_pdf_needs_a_dominant_image_not_just_any_image():
    """Every corporate page carries a logo. Flagging on any image flags the whole corpus.

    Measured on one real corpus: 61% of flagged figures were decoration, and each one asked a person
    to describe a figure that did not exist.
    """
    from oto.intake.extractors.pdf import DOMINANT_IMAGE_AREA, Pdf

    assert DOMINANT_IMAGE_AREA > 0, "any-image detection floods the worklist with decoration"
    assert Pdf().dominant_image_area == DOMINANT_IMAGE_AREA


def _fake_page(objects, size=(100.0, 100.0)):
    """A stand-in for a PDFium page, so object handling is testable without a real PDF."""

    class FakePage:
        def get_size(self):
            return size

        def get_objects(self):
            return iter(objects)

    return FakePage()


def _fake_object(kind, bounds=None, raises=False):
    class FakeObject:
        type = kind

        def get_bounds(self):
            if raises:
                raise ValueError("malformed object")
            return bounds

    return FakeObject()


def test_page_objects_counts_nothing_on_an_empty_page():
    from oto.intake.extractors.pdf import _page_objects

    assert _page_objects(_fake_page([])) == (0, 0.0, 0)


def test_page_objects_separates_images_from_paths():
    import pypdfium2.raw as raw

    from oto.intake.extractors.pdf import _page_objects

    objects = [
        _fake_object(raw.FPDF_PAGEOBJ_IMAGE, bounds=(0.0, 0.0, 50.0, 50.0)),   # a quarter of the page
        _fake_object(raw.FPDF_PAGEOBJ_PATH),
        _fake_object(raw.FPDF_PAGEOBJ_PATH),
        _fake_object(raw.FPDF_PAGEOBJ_TEXT),
    ]
    n_images, biggest, n_paths = _page_objects(_fake_page(objects))
    assert n_images == 1
    assert n_paths == 2
    assert abs(biggest - 0.25) < 1e-9


def test_page_objects_survives_a_malformed_image():
    """A malformed object must not abort extraction of the whole document."""
    import pypdfium2.raw as raw

    from oto.intake.extractors.pdf import _page_objects

    objects = [_fake_object(raw.FPDF_PAGEOBJ_IMAGE, raises=True)]
    n_images, biggest, n_paths = _page_objects(_fake_page(objects))
    assert n_images == 1, "the image must still be counted"
    assert biggest == 0.0
    assert n_paths == 0


def test_page_objects_handles_a_zero_area_page():
    """A degenerate page size must not divide by zero."""
    import pypdfium2.raw as raw

    from oto.intake.extractors.pdf import _page_objects

    objects = [_fake_object(raw.FPDF_PAGEOBJ_IMAGE, bounds=(0.0, 0.0, 10.0, 10.0))]
    assert _page_objects(_fake_page(objects, size=(0.0, 0.0))) == (1, 0.0, 0)


def test_pdf_extractor_does_not_depend_on_the_agpl_library():
    """PyMuPDF is AGPL-3.0 or commercial. It must not reappear as a dependency."""
    import inspect

    from oto.intake.extractors import pdf

    source = inspect.getsource(pdf)
    assert "fitz" not in source, "the AGPL PDF library is back in the extractor"
    assert "pypdfium2" in pdf.Pdf.requires


# ---- a figure nobody can describe ----

def _placeholder_document(tmp_path, slug, image_name, on_disk):
    """A corpus document holding one undescribed figure, with or without the image on disk."""
    corpus = tmp_path / "documents"
    corpus.mkdir(exist_ok=True)
    (corpus / ("%s.md" % slug)).write_text(
        "## Slide 1 — A slide with a picture\n\n"
        "> **[DIAGRAM]** (dominant-image) — see `assets/%s/%s`. "
        "_Description added in review pass._\n" % (slug, image_name),
        encoding="utf-8")
    if on_disk:
        assets = corpus / "assets" / slug
        assets.mkdir(parents=True, exist_ok=True)
        (assets / image_name).write_bytes(b"\x89PNG\r\n\x1a\n")
    return str(corpus)


def test_a_missing_image_is_recorded_as_missing(tmp_path):
    from oto.intake import figures

    corpus = _placeholder_document(tmp_path, "deck", "slide-1.png", on_disk=False)
    found = figures.scan_corpus(corpus)
    assert len(found) == 1
    assert found[0]["image_present"] is False


def test_an_image_on_disk_is_recorded_as_present(tmp_path):
    from oto.intake import figures

    corpus = _placeholder_document(tmp_path, "deck", "slide-1.png", on_disk=True)
    found = figures.scan_corpus(corpus)
    assert found[0]["image_present"] is True


def test_the_report_says_when_no_description_is_possible(tmp_path):
    """"Not described" and "cannot be described" have different fixes, so they need different words."""
    from oto.intake import figures

    corpus = _placeholder_document(tmp_path, "deck", "slide-1.png", on_disk=False)
    found = figures.scan_corpus(corpus)
    text = figures.report(found)
    assert "no image on disk" in text
    assert "Render the missing images" in text


def test_workable_figures_come_first_in_the_worklist(tmp_path):
    from oto.intake import figures

    corpus = _placeholder_document(tmp_path, "gone", "slide-1.png", on_disk=False)
    _placeholder_document(tmp_path, "here", "slide-1.png", on_disk=True)
    found = figures.scan_corpus(corpus)
    assert len(found) == 2

    path = str(tmp_path / "work.json")
    figures.worklist(found, path)
    payload = json.load(open(path, encoding="utf-8"))
    order = [f["image_present"] for f in payload["figures"]]
    assert order == sorted(order, reverse=True), "actionable entries must come first"
