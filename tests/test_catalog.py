# -*- coding: utf-8 -*-
"""The catalog: a static site from a registry checkout, one page per pack with its sample
drawn by the explorer, one per ontology, grouped by domain on the index."""
import json
import os
import shutil
import subprocess
import tempfile

import pytest

from oto import catalog
from oto.cli import main
from oto.model import ontologies, packs

from test_registry import _empty_registry, _git


@pytest.fixture
def home(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        monkeypatch.setenv(packs.USER_DIR_ENV, os.path.join(root, "packs"))
        monkeypatch.setenv(ontologies.USER_DIR_ENV, os.path.join(root, "ontologies"))
        monkeypatch.setenv("OTO_REGISTRIES", os.path.join(root, "registries.json"))
        yield root


def test_the_catalog_has_a_page_per_pack_and_per_ontology_and_draws_the_sample(home, capsys):
    bare = _empty_registry(home, name="market")
    assert main(["ontology", "publish", "--from", "oto-core", "--to", bare, "--registry-name", "market"]) == 0
    assert main(["ontology", "publish", "--from", "software-architecture", "--to", bare]) == 0
    assert main(["pack", "new", "arch", "--ontology", "software-architecture", "--maintainer", "Cynergis"]) == 0
    assert main(["pack", "publish", "--from", "arch", "--to", bare, "--note", "first"]) == 0
    work = os.path.join(home, "checkout")
    _git(["clone", "--quiet", bare, work], home)
    # the registry scaffold wrote both workflows and ignores the generated site
    assert os.path.exists(os.path.join(work, ".github", "workflows", "oto-registry-site.yml"))
    assert "site/" in open(os.path.join(work, ".gitignore"), encoding="utf-8").read()
    assert "upload-pages-artifact" in open(os.path.join(work, ".github", "workflows", "oto-registry-site.yml"), encoding="utf-8").read()

    out, report = catalog.write(work)
    assert out == os.path.join(work, "site") and report == {"packs": 1, "ontologies": 2, "drawn": 1, "problems": []}
    index = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    assert 'data-domain="software"' in index and 'href="packs/arch/index.html"' in index and 'href="ontologies/oto-core/index.html"' in index
    assert "1 packs, 2 ontologies" in index and "/plugin install &lt;pack&gt;@market" in index
    assert "/plugin marketplace add %s" % bare in index, "the checkout's remote is what a person adds"
    assert '<button class="f d" data-domain="software"' in index and 'id="q"' in index, "a domain filter and the search box"
    assert index.index('data-domain="software" data-text') < index.index('data-domain="" data-text'), "named domains first"
    page = open(os.path.join(out, "packs", "arch", "index.html"), encoding="utf-8").read()
    for expected in ("<h1>arch", "/plugin install arch@market", "oto init --name", "${CLAUDE_PLUGIN_ROOT}",
                     "<code>software-architecture@10</code>", "<strong>System</strong>", "which product provides each",
                     "<code>depends_on</code>", "The sample, drawn", 'src="explorer/index.html"', "action.check-repository",
                     "<code>/arch:start</code>", "The guide", "<strong>@1</strong>", "by Cynergis"):
        assert expected in page, expected
    assert os.path.exists(os.path.join(out, "packs", "arch", "explorer", "index.html"))
    data = json.load(open(os.path.join(out, "packs", "arch", "explorer", "data.json"), encoding="utf-8"))
    assert data["nodes"] and data["edges"] and "System" in data["vocabulary"]["classes"]
    onto = open(os.path.join(out, "ontologies", "software-architecture", "index.html"), encoding="utf-8").read()
    assert "<h1>software-architecture" in onto and "oto init --ontology software-architecture" in onto and "<strong>Component</strong>" in onto
    assert os.path.exists(os.path.join(out, ".nojekyll"))
    listing = json.load(open(os.path.join(out, "catalog.json"), encoding="utf-8"))
    assert listing["registry"] == "market" and [p["name"] for p in listing["packs"]] == ["arch"]
    # the command, from inside the checkout and with --out
    assert catalog.registry_address(work, "https://github.com/Cynergis/oto-registry") == ("Cynergis/oto-registry", "https://github.com/Cynergis/oto-registry")
    assert catalog.registry_address(work, "git@github.com:Cynergis/oto-registry.git") == ("Cynergis/oto-registry", "https://github.com/Cynergis/oto-registry")
    assert catalog.registry_address(home) == ("&lt;this registry&gt;", "&lt;this registry&gt;"), "no remote, a placeholder"
    # a credential in the remote never reaches a page: not from --url, not from the checkout
    assert catalog.registry_address(work, "https://x-access-token:ghp_secret@github.com/Cynergis/oto-registry") == ("Cynergis/oto-registry", "https://github.com/Cynergis/oto-registry")
    assert catalog.scrub("https://user:pass@example.com/team/reg.git") == "https://example.com/team/reg.git"
    subprocess.run(["git", "config", "url.https://x-access-token:ghp_secret@github.com/.insteadOf", "https://github.com/"], cwd=work, check=True)
    subprocess.run(["git", "remote", "set-url", "origin", "https://github.com/Cynergis/oto-registry"], cwd=work, check=True)
    assert catalog.registry_address(work) == ("Cynergis/oto-registry", "https://github.com/Cynergis/oto-registry"), "the stored value, not the rewritten one"
    out2, _ = catalog.write(work, out=os.path.join(home, "scrubbed"))
    for dirpath, _dirs, files in os.walk(out2):
        for name in files:
            if name.endswith((".html", ".json")):
                assert "ghp_secret" not in open(os.path.join(dirpath, name), encoding="utf-8").read(), name
    subprocess.run(["git", "remote", "set-url", "origin", bare], cwd=work, check=True)
    assert main(["registry", "site", work, "--out", os.path.join(home, "elsewhere"), "--url", "https://github.com/Cynergis/oto-registry"]) == 0
    assert "/plugin marketplace add Cynergis/oto-registry" in open(os.path.join(home, "elsewhere", "index.html"), encoding="utf-8").read()
    assert "catalog: 1 pack(s) (1 drawn), 2 ontologies" in capsys.readouterr().out
    assert os.path.exists(os.path.join(home, "elsewhere", "packs", "arch", "index.html"))
    # a broken pack is reported on the page and in the exit code, the rest still generated
    shutil.rmtree(os.path.join(work, "packs", "arch", "ontology"))
    assert main(["registry", "site", work]) == 1
    out_text = capsys.readouterr().out
    assert "could not be drawn" in out_text


def test_the_small_markdown_renderer_covers_what_the_engine_writes():
    text = "---\nname: x\n---\n# Title\n\nA line with `code` and **bold**.\n\n- one\n- two\n  continued\n\n```bash\noto init\n```\n"
    fields, body = catalog._frontmatter(text)
    assert fields == {"name": "x"} and body.startswith("# Title")
    out = catalog._markdown(body)
    assert "<h2>Title</h2>" in out and "<code>code</code>" in out and "<strong>bold</strong>" in out
    assert "<li>two continued</li>" in out and "<pre><code>oto init</code></pre>" in out
    assert "<script>" not in catalog._markdown("<script>alert(1)</script>")


def test_the_embedded_explorer_can_expand_to_the_parent_window():
    """The explorer inside the catalog's frame tells the parent page when it expands, and the
    page grows the frame to the full window; the bundle carries the message and the page the
    listener."""
    bundle = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "oto", "ui", "explorer", "explorer.js"), encoding="utf-8").read()
    assert 'oto:"explorer"' in bundle and "postMessage" in bundle
    page = catalog._pack_page.__code__.co_consts
    assert any(isinstance(c, str) and "addEventListener('message'" in c and "classList.toggle('expanded'" in c for c in page)
    assert "iframe.expanded{position:fixed;inset:0" in catalog.STYLE


