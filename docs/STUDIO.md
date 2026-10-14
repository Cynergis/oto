# The studio: a product's pages, from the packs it uses

A product is assembled from packs, and every pack may ship a **view** of its part: a page, read from
the knowledge base, that shows people what that part is. The **studio** is those views side by side:

- **One front page**, from the product type's pack.
- **Every other page in the order a reader needs it:** what the product is, what it deals with, how
  it is designed, where the data comes from, how people work with it, where it runs, how it is
  built.
- **The same look and navigation** on every page.
- **Links between pages:** a requirement opens on the page that shows requirements, a component on
  the page that shows components.
- **What is still open** on every page.

`oto serve --http` serves the studio, and `oto build --target site` writes it as static pages, which
is what gets published. Nothing names a pack: the studio is what the project's views declare.

## A view joins the studio

A view is a folder under the pack's `views/`, with an `app.json` and an `index.html`; the project
installs it when it declares the pack. Five fields place it in the studio:

```json
{
  "name": "where",
  "title": "Where it runs",
  "place": "runs",
  "shows": ["Environment", "Component"],
  "open": ["PL"],
  "summary": "Where each part of the product runs, and what is still missing to deploy it.",
  "entry": "index.html",
  "data": [{"file": "data.js", "format": "js-globals",
            "globals": {"__WHERE__": {"$nodes": "Component", "$sort": "label",
                                      "$map": {"id": "$id", "name": "$label", "about": "$summary"}}}}]
}
```

| Field | What it says |
|---|---|
| `title` | The page's name in plain words: what a reader sees in the navigation. |
| `place` | Where it belongs: `front`, `product`, `domain`, `design`, `data`, `people`, `runs`, `build`, `tools`, `other` or `technical`. |
| `shows` | The classes whose things this page can open: a link to one of them lands here, at `#<id>`. The first page in reading order that shows a class gets its links. |
| `open` | The competency questions, by id (`SA17`) or by prefix (`PL`), whose gaps belong on this page. |
| `portal` | `true` for the product's front page. The product type's pack provides it; the home page opens it. |
| `summary` | One plain sentence: what a reader finds there. |

## The page includes the kit

```html
<link rel="stylesheet" href="../_studio/studio.css">
<script src="../_studio/data.js"></script>
<script src="../_studio/studio.js"></script>
<script src="data.js"></script>
```

The kit draws the navigation at the top of the page, and gives the page three things:

- `Studio.link(id, text)`: a link to the page that shows the thing, or the text alone when no page
  does. Never write an id where a reader sees it; use the thing's label.
- `Studio.ready(fn)`: run `fn` once the page is loaded.
- `Studio.page(path)`: a page's address for a link the page builds itself (`"../reports/"`): it names
  `index.html` when the site is opened from disk, where a folder would open as a listing.
- `<div id="studio-open"></div>`: filled with what is still open on this page, each gap in words with
  who can answer it. An element per thing with `id="<the thing's id>"` lets a link highlight it.

Use the kit's classes (`studio-page`, `studio-lead`, `studio-card`, `studio-muted`) so every page reads
as one site, in light and dark, on a phone and on paper.

## Writing a page

- **Plain language.** Labels and sentences, never ids, class or field names, codes or progress
  meters. The explorer (listed last, as technical) is where the technical detail lives.
- **What is recorded, and what is not.** A topic with nothing recorded says so in one line, or does
  not appear; "Still open" says what is missing and who can answer it.
- **Its own part only.** A page shows its pack's part and links to the others. A bridge (a pack that
  connects two others) adds links between their pages, not a page of its own.
