"""Web pages, web archives and legacy Office files reach the corpus like any other source."""
import base64
import os
import tempfile
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest

from oto.intake.document import IntakeStyle
from oto.intake.registry import find, load_builtins, supported_extensions

pytest.importorskip("bs4")

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
STYLE = IntakeStyle()

PAGE = """<html><head><title>Claims handbook</title><style>p{color:red}</style></head><body>
<script>alert(1)</script>
<h1>Claims handbook</h1>
<p>The <b>Claims Adjuster</b> reviews each First Notice of Loss within 2 days.</p>
<h2>Escalation</h2>
<ul><li>Disputes go to the Claims Manager<ul><li>within one week</li></ul></li><li>Fraud goes to the Fraud Unit</li></ul>
<table><tr><th>Role</th><th>Limit</th></tr><tr><td>Adjuster</td><td>5,000</td></tr></table>
<img src="flow.png" alt="Escalation flow">
<img src="data:image/png;base64,%s" alt="Inline chart">
<img src="https://example.com/remote.png" alt="Remote">
<pre>code here</pre>
</body></html>""" % base64.b64encode(PNG).decode()


def _write_page(root):
    path = os.path.join(root, "handbook.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(PAGE)
    with open(os.path.join(root, "flow.png"), "wb") as f:
        f.write(PNG)
    return path


def test_the_new_formats_are_registered():
    load_builtins()
    assert {".html", ".htm", ".mht", ".mhtml", ".doc", ".ppt", ".xls"} <= set(supported_extensions())
    assert find("x.html").name == "html" and find("x.mht").name == "mht" and find("x.doc").name == "legacy"


def test_html_becomes_headings_text_lists_tables_and_figures():
    with tempfile.TemporaryDirectory() as root:
        path = _write_page(root)
        assets = os.path.join(root, "assets", "handbook")
        doc = find(path).extract(path, STYLE, assets_dir=assets)
        from oto.intake.extractors.html import render
        text = render(doc, STYLE)
        assert os.path.exists(os.path.join(assets, "image-01.png")) and os.path.exists(os.path.join(assets, "image-02.png"))
    assert text.startswith("# Claims handbook\n")
    assert "alert(1)" not in text and "color:red" not in text, "script and style are dropped"
    assert "The Claims Adjuster reviews each First Notice of Loss within 2 days." in text
    assert "### Escalation" in text
    assert "- Disputes go to the Claims Manager" in text and "  - within one week" in text
    assert "| Role | Limit |" in text and "| Adjuster | 5,000 |" in text
    assert "```\ncode here\n```" in text
    # Two stored images, one placeholder each, numbered in order; the remote one is a link only.
    assert text.count("_Description added in review pass._") == 2
    assert "`assets/handbook/image-01.png`" in text and "`assets/handbook/image-02.png`" in text
    assert "![Escalation flow](assets/handbook/image-01.png)" in text
    assert "![Remote](https://example.com/remote.png)  _(external image, not fetched)_" in text
    assert doc.extra["n_images"] == 2


def test_html_figures_get_descriptions_and_are_counted_by_the_figure_report():
    from oto.intake.descriptions import inject, needs_injection
    from oto.intake.figures import scan_corpus

    with tempfile.TemporaryDirectory() as root:
        path = _write_page(root)
        corpus = os.path.join(root, "documents")
        assets = os.path.join(corpus, "assets", "handbook")
        doc = find(path).extract(path, STYLE, assets_dir=assets)
        from oto.intake.extractors.html import render
        text = render(doc, STYLE)
        assert needs_injection(text)
        text, n_curated, n_auto = inject(text, {"handbook#1": "The escalation flow from adjuster to manager."})
        assert (n_curated, n_auto) == (1, 1)
        assert "> **Description:** The escalation flow from adjuster to manager." in text
        with open(os.path.join(corpus, "handbook.md"), "w", encoding="utf-8") as f:
            f.write(text)
        # After injection the curated figure is described; the auto-summarised one without labels
        # is still reported as needing eyes, image present.
        figures = scan_corpus(corpus, {"handbook#1": "x"})
        assert [f["key"] for f in figures] == ["handbook#2"]
        assert figures[0]["image_present"] and "needs" in figures[0]["verdict"]


def test_html_without_lxml_still_parses(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def no_lxml(name, *a, **k):
        if name == "lxml" or name.startswith("lxml."):
            raise ImportError("no lxml")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_lxml)
    from oto.intake.extractors.html import build_document
    doc = build_document("<html><body><h2>Only</h2><p>Text.</p></body></html>", "x.html", "Web page")
    assert [b.kind for b in doc.blocks] == ["heading", "text"]


def test_mhtml_supplies_its_images_from_the_archive():
    message = MIMEMultipart("related")
    message["Subject"] = "Saved page"
    html = ('<html><head><title>Wiki page</title></head><body><h1>Wiki page</h1>'
            '<p>A paragraph.</p><img src="http://wiki/img/diagram.png" alt="Diagram">'
            '<img src="cid:chart@wiki" alt="Chart"></body></html>')
    message.attach(MIMEText(html, "html", "utf-8"))
    one = MIMEImage(PNG, "png"); one["Content-Location"] = "http://wiki/img/diagram.png"; message.attach(one)
    two = MIMEImage(PNG, "png"); two["Content-ID"] = "<chart@wiki>"; message.attach(two)
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "page.mht")
        with open(path, "wb") as f:
            f.write(message.as_bytes())
        assets = os.path.join(root, "assets", "page")
        doc = find(path).extract(path, STYLE, assets_dir=assets)
        from oto.intake.extractors.mht import render
        text = render(doc, STYLE)
        assert doc.title == "Wiki page" and doc.extra["n_parts"] >= 2
        assert "A paragraph." in text
        assert "![Diagram](assets/page/image-01.png)" in text and "![Chart](assets/page/image-02.png)" in text
        assert os.path.exists(os.path.join(assets, "image-02.png"))