def test_the_registry_can_brand_its_catalog(home):
    """A `site.json` beside the index names the site, recolours it, adds a logo and links, and
    writes the CNAME a custom domain needs; without one the registry's own name and summary serve."""
    bare = _empty_registry(home, name="market")
    assert main(["ontology", "publish", "--from", "oto-core", "--to", bare, "--registry-name", "market"]) == 0
    work = os.path.join(home, "checkout")
    _git(["clone", "--quiet", bare, work], home)
    plain = catalog.brand(work, {"name": "market", "summary": "Market ontologies."})
    assert plain["title"] == "market" and plain["tagline"] == "Market ontologies." and plain["colors"] == {} and plain["domain"] is None
    with open(os.path.join(work, "mark.svg"), "w", encoding="utf-8") as f:
        f.write("<svg xmlns='http://www.w3.org/2000/svg'/>")
    with open(os.path.join(work, catalog.BRAND_FILE), "w", encoding="utf-8") as f:
        json.dump({"title": "The Market catalog", "tagline": "Packs for the market.", "logo": "mark.svg", "domain": "catalog.example.com",
                   "colors": {"accent": "#3B3BD6", "paper": "#F7F2EA", "bad key!": "#000", "accent-2": "not a colour"},
                   "links": [{"label": "Home", "url": "https://example.com"}, {"label": "Go", "url": "https://example.com/go", "button": True}, {"nope": 1}]}, f)
    out, report = catalog.write(work, url="https://github.com/Example/market")
    assert report["ontologies"] == 1
    index = open(os.path.join(out, "index.html"), encoding="utf-8").read()
    assert "<h1>The Market catalog</h1>" in index and "Packs for the market." in index
    assert "--accent:#3B3BD6;--paper:#F7F2EA;" in index and "bad key" not in index and "not a colour" not in index, "only well-formed tokens reach the page"
    assert '<img src="mark.svg" alt="">' in index and os.path.exists(os.path.join(out, "mark.svg"))
    assert '<a href="https://example.com">Home</a>' in index and '<a class="btn" href="https://example.com/go">Go</a>' in index
    assert 'id="q"' in index and 'data-kind="ontology"' in index and "/plugin install &lt;pack&gt;@market" in index, "the search, the cards and the install line"
    assert open(os.path.join(out, "CNAME"), encoding="utf-8").read() == "catalog.example.com\n"
    onto = open(os.path.join(out, "ontologies", "oto-core", "index.html"), encoding="utf-8").read()
    assert '<img src="../../mark.svg" alt="">' in onto and "--accent:#3B3BD6" in onto, "every page carries the brand"
