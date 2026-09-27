/* The generic reader: the graph as pages.
 *
 * Loads data.json (the graph payload) and renders it as pages behind hash routes:
 *   #/                    home: the map
 *   #/type/<Class>        a section: one class as a table
 *   #/entity/<id>         the card: provenance, relations, derived facts, history, evidence
 *   #/doc/<slug>          a document: its passage and what cites it
 *   #/search?q=<words>    entities and passages
 *   #/findings            policy findings, and each rule with what it derived
 *   #/changes             the ledger
 *
 * The pure functions (indexing, searching, the text of each page) are exported for tests under
 * Node; the DOM work is confined to `boot` and `render`. No framework, no network beyond the
 * engine: in live mode /api/changes is polled and a changed build reloads the data.
 */
(function (root) {
  "use strict";

  // ---------- indexing ----------
  function index(payload) {
    var byId = {}, byType = {}, out = {}, inn = {}, byDoc = {}, docsByPath = {};
    (payload.nodes || []).forEach(function (n) {
      byId[n.id] = n;
      (byType[n.type] = byType[n.type] || []).push(n);
      var cites = {};
      (n.sources || []).forEach(function (s) { cites[s] = true; });
      if (n.source_doc) cites[n.source_doc] = true;
      (n.evidence || []).forEach(function (e) { if (e && e.doc) cites[e.doc] = true; });
      Object.keys(cites).forEach(function (d) { (byDoc[d] = byDoc[d] || []).push(n); });
    });
    (payload.edges || []).forEach(function (e) {
      (out[e.from] = out[e.from] || []).push(e);
      (inn[e.to] = inn[e.to] || []).push(e);
    });
    (payload.passages || []).forEach(function (p) { docsByPath[p.path] = p; });
    Object.keys(byType).forEach(function (t) { byType[t].sort(function (a, b) { return a.label.localeCompare(b.label); }); });
    return {payload: payload, byId: byId, byType: byType, out: out, inn: inn, byDoc: byDoc, docsByPath: docsByPath,
            classes: Object.keys(byType).sort()};
  }

  function docSlug(path) { return path.replace(/^documents\//, "").replace(/\.md$/, ""); }

  function passageFor(ix, slug) {
    return ix.docsByPath["documents/" + slug + ".md"] || ix.docsByPath[slug + ".md"] || ix.docsByPath[slug] || null;
  }

  // ---------- searching ----------
  function search(ix, query, limit) {
    var q = (query || "").trim().toLowerCase();
    if (!q) return {entities: [], passages: []};
    var words = q.split(/\s+/);
    function score(text) {
      var t = (text || "").toLowerCase(), s = 0;
      for (var i = 0; i < words.length; i++) if (t.indexOf(words[i]) >= 0) s += 1;
      return s === words.length ? s : 0;
    }
    var entities = [];
    (ix.payload.nodes || []).forEach(function (n) {
      var s = score(n.label) * 3 + score((n.aliases || []).join(" ")) * 2 + score(n.summary);
      if (s) entities.push({node: n, score: s + (n.status === "current" ? 1 : 0)});
    });
    entities.sort(function (a, b) { return b.score - a.score || a.node.label.localeCompare(b.node.label); });
    var passages = [];
    (ix.payload.passages || []).forEach(function (p) {
      var s = score(p.title) * 2 + score(p.body);
      if (s) passages.push({passage: p, score: s, snippet: snippet(p.body, words[0])});
    });
    passages.sort(function (a, b) { return b.score - a.score || a.passage.path.localeCompare(b.passage.path); });
    limit = limit || 20;
    return {entities: entities.slice(0, limit), passages: passages.slice(0, limit)};
  }

  function snippet(body, word) {
    var t = body || "", i = t.toLowerCase().indexOf(word);
    if (i < 0) return t.slice(0, 160);
    var start = Math.max(0, i - 70), end = Math.min(t.length, i + 90);
    return (start > 0 ? "…" : "") + t.slice(start, end).replace(/\s+/g, " ") + (end < t.length ? "…" : "");
  }

  // ---------- routing ----------
  function parseRoute(hash) {
    var h = (hash || "#/").replace(/^#/, "");
    var q = "", i = h.indexOf("?");
    if (i >= 0) { q = h.slice(i + 1); h = h.slice(0, i); }
    var parts = h.split("/").filter(Boolean).map(decodeURIComponent);
    var params = {};
    q.split("&").forEach(function (kv) { if (!kv) return; var p = kv.split("="); params[decodeURIComponent(p[0])] = decodeURIComponent((p[1] || "").replace(/\+/g, " ")); });
    return {page: parts[0] || "home", arg: parts.slice(1).join("/"), params: params};
  }

  // ---------- helpers ----------
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; }); }
  function link(href, text, cls) { return '<a href="' + esc(href) + '"' + (cls ? ' class="' + cls + '"' : "") + ">" + esc(text) + "</a>"; }
  function entityLink(ix, id) { var n = ix.byId[id]; return n ? link("#/entity/" + encodeURIComponent(id), n.label) : "<code>" + esc(id) + "</code>"; }
  function docLink(slug) { return link("#/doc/" + encodeURIComponent(slug), slug); }
  function badge(text, cls) { return '<span class="badge ' + (cls || "") + '">' + esc(text) + "</span>"; }
  function fmt(v) {
    if (v == null || v === "") return "";
    if (Array.isArray(v)) return v.map(fmt).join(", ");
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  }
  function prov(n) {
    var bits = ["status=" + (n.status || "current")];
    ["as_of", "valid_from", "valid_to", "source_doc"].forEach(function (k) { if (n[k]) bits.push(k + "=" + n[k]); });
    return '<div class="prov">' + bits.map(function (b) { return "<span>" + esc(b) + "</span>"; }).join("") + "</div>";
  }

  // ---------- pages (return HTML strings) ----------
  function pageHome(ix) {
    var p = ix.payload, c = p.counts || {};
    var h = ['<h1>' + esc(p.project && p.project.name || "The graph") + '</h1>'];
    h.push('<div class="grid">' +
      tile(c.nodes || (p.nodes || []).length, "entities") + tile(c.edges || (p.edges || []).length, "relationships") +
      tile(c.derived_edges || 0, "derived by rules") + tile((p.findings || []).length, "policy findings") +
      tile(c.superseded || 0, "superseded facts") + tile((p.documents || []).length, "documents") + "</div>");
    if (p.frontier) h.push('<p class="muted">Most recent fact recorded: ' + esc(p.frontier) + "</p>");
    var pend = p.pending || [];
    if (pend.length) {
      var byStation = {};
      pend.forEach(function (r) { var k = r.verdict === "refused" ? "refused" : r.station; byStation[k] = (byStation[k] || 0) + 1; });
      h.push('<div class="card"><h2>Pending ' + badge(pend.length + " not yet believed", "pending") + '</h2><p class="muted">Knowledge captured and not yet through the gates: ' +
        Object.keys(byStation).map(function (k) { return byStation[k] + " " + k; }).join(", ") + '. Each is listed on the page it would change.</p><ul class="plain">' +
        pend.slice(0, 12).map(function (r) { return "<li>" + badge(r.verdict === "refused" ? "refused" : r.station, "pending") + " " + (r.kind === "edge" ? esc(r.from) + " <code>" + esc(r.rel) + "</code> " + esc(r.to) : (r.id && ix.byId[r.id] ? entityLink(ix, r.id) : esc(r.label || r.id || r.source))) + ' <span class="mono muted">' + esc(r.verdict) + " · " + esc(r.source) + "</span>" + (r.reason ? '<div class="muted">' + esc(r.reason) + "</div>" : "") + "</li>"; }).join("") +
        (pend.length > 12 ? "<li class=\"muted\">… " + (pend.length - 12) + " more</li>" : "") + "</ul></div>");
    }
    if (p.stations) {
      var st = p.stations, names = Object.keys(st);
      if (names.some(function (k) { return st[k]; })) h.push('<p class="muted">Raw files: ' + names.map(function (k) { return k + " " + st[k]; }).join(" · ") + "</p>");
    }
    h.push('<div class="card"><h2>By class</h2><div class="tw"><table><thead><tr><th>Class</th><th>Current</th><th>First entries</th></tr></thead><tbody>' +
      ix.classes.map(function (t) {
        var rows = ix.byType[t].filter(function (n) { return n.status !== "superseded"; });
        return "<tr><td>" + link("#/type/" + encodeURIComponent(t), t) + '</td><td class="mono">' + rows.length + "</td><td>" +
          rows.slice(0, 3).map(function (n) { return entityLink(ix, n.id); }).join(", ") + (rows.length > 3 ? ", …" : "") + "</td></tr>";
      }).join("") + "</tbody></table></div></div>");
    var hubs = (p.nodes || []).filter(function (n) { return n.status !== "superseded"; }).sort(function (a, b) { return (b.degree || 0) - (a.degree || 0) || a.id.localeCompare(b.id); }).slice(0, 8);
    if (hubs.length) h.push('<div class="card"><h2>Most connected</h2><ul class="plain">' + hubs.map(function (n) {
      return "<li>" + entityLink(ix, n.id) + " " + badge(n.type, "type") + ' <span class="mono muted">' + (n.degree || 0) + "</span></li>"; }).join("") + "</ul></div>");
    var rels = Object.keys(c.by_relation || {}).sort(function (a, b) { return c.by_relation[b] - c.by_relation[a]; }).slice(0, 10);
    if (rels.length) h.push('<div class="card"><h2>By relation</h2><p>' + rels.map(function (r) { return "<code>" + esc(r) + "</code> " + c.by_relation[r]; }).join(" · ") + "</p></div>");
    var led = (p.ledger || []).slice(0, 5);
    h.push('<div class="card"><h2>Recent changes</h2>' + (led.length ? ledgerList(led) : '<p class="empty">Nothing recorded in the ledger yet.</p>') + '<p>' + link("#/changes", "All changes") + "</p></div>");
    return h.join("");
  }
  function tile(n, label) { return '<div class="tile"><div class="big">' + esc(n) + '</div><div class="label">' + esc(label) + "</div></div>"; }

  function pageType(ix, type) {
    var rows = ix.byType[type];
    if (!rows) return '<h1>' + esc(type) + '</h1><p class="empty">No entities of this class.</p>';
    var attrs = {};
    rows.forEach(function (n) { Object.keys(n.attributes || {}).forEach(function (k) { attrs[k] = (attrs[k] || 0) + 1; }); });
    var cols = Object.keys(attrs).sort(function (a, b) { return attrs[b] - attrs[a]; }).slice(0, 4);
    var h = ['<div class="crumb">' + link("#/", "Home") + " / " + esc(type) + "</div>", "<h1>" + esc(type) + ' <span class="muted">' + rows.length + "</span></h1>"];
    h.push('<div class="tw"><table><thead><tr><th>Entity</th>' + cols.map(function (c) { return "<th>" + esc(c) + "</th>"; }).join("") + "<th>Status</th><th>As of</th></tr></thead><tbody>" +
      rows.map(function (n) {
        return "<tr><td>" + entityLink(ix, n.id) + '<div class="muted" style="font-size:.85rem">' + esc(n.summary || "") + "</div></td>" +
          cols.map(function (c) { return "<td>" + esc(fmt((n.attributes || {})[c])) + "</td>"; }).join("") +
          "<td>" + (n.status === "current" ? '<span class="muted">current</span>' : badge(n.status, n.status)) + '</td><td class="mono">' + esc(n.as_of || "") + "</td></tr>";
      }).join("") + "</tbody></table></div>");
    return h.join("");
  }

  function pageEntity(ix, id) {
    var n = ix.byId[id];
    if (!n) return '<h1>Not in the graph</h1><p class="empty">No entity with id <code>' + esc(id) + "</code>.</p>";
    var h = ['<div class="crumb">' + link("#/", "Home") + " / " + link("#/type/" + encodeURIComponent(n.type), n.type) + "</div>"];
    h.push("<h1>" + esc(n.label) + " " + badge(n.type, "type") + (n.status !== "current" ? " " + badge(n.status, n.status) : "") + "</h1>");
    h.push(prov(n));
    if (n.status === "superseded" && n.superseded_by && ix.byId[n.superseded_by]) {
      h.push('<div class="card"><p>Superseded' + (n.valid_to ? " on " + esc(n.valid_to) : "") + ". Current: " + entityLink(ix, n.superseded_by) + "</p></div>");
    }
    if ((n.aliases || []).length) h.push('<p class="muted">aka ' + esc(n.aliases.join(", ")) + "</p>");
    if (n.summary) h.push("<p>" + esc(n.summary) + "</p>");
    var attrs = Object.keys(n.attributes || {}).filter(function (k) { var v = n.attributes[k]; return v !== null && v !== "" && !(Array.isArray(v) && !v.length); });
    var derivedAttrs = (ix.payload.derived_attributes || []).filter(function (d) { return d.node === id; });
    if (attrs.length || derivedAttrs.length) {
      h.push('<div class="card"><h2>Attributes</h2><dl>' + attrs.map(function (k) { return "<dt>" + esc(k) + "</dt><dd>" + esc(fmt(n.attributes[k])) + "</dd>"; }).join("") +
        derivedAttrs.map(function (d) { return "<dt>" + esc(d.name) + " " + badge("derived by " + d.derived_by, "derived") + "</dt><dd>" + esc(fmt(d.value)) + premises(ix, d.premises) + "</dd>"; }).join("") + "</dl></div>");
    }
    h.push(relations(ix, n, ix.out[id] || [], true));
    h.push(relations(ix, n, ix.inn[id] || [], false));
    var preds = (ix.payload.nodes || []).filter(function (m) { return m.superseded_by === id; });
    var sup = n.supersedes ? (Array.isArray(n.supersedes) ? n.supersedes : [n.supersedes]) : [];
    sup.forEach(function (s) { if (ix.byId[s] && !preds.some(function (m) { return m.id === s; })) preds.push(ix.byId[s]); });
    if (preds.length) h.push('<div class="card"><h2>History</h2><ul class="plain">' + preds.map(function (m) {
      return "<li>" + entityLink(ix, m.id) + ' <span class="mono muted">valid ' + esc(m.valid_from || "?") + " → " + esc(m.valid_to || "?") + "</span></li>"; }).join("") + "</ul></div>");
    var findings = (ix.payload.findings || []).filter(function (f) { return f.node === id; });
    if (findings.length) h.push('<div class="card"><h2>Policy findings</h2><ul class="plain">' + findings.map(function (f) {
      return "<li>" + badge(f.severity, f.severity) + " <code>" + esc(f.rule) + "</code> " + esc(f.message) + "</li>"; }).join("") + "</ul></div>");
    var src = n.sources || [];
    if (src.length || (n.evidence || []).length) {
      h.push('<div class="card"><h2>Sources</h2>' + (src.length ? "<p>" + src.map(function (s) { return docLink(s); }).join(", ") + "</p>" : "") +
        (n.evidence || []).map(function (e) { return "<blockquote>" + (e.quote ? esc(e.quote) : '<span class="muted">no quote</span>') + '<div class="mono muted">' + docLink(e.doc || "?") + (e.where ? " · " + esc(e.where) : "") + "</div></blockquote>"; }).join("") + "</div>");
    }
    var pending = (ix.payload.pending || []).filter(function (p) { return p.id === id || p.from === id || p.to === id || p.supersedes === id; });
    if (pending.length) h.push('<div class="card"><h2>Pending ' + badge("not yet believed", "pending") + "</h2><ul class=\"plain\">" + pending.map(function (p) {
      return "<li>" + badge(p.station || "pending", "pending") + " " + esc(p.label || (p.from + " -" + p.rel + "-> " + p.to)) + "</li>"; }).join("") + "</ul></div>");
    return h.join("");
  }

  function relations(ix, n, edges, outgoing) {
    var live = edges.filter(function (e) { if (e.status === "superseded") return false; var o = ix.byId[outgoing ? e.to : e.from]; return !o || o.status !== "superseded"; });
    if (!live.length) return "";
    var byRel = {};
    live.forEach(function (e) { (byRel[e.rel] = byRel[e.rel] || []).push(e); });
    return '<div class="card"><h2>' + (outgoing ? "Relationships" : "Referenced by") + "</h2>" + Object.keys(byRel).sort().map(function (r) {
      return '<div class="rel"><span class="name">' + esc(outgoing ? r : "← " + r) + "</span><span>" + byRel[r].map(function (e) {
        var other = outgoing ? e.to : e.from;
        return entityLink(ix, other) + (e.status === "derived" ? " " + badge("derived by " + e.derived_by, "derived") + premises(ix, e.premises) : "");
      }).join(", ") + "</span></div>";
    }).join("") + "</div>";
  }

  function premises(ix, list) {
    if (!list || !list.length) return "";
    return "<details><summary>rests on " + list.length + "</summary><ul class=\"plain\">" + list.map(function (p) {
      var m = /^(.+?) -(.+?)-> (.+)$/.exec(p);
      if (m) return "<li>" + entityLink(ix, m[1]) + " <code>" + esc(m[2]) + "</code> " + entityLink(ix, m[3]) + "</li>";
      return "<li>" + entityLink(ix, p) + "</li>";
    }).join("") + "</ul></details>";
  }

  function pageDoc(ix, slug) {
    var passage = passageFor(ix, slug), cites = (ix.byDoc[slug] || []).slice();
    var docNode = (ix.payload.documents || []).filter(function (d) { return d.id === slug || d.id === "doc." + slug; })[0];
    if (docNode) {
      // entities that point at the document's own entity, by any relation, cite it too
      (ix.inn[docNode.id] || []).forEach(function (e) { var n = ix.byId[e.from]; if (n && cites.indexOf(n) < 0) cites.push(n); });
    }
    var title = passage ? passage.title : (docNode ? docNode.label : slug);
    var h = ['<div class="crumb">' + link("#/", "Home") + " / " + link("#/docs", "documents") + "</div>", "<h1>" + esc(title) + "</h1>"];
    if (docNode) h.push('<p class="muted">Document entity: ' + entityLink(ix, docNode.id) + (docNode.valid_from || docNode.as_of ? " · " + esc(docNode.valid_from || docNode.as_of) : "") + "</p>");
    if (passage) h.push('<div class="passage">' + esc(passage.body) + "</div>");
    else h.push('<p class="empty">The corpus text of <code>' + esc(slug) + "</code> is not in this payload (passages were left out, or the document is not ingested).</p>");
    h.push('<div class="card"><h2>Cited by</h2>' + (cites.length ? '<ul class="plain">' + cites.map(function (n) { return "<li>" + entityLink(ix, n.id) + " " + badge(n.type, "type") + "</li>"; }).join("") + "</ul>" : '<p class="empty">No entity cites this document.</p>') + "</div>");
    return h.join("");
  }

  function pageDocs(ix) {
    var docs = (ix.payload.documents || []).slice();
    var h = ["<h1>Documents <span class=\"muted\">" + docs.length + "</span></h1>"];
    if (ix.payload.frontier) h.push('<p class="muted">Ingest frontier: ' + esc(ix.payload.frontier) + "</p>");
    h.push('<div class="tw"><table><thead><tr><th>Date</th><th>Document</th><th>Cited by</th></tr></thead><tbody>' + docs.map(function (d) {
      var slug = d.id.replace(/^doc\./, ""), dt = d.valid_from || (d.attributes || {}).date || d.as_of || "?";
      return '<tr><td class="mono">' + esc(dt) + "</td><td>" + link("#/doc/" + encodeURIComponent(slug), d.label) + '</td><td class="mono">' + ((ix.byDoc[slug] || []).length) + "</td></tr>";
    }).join("") + "</tbody></table></div>");
    var passages = Object.keys(ix.docsByPath).sort();
    if (passages.length) h.push('<div class="card"><h2>In the index</h2><ul class="plain">' + passages.map(function (p) { return "<li>" + link("#/doc/" + encodeURIComponent(docSlug(p)), p) + "</li>"; }).join("") + "</ul></div>");
    return h.join("");
  }

  function pageSearch(ix, q) {
    var r = search(ix, q);
    var h = ["<h1>Search <span class=\"muted\">" + esc(q) + "</span></h1>"];
    if (!q) return h.join("") + '<p class="empty">Type words above.</p>';
    h.push('<div class="card"><h2>Entities ' + '<span class="muted">' + r.entities.length + "</span></h2>" + (r.entities.length ? '<ul class="plain">' + r.entities.map(function (e) {
      return "<li>" + entityLink(ix, e.node.id) + " " + badge(e.node.type, "type") + (e.node.status !== "current" ? " " + badge(e.node.status, e.node.status) : "") + '<div class="muted" style="font-size:.85rem">' + esc(e.node.summary || "") + "</div></li>";
    }).join("") + "</ul>" : '<p class="empty">No entity matches.</p>') + "</div>");
    h.push('<div class="card"><h2>Passages ' + '<span class="muted">' + r.passages.length + "</span></h2>" + (r.passages.length ? '<ul class="plain">' + r.passages.map(function (p) {
      return '<li class="hit">' + link("#/doc/" + encodeURIComponent(docSlug(p.passage.path)), p.passage.title) + ' <span class="mono muted">' + esc(p.passage.path) + "</span><div>" + esc(p.snippet) + "</div></li>";
    }).join("") + "</ul>" : '<p class="empty">' + ((ix.payload.passages || []).length ? "No passage matches." : "Passages are not in this payload.") + "</p>") + "</div>");
    return h.join("");
  }

  function pageFindings(ix) {
    var f = ix.payload.findings || [], derived = (ix.payload.edges || []).filter(function (e) { return e.status === "derived"; });
    var byRule = {};
    derived.forEach(function (e) { (byRule[e.derived_by] = byRule[e.derived_by] || []).push(e); });
    (ix.payload.derived_attributes || []).forEach(function (d) { (byRule[d.derived_by] = byRule[d.derived_by] || []).push(d); });
    var h = ["<h1>Findings and rules</h1>"];
    h.push('<div class="card"><h2>Policy findings <span class="muted">' + f.length + "</span></h2>" + (f.length ? '<ul class="plain">' + f.map(function (x) {
      return "<li>" + badge(x.severity, x.severity) + " <code>" + esc(x.rule) + "</code> " + (x.node ? entityLink(ix, x.node) + ": " : "") + esc(x.message) + "</li>";
    }).join("") + "</ul>" : '<p class="empty">Every policy rule is satisfied.</p>') + "</div>");
    var rules = Object.keys(byRule).sort();
    h.push('<div class="card"><h2>Derived by rules</h2>' + (rules.length ? rules.map(function (r) {
      return "<h3><code>" + esc(r) + '</code> <span class="muted">' + byRule[r].length + "</span></h3><ul class=\"plain\">" + byRule[r].map(function (e) {
        return e.rel ? "<li>" + entityLink(ix, e.from) + " <code>" + esc(e.rel) + "</code> " + entityLink(ix, e.to) + premises(ix, e.premises) + "</li>"
                     : "<li>" + entityLink(ix, e.node) + " <code>" + esc(e.name) + "</code> = " + esc(fmt(e.value)) + premises(ix, e.premises) + "</li>";
      }).join("") + "</ul>";
    }).join("") : '<p class="empty">Nothing is derived; every fact is asserted by a document.</p>') + "</div>");
    return h.join("");
  }

  function ledgerList(entries) {
    return '<ul class="plain">' + entries.map(function (e) {
      return '<li><span class="mono">' + esc(e.at || "?") + "</span> +" + esc(e.nodes_added || 0) + " nodes, " + esc(e.nodes_changed || 0) + " changed, +" + esc(e.edges_added || 0) + " edges" +
        (e.by ? ' <span class="muted">by ' + esc(e.by) + "</span>" : "") + (e.note ? "<div>" + esc(e.note) + "</div>" : "") +
        ((e.retired || []).length ? '<div class="muted">retired ' + e.retired.map(function (r) { return "<code>" + esc(r.id) + "</code>" + (r.change_note ? ": " + esc(r.change_note) : ""); }).join("; ") + "</div>" : "") + "</li>";
    }).join("") + "</ul>";
  }

  function pageChanges(ix) {
    var led = ix.payload.ledger || [];
    return "<h1>Changes</h1>" + (led.length ? '<div class="card">' + ledgerList(led) + "</div>" : '<p class="empty">Nothing recorded in the ledger yet.</p>');
  }

  function renderPage(ix, route) {
    switch (route.page) {
      case "home": return pageHome(ix);
      case "type": return pageType(ix, route.arg);
      case "entity": return pageEntity(ix, route.arg);
      case "doc": return pageDoc(ix, route.arg);
      case "docs": return pageDocs(ix);
      case "search": return pageSearch(ix, route.params.q || "");
      case "findings": return pageFindings(ix);
      case "changes": return pageChanges(ix);
      default: return '<h1>No such page</h1><p class="empty">' + esc(route.page) + "</p>";
    }
  }

  function sideNav(ix, route) {
    var h = ["<h3>Read</h3>", nav("#/", "Home", route.page === "home"), nav("#/docs", "Documents", route.page === "docs" || route.page === "doc", (ix.payload.documents || []).length),
             nav("#/findings", "Findings and rules", route.page === "findings", (ix.payload.findings || []).length), nav("#/changes", "Changes", route.page === "changes", (ix.payload.ledger || []).length)];
    h.push("<h3>Classes</h3>");
    ix.classes.forEach(function (t) { h.push(nav("#/type/" + encodeURIComponent(t), t, route.page === "type" && route.arg === t, ix.byType[t].filter(function (n) { return n.status !== "superseded"; }).length)); });
    return h.join("");
  }
  function nav(href, text, active, n) { return '<a href="' + esc(href) + '"' + (active ? ' class="active"' : "") + "><span>" + esc(text) + "</span>" + (n != null ? '<span class="n">' + esc(n) + "</span>" : "") + "</a>"; }

  // ---------- the DOM ----------
  var state = {ix: null, live: false, seq: null, timer: null};

  function load() {
    return fetch("data.json", {cache: "no-store"}).then(function (r) { if (!r.ok) throw new Error("data.json " + r.status); return r.json(); });
  }

  function render() {
    if (!state.ix) return;
    var route = parseRoute(location.hash);
    document.getElementById("side").innerHTML = sideNav(state.ix, route);
    document.getElementById("main").innerHTML = renderPage(state.ix, route);
    var p = state.ix.payload;
    document.getElementById("brand-name").textContent = (p.project && p.project.name) || "Oto";
    document.title = ((p.project && p.project.name) || "Oto") + " · reader";
    freshness();
    document.getElementById("foot").textContent = "Read from the graph: every fact carries its status, dates and source. A superseded fact is history, not current.";
    if (route.page === "search") document.getElementById("search-box").value = route.params.q || "";
    window.scrollTo(0, 0);
  }

  function freshness() {
    var p = state.ix && state.ix.payload || {}, m = p.mode || {};
    var text = (state.live ? "live" : "static") + " · build " + (p.build_seq || "?") + " · " + (p.backend || "");
    if (m.regime === "preview" || m.regime === "watch") text = m.regime + " · built " + String(m.preview_built_at || "?").replace("T", " ").slice(0, 19) + (m.differs ? " · " + m.differs + " pending" : "");
    document.getElementById("freshness").textContent = text;
  }

  function poll() {
    fetch("api/changes?since=" + encodeURIComponent(state.seq || ""), {cache: "no-store"}).then(function (r) {
      if (!r.ok) throw new Error("no changes route");
      return r.json();
    }).then(function (c) {
      var was = state.live;
      state.live = true;
      if (!was) freshness();
      if (c.changed && state.seq !== null) load().then(function (payload) { state.ix = index(payload); state.seq = payload.token || payload.build_seq; render(); });
      else if (state.seq === null) state.seq = c.token || c.build_seq;
      state.timer = setTimeout(poll, 4000);
    }).catch(function () { state.live = false; freshness(); });
  }

  function boot() {
    load().then(function (payload) {
      state.ix = index(payload); state.seq = payload.token || payload.build_seq;
      render();
      poll();
    }).catch(function (e) { document.getElementById("main").innerHTML = '<h1>No data</h1><p class="empty">' + esc(e.message) + ". Serve this app with <code>oto serve --http --app reader</code> or export it with <code>oto build --target site</code>.</p>"; });
    window.addEventListener("hashchange", render);
    document.getElementById("search-form").addEventListener("submit", function (ev) { ev.preventDefault(); location.hash = "#/search?q=" + encodeURIComponent(document.getElementById("search-box").value); });
  }

  var api = {index: index, search: search, parseRoute: parseRoute, renderPage: renderPage, sideNav: sideNav, passageFor: passageFor, boot: boot};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.OtoReader = api;
})(typeof window !== "undefined" ? window : globalThis);
