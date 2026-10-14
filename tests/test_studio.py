"""The studio: a product's pages assembled from the views of the packs it uses, each saying where it
belongs, what it shows and what is still open on it."""
import json
import os
import tempfile

from oto.apps import manifest as apps
from oto.apps import studio


def _view(base, name, **declared):
    directory = os.path.join(base, name)
    os.makedirs(directory)
    with open(os.path.join(directory, "app.json"), "w", encoding="utf-8") as f:
        json.dump(dict({"name": name, "summary": "", "entry": "index.html"}, **declared), f)
    with open(os.path.join(directory, "index.html"), "w", encoding="utf-8") as f:
        f.write("<title>%s</title>" % name)
    return name, directory


PAYLOAD = {
    "project": {"name": "Fund reports", "slug": "funds"},
    "vocabulary": {"classes": {"Requirement": {}, "Component": {}, "Environment": {}}},
    "nodes": [{"id": "requirement.r1", "type": "Requirement", "label": "Produce the profile monthly", "status": "current"},
              {"id": "component.c1", "type": "Component", "label": "Render job", "status": "current"},
              {"id": "component.old", "type": "Component", "label": "Old job", "status": "retired"},
              {"id": "environment.prod", "type": "Environment", "label": "Production", "status": "current"}],
}


def test_a_view_declares_its_place_and_wrong_declarations_are_refused():
    with tempfile.TemporaryDirectory() as base:
        _name, good = _view(base, "spec", title="What it must do", place="product", shows=["Requirement"], open=["PR"])
        assert apps.problems(good) == []
        for bad, words in ((dict(place="somewhere"), "`place` 'somewhere' is not one of"),
                           (dict(title=""), None), (dict(title=3), "`title` must be"),
                           (dict(shows="Requirement"), "`shows` must be a list"),
                           (dict(open=[1]), "`open` must be a list"), (dict(portal="yes"), "`portal` must be true or false")):
            _n, directory = _view(base, "v%d" % len(os.listdir(base)), **bad)
            found = apps.problems(directory)
            assert (words is None and found == []) or any(words in p for p in found), (bad, found)


def test_the_pages_come_in_reading_order_with_the_front_page_first_and_the_explorer_last():
    with tempfile.TemporaryDirectory() as base:
        views = [_view(base, "runs", title="Where it runs", place="runs", shows=["Environment"]),
                 _view(base, "spec", title="What it must do", place="product", shows=["Requirement"]),
                 _view(base, "front", title="Overview", portal=True),
                 _view(base, "design", title="How it is designed", place="design", shows=["Component", "Requirement"]),
                 ("explorer", os.path.join(apps.UI_DIR, "explorer")),
                 _view(base, "loose")]
        data = studio.data(views, PAYLOAD)
        assert [p["name"] for p in data["pages"]] == ["front", "spec", "design", "runs", "loose", "explorer"]
        assert data["portal"] == "front" and data["project"]["name"] == "Fund reports"
        places = {p["id"]: p["pages"] for p in data["places"]}
        assert places["front"] == [] and places["product"] == ["spec"] and places["other"] == ["loose"]
        assert places["technical"] == ["explorer"]
        assert data["entities"]["requirement.r1"] == {"label": "Produce the profile monthly", "view": "spec"}, \
            "a thing opens on the first page, in reading order, that shows it"
        assert data["entities"]["component.c1"]["view"] == "design" and "component.old" not in data["entities"]
        loose = next(p for p in data["pages"] if p["name"] == "loose")
        assert loose["title"] == "Loose" and loose["place"] == "other"


def test_still_open_puts_each_unanswered_question_on_its_page_in_words():
    rows = [{"id": "PL6", "status": "unanswered", "who": "a builder", "question": "Which pipeline deploys $COMPONENT?",
             "gaps": [], "unanswered": [{"node": "component.c1", "label": "Render job", "status": "unanswered",
                                         "gaps": ["no pipeline deploys it"]}]},
            {"id": "PL1", "status": "answered", "who": "an architect", "question": "Which accounts?", "gaps": [], "unanswered": []},
            {"id": "PL11", "status": "violated", "who": "a tester", "gaps": [],
             "question": "Which components that run in $ENVIRONMENT cannot be deployed there yet?",
             "unanswered": [{"node": "environment.prod", "label": "Production", "status": "violated", "gaps": []}]},
            {"id": "PLX", "status": "unanswered", "who": "", "question": "Not ours", "gaps": ["x"], "unanswered": []},
            {"id": "SA17", "status": "violated", "who": "an architect", "unanswered": [], "gaps": [],
             "question": "Which requirements of the product does nothing in the design satisfy yet?"}]
    with tempfile.TemporaryDirectory() as base:
        views = [_view(base, "runs", title="Where it runs", place="runs", open=["PL"]),
                 _view(base, "design", title="How it is designed", place="design", open=["SA17"]),
                 _view(base, "spec", title="What it must do", place="product")]
        data = studio.data(views, PAYLOAD, rows)
        assert data["open"]["runs"] == [
            {"who": "a builder", "items": [{"label": "Render job", "gaps": ["no pipeline deploys it"]}]},
            {"who": "a tester", "items": [{"label": None, "gaps": ["Which components that run in Production cannot be deployed there yet?"]}]}], \
            "answered questions are not open, a question with no gap in words is asked about its thing, and PLX is not a PL question"
        assert data["open"]["design"][0]["items"][0]["gaps"] == ["Which requirements of the product does nothing in the design satisfy yet?"]
        assert "spec" not in data["open"], "a page that names no questions has no open box"
        text = studio.script(data)
        assert text.startswith("window.__STUDIO__ = ") and json.loads(text.split(" = ", 1)[1].rstrip().rstrip(";"))["portal"] is None


def test_the_kit_is_shipped_and_names_no_pack():
    for name in ("studio.css", "studio.js"):
        text = open(os.path.join(studio.KIT_DIR, name), encoding="utf-8").read()
        for pack in ("medallion", "product-report", "ddd", "platform"):
            assert pack not in text, (name, pack)
    js = open(os.path.join(studio.KIT_DIR, "studio.js"), encoding="utf-8").read()
    assert "Still open" in js and "window.Studio" in js
    home = open(os.path.join(apps.HOME_DIR, "index.html"), encoding="utf-8").read()
    assert "D.portal" in home and "_studio/data.js" in home
