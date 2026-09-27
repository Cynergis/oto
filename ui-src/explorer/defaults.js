/* What the explorer needs beyond the graph, derived from the vocabulary and overridable by a
 * ontology's or project's `views/explorer.json`:
 *
 *   columns      [[Class, ...], ...]   which classes sit in which column, left to right
 *   typeMeta     {Class: {label, colour, icon}}
 *   evidenceable [Class, ...]          classes that must cite evidence or show as "assumed"
 *   threshold    number                 draw the whole graph up to this many nodes; focus mode above
 *
 * The default column order is the vocabulary's declaration order, which every ontology writes
 * with intent; classes are grouped into at most `maxColumns` columns. Colours come from a fixed
 * hue wheel by class index, so a class keeps its colour across rebuilds. Pure; runs under Node.
 */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.OtoExplorerDefaults = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var HUES = [200, 30, 275, 150, 340, 60, 240, 110, 10, 190, 300, 80, 160, 220, 40, 260];
  var ICONS = [
    [/decision|adr|choice|approval/i, "check"],
    [/doc|source|file|report|transcript/i, "doc"],
    [/risk|threat|incident|hazard/i, "warn"],
    [/team|person|persona|party|stakeholder|role|user|customer|claimant|adjuster|owner/i, "user"],
    [/metric|measure|kpi|objective|result|target|slo/i, "metric"],
    [/process|journey|flow|procedure|runbook|workflow|step/i, "journey"],
    [/system|component|service|platform|application|api|interface|resource|datastore|database|environment|store/i, "graph"],
    [/policy|rule|regulation|control|governance|requirement|constraint|invariant/i, "policy"],
    [/claim|case|incident|matter|engagement|deliverable|contract|coverage|product|capability/i, "usecase"],
  ];

  function icon(name) {
    for (var i = 0; i < ICONS.length; i++) if (ICONS[i][0].test(name)) return ICONS[i][1];
    return "usecase";
  }

  function readable(name) {
    return name.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ");
  }

  function fromVocabulary(vocabulary, override) {
    override = override || {};
    var classes = Object.keys((vocabulary && vocabulary.classes) || {});
    var maxColumns = override.maxColumns || 9;
    var typeMeta = {};
    classes.forEach(function (c, i) {
      typeMeta[c] = {label: readable(c), colour: "oklch(0.55 0.13 " + HUES[i % HUES.length] + ")", icon: icon(c)};
    });
    Object.keys(override.typeMeta || {}).forEach(function (c) {
      typeMeta[c] = Object.assign({}, typeMeta[c] || {label: readable(c), colour: "oklch(0.5 0.02 260)", icon: "usecase"}, override.typeMeta[c]);
    });
    var columns;
    if (override.columns && override.columns.length) {
      columns = override.columns.map(function (col) { return Array.isArray(col) ? col : [col]; });
      var placed = {};
      columns.forEach(function (col) { col.forEach(function (c) { placed[c] = true; }); });
      var rest = classes.filter(function (c) { return !placed[c]; });
      if (rest.length) columns.push(rest);                          // a class the override forgot still shows
    } else {
      // documents first, then the vocabulary's order; group when there are too many classes
      var docs = classes.filter(function (c) { return /^(Document|Source)$/.test(c); });
      var others = classes.filter(function (c) { return !/^(Document|Source)$/.test(c); });
      var room = Math.max(1, maxColumns - (docs.length ? 1 : 0));
      var per = Math.max(1, Math.ceil(others.length / room));
      columns = docs.length ? [docs] : [];
      for (var i = 0; i < others.length; i += per) columns.push(others.slice(i, i + per));
    }
    var evidenceable = override.evidenceable || classes.filter(function (c) { return !/^(Document|Source)$/.test(c); });
    return {columns: columns, typeMeta: typeMeta, evidenceable: evidenceable,
            threshold: override.threshold || 400, hops: override.hops || 1, title: override.title || null};
  }

  return {fromVocabulary: fromVocabulary, icon: icon, readable: readable, HUES: HUES};
});
