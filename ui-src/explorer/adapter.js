/* The graph payload (serve/payload.py) as the explorer's graph: {nodes, edges, byId, out, in}.
 *
 * nodes keep the payload's fields (id, type, label, status, attributes, evidence, ...); edges
 * become {from, to, rel, fwd, rev, dash, derived_by, premises, status, pending} where `fwd` is
 * the relation as read from the source, `rev` the inverse the vocabulary declares (or "← rel"),
 * `dash` marks a derived edge and `pending` ({station, verdict, source, reason}, on nodes too)
 * marks a fact from the pending lane, not yet believed. Pure and dependency-free, so it runs
 * under Node for tests.
 */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.OtoExplorerAdapter = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function inverses(vocabulary) {
    var out = {};
    var props = (vocabulary && vocabulary.properties) || {};
    Object.keys(props).forEach(function (rel) {
      var spec = props[rel];
      if (Array.isArray(spec) && spec[2]) out[rel] = spec[2];
    });
    return out;
  }

  function toGraph(payload, options) {
    options = options || {};
    var history = !!options.history;
    var inv = inverses(payload.vocabulary);
    var nodes = [], byId = {}, out = {}, inn = {};
    (payload.nodes || []).forEach(function (n) {
      if (!history && n.status === "superseded") return;
      byId[n.id] = n;
      nodes.push(n);
    });
    var edges = [];
    function addEdge(e, pending) {
      if (!byId[e.from] || !byId[e.to] || e.from === e.to) return;
      if (!history && e.status === "superseded") return;
      var edge = {from: e.from, to: e.to, rel: e.rel, fwd: e.rel, rev: inv[e.rel] || ("← " + e.rel),
                  dash: e.status === "derived", derived_by: e.derived_by || null, premises: e.premises || [],
                  status: e.status || "current", pending: pending || null};
      edges.push(edge);
      (out[e.from] = out[e.from] || []).push(edge);
      (inn[e.to] = inn[e.to] || []).push(edge);
    }
    (payload.edges || []).forEach(function (e) { addEdge(e, null); });
    /* The pending lane: facts on their way in, each carrying its station, never mixed silently. A
     * new entity or edge joins the graph marked; an entity the lane would change is marked in
     * place; a refused row is counted and never drawn. */
    var pendingRows = options.pending === false ? [] : (payload.pending || []);
    var seenEdges = {};
    edges.forEach(function (e) { seenEdges[e.from + "\0" + e.rel + "\0" + e.to] = true; });
    pendingRows.forEach(function (row) {
      if (row.kind !== "node" || !row.id) return;
      var mark = {station: row.station, verdict: row.verdict, source: row.source, reason: row.reason || null};
      if (byId[row.id]) {
        var marked = Object.assign({}, byId[row.id], {pending: mark});
        byId[row.id] = marked;
        for (var i = 0; i < nodes.length; i++) if (nodes[i].id === row.id) { nodes[i] = marked; break; }
      } else if (row.verdict !== "refused") {
        var n = Object.assign({}, row, {pending: mark});
        ["kind", "station", "verdict", "source", "reason"].forEach(function (k) { delete n[k]; });
        n.status = n.status || "current";
        byId[n.id] = n;
        nodes.push(n);
      }
    });
    pendingRows.forEach(function (row) {
      if (row.kind !== "edge" || row.verdict === "refused" || seenEdges[row.from + "\0" + row.rel + "\0" + row.to]) return;
      addEdge({from: row.from, rel: row.rel, to: row.to, status: "current"},
              {station: row.station, verdict: row.verdict, source: row.source, reason: row.reason || null});
    });
    return {nodes: nodes, edges: edges, byId: byId, out: out, in: inn,
            pending: pendingRows.length, refused: pendingRows.filter(function (r) { return r.verdict === "refused"; })};
  }

  function neighbors(g, id) {
    var res = [];
    (g.out[id] || []).forEach(function (e) { res.push({id: e.to, label: e.fwd, dir: "out", edge: e}); });
    (g.in[id] || []).forEach(function (e) { res.push({id: e.from, label: e.rev, dir: "in", edge: e}); });
    return res;
  }

  /* The nodes within `hops` of `id` (id included), for focus mode on a large graph. */
  function neighbourhood(g, id, hops) {
    var seen = {}, frontier = [id];
    seen[id] = 0;
    for (var h = 1; h <= (hops || 1); h++) {
      var next = [];
      frontier.forEach(function (cur) {
        neighbors(g, cur).forEach(function (nb) {
          if (seen[nb.id] === undefined) { seen[nb.id] = h; next.push(nb.id); }
        });
      });
      frontier = next;
    }
    return Object.keys(seen);
  }

  function subgraph(g, ids) {
    var keep = {};
    ids.forEach(function (i) { if (g.byId[i]) keep[i] = true; });
    var nodes = g.nodes.filter(function (n) { return keep[n.id]; });
    var edges = g.edges.filter(function (e) { return keep[e.from] && keep[e.to]; });
    var byId = {}, out = {}, inn = {};
    nodes.forEach(function (n) { byId[n.id] = n; });
    edges.forEach(function (e) { (out[e.from] = out[e.from] || []).push(e); (inn[e.to] = inn[e.to] || []).push(e); });
    return {nodes: nodes, edges: edges, byId: byId, out: out, in: inn};
  }

  function search(g, query, limit) {
    var q = (query || "").trim().toLowerCase();
    if (!q) return [];
    var words = q.split(/\s+/);
    var hits = [];
    g.nodes.forEach(function (n) {
      var text = [n.label, n.id, (n.aliases || []).join(" "), n.summary].join(" ").toLowerCase();
      var ok = words.every(function (w) { return text.indexOf(w) >= 0; });
      if (!ok) return;
      var score = (n.label || "").toLowerCase().indexOf(words[0]) === 0 ? 3 : ((n.label || "").toLowerCase().indexOf(words[0]) >= 0 ? 2 : 1);
      hits.push({node: n, score: score});
    });
    hits.sort(function (a, b) { return b.score - a.score || a.node.label.localeCompare(b.node.label); });
    return hits.slice(0, limit || 12).map(function (h) { return h.node; });
  }

  /* An evidenceable node with no evidence locator and no source is "assumed". */
  function assumed(node, evidenceable) {
    if (!evidenceable || evidenceable.indexOf(node.type) < 0) return false;
    return !((node.evidence && node.evidence.length) || (node.sources && node.sources.length));
  }

  return {toGraph: toGraph, neighbors: neighbors, neighbourhood: neighbourhood, subgraph: subgraph, search: search,
          assumed: assumed, inverses: inverses};
});