def test_legacy_office_reports_libreoffice_as_the_missing_dependency(monkeypatch):
    from oto.intake.extractors import legacy

    monkeypatch.setattr(legacy, "soffice", lambda: None)
    extractor = find("old.doc")
    assert extractor.name == "legacy"
    assert not extractor.available()
    assert "LibreOffice" in extractor.missing()[0]


@pytest.mark.skipif(__import__("oto.intake.extractors.legacy", fromlist=["soffice"]).soffice() is None,
                    reason="LibreOffice not installed")
def test_legacy_doc_converts_and_cites_the_original():
    from oto.intake.extractors import legacy
    with tempfile.TemporaryDirectory() as root:
        # Make a .doc with LibreOffice itself, then read it back through the extractor.
        src = os.path.join(root, "memo.txt")
        with open(src, "w") as f:
            f.write("A legacy memo.\n")
        import subprocess
        subprocess.run([legacy.soffice(), "--headless", "--convert-to", "doc", "--outdir", root, src],
                       capture_output=True, timeout=300)
        path = os.path.join(root, "memo.doc")
        doc = find(path).extract(path, STYLE)
        assert doc.source_name == "memo.doc" and "converted from .doc" in doc.media_type
        assert "A legacy memo." in legacy.render(doc, STYLE)


def test_ingest_run_handles_a_web_page(tmp_path):
    from oto.cli import main
    from oto.intake import pipeline
    from oto.project import Project
    from oto.scaffold import init

    root = str(tmp_path / "p")
    init(root, name="Web")
    project = Project.standard(root)
    _write_page(project.layout.inbox)
    result = pipeline.ingest(project)
    assert result["written"] == ["handbook"]
    corpus = os.path.join(project.layout.corpus, "handbook.md")
    assert os.path.exists(corpus) and os.path.exists(os.path.join(project.layout.corpus, "assets", "handbook", "image-01.png"))
    assert main(["figures", "--project", root]) == 0
