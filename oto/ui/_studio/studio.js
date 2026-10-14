/* The studio: what every view of a product includes, after ../_studio/data.js.
 *
 *   Studio.link(id, text)  a link to the page that shows the thing, or the text alone
 *   Studio.label(id)       the thing's label in plain words ("" when unknown; never its id)
 *   Studio.open(element)   fills an element with what is still open on this page
 *   Studio.page(path)      a page's address: "<name>/", or "<name>/index.html" when the site is opened from disk
 *
 * On load it draws the studio's navigation at the top of the page (unless <body data-studio="bare">),
 * fills #studio-open when the page has one, and highlights the thing a link pointed to (#<id>) once
 * the page has drawn it. A page that draws later (after a fetch) calls Studio.focus() when it is done.
 */
(function () {
  "use strict";
  var D = window.__STUDIO__ || null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c];
    });
  }

  // the view this page is: the folder it is served from
  function here() {
    var parts = location.pathname.split("/").filter(Boolean);
    if (parts.length && /\.[a-z0-9]+$/i.test(parts[parts.length - 1])) parts.pop();
    return parts.length ? decodeURIComponent(parts[parts.length - 1]) : "";
  }

  function pageOf(name) {
    var pages = (D && D.pages) || [];
    for (var i = 0; i < pages.length; i++) if (pages[i].name === name) return pages[i];
    return null;
  }

  var current = pageOf(here()) ? here() : "";
  // opened from disk (file://), a folder is a listing, not its index.html: name the file
  var fromDisk = location.protocol === "file:";
  function page(path) { return fromDisk && /\/$/.test(path) ? path + "index.html" : path; }
  // from a view's folder, the site's root is one level up; from the root, it is here
  var root = current ? "../" : "";

  function label(id) {
    var e = D && D.entities && D.entities[id];
    return e ? e.label : "";
  }

  function link(id, text) {
    var e = D && D.entities && D.entities[id];
    var shown = text || (e && e.label) || "";
    if (!e) return esc(shown);
    var href = (e.view === current ? "" : page(root + e.view + "/")) + "#" + encodeURIComponent(id);
    return '<a class="studio-link" href="' + esc(href) + '">' + esc(shown) + "</a>";
  }

  function bar() {
    if (!D || !D.pages || !D.pages.length) return null;
    var name = (D.project && D.project.name) || "The product";
    var links = [];
    var ordered = [];
    if (D.portal) ordered.push(pageOf(D.portal));
    (D.places || []).forEach(function (place) {
      place.pages.forEach(function (n) { var p = pageOf(n); if (p) ordered.push(p); });
    });
    ordered.forEach(function (p) {
      if (!p) return;
      var cls = p.place === "technical" ? ' class="studio-technical"' : "";
      var curr = p.name === current ? ' aria-current="page"' : "";
      links.push('<a href="' + esc(page(root + p.path)) + '"' + cls + curr + ' title="' + esc(placeLabel(p.place)) + '">' +
                 esc(p.title) + "</a>");
    });
    var nav = document.createElement("header");
    nav.className = "studio-bar";
    nav.innerHTML = '<div class="studio-bar-inner"><a class="studio-home" href="' + esc(page(root || "./")) + '">' + esc(name) +
                    '</a><nav class="studio-nav" aria-label="Pages">' + links.join("") + "</nav></div>";
    return nav;
  }

  function placeLabel(id) {
    var places = (D && D.places) || [];
    for (var i = 0; i < places.length; i++) if (places[i].id === id) return places[i].label;
    return "";
  }

  function open(element, view) {
    if (!element) return;
    var entries = (D && D.open && D.open[view || current]) || null;
    if (entries === null) { element.innerHTML = ""; return; }
    var items = [];
    entries.forEach(function (entry) {
      entry.items.forEach(function (item) {
        var gaps = (item.gaps || []).join("; ");
        var what = item.label ? "<strong>" + esc(item.label) + "</strong>" + (gaps ? ": " + esc(gaps) : "") : esc(gaps);
        var who = entry.who ? ' <span class="studio-who">(' + esc(entry.who) + " can answer)</span>" : "";
        items.push("<li>" + what + who + "</li>");
      });
    });
    element.classList.add("studio-open");
    element.innerHTML = "<h2>Still open</h2>" +
      (items.length ? "<ul>" + items.join("") + "</ul>" : '<p class="studio-none">Nothing is open on this page.</p>');
  }

  function focus() {
    var id = decodeURIComponent((location.hash || "").slice(1));
    if (!id) return;
    var target = document.getElementById(id);
    if (!target) return;
    target.scrollIntoView({block: "center"});
    target.classList.add("studio-focus");
    setTimeout(function () { target.classList.remove("studio-focus"); }, 2500);
  }

  function ready(fn) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
    else fn();
  }

  ready(function () {
    if (document.body.getAttribute("data-studio") !== "bare") {
      var nav = bar();
      if (nav) document.body.insertBefore(nav, document.body.firstChild);
    }
    open(document.getElementById("studio-open"));
    // after the page's own code has drawn what a link may point to
    setTimeout(focus, 0);
  });
  window.addEventListener("hashchange", focus);

  window.Studio = {data: D, link: link, label: label, open: open, focus: focus, ready: ready, here: current, esc: esc, page: page};
})();
