// Exercises the explorer's pure modules under Node over a payload file and prints what the
// Python test asserts on. Usage: node explorer_checks.js <ui-src/explorer dir> <payload.json>
"use strict";
const fs = require("fs");
const path = require("path");
const adapter = require(path.join(process.argv[2], "adapter.js"));
const defaults = require(path.join(process.argv[2], "defaults.js"));
const payload = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

const g = adapter.toGraph(payload);
const withHistory = adapter.toGraph(payload, {history: true});
const d = defaults.fromVocabulary(payload.vocabulary, {});
const over = defaults.fromVocabulary(payload.vocabulary, {columns: [["Risk"], ["System", "Component"]], typeMeta: {Risk: {colour: "red", icon: "warn"}},
                                                          evidenceable: ["Risk"], threshold: 5, title: "Custom"});
const sys = "system.payments";
// the pending lane: a new node and edge join with their station, an existing node is marked, a refusal is counted and never drawn
const lane = adapter.toGraph(Object.assign({}, payload, {pending: [
  {kind: "node", station: "proposal", verdict: "new", source: "proposals/memo.json", id: "system.billing", type: "System", label: "Billing platform", status: "current"},
  {kind: "node", station: "candidate", verdict: "changed", source: "graph.candidate.json", id: sys, type: "System", label: "Payments platform", status: "current"},
  {kind: "node", station: "proposal", verdict: "refused", source: "proposals/wrong.json", id: "system.ghost", type: "System", label: "Ghost", reason: "conflict"},
  {kind: "edge", station: "proposal", verdict: "new", source: "proposals/memo.json", from: "system.billing", rel: "owned_by", to: "team.payments"},
  {kind: "edge", station: "proposal", verdict: "refused", source: "proposals/wrong.json", from: "system.billing", rel: "owned_by", to: "system.ghost"}]}));
const laneOff = adapter.toGraph(Object.assign({}, payload, {pending: [{kind: "node", station: "proposal", verdict: "new", source: "x", id: "system.billing", type: "System", label: "B"}]}), {pending: false});
process.stdout.write(JSON.stringify({
  lane: {nodes: lane.nodes.length - g.nodes.length, edges: lane.edges.length - g.edges.length, pending: lane.pending, refused: lane.refused.length,
         billing: lane.byId["system.billing"] && lane.byId["system.billing"].pending, ghost: !!lane.byId["system.ghost"],
         marked: lane.byId[sys].pending && lane.byId[sys].pending.station, markedInList: lane.nodes.filter(n => n.id === sys)[0].pending.verdict,
         edge: lane.edges.filter(e => e.pending).map(e => [e.from, e.rel, e.to, e.pending.station]), off: laneOff.nodes.length - g.nodes.length},
  nodes: g.nodes.length, edges: g.edges.length, historyNodes: withHistory.nodes.length,
  inverses: adapter.inverses(payload.vocabulary),
  edgeSample: g.edges.find(e => e.dash && e.derived_by === "risk-reaches-system") || null,
  neighbours: adapter.neighbors(g, sys).map(n => [n.id, n.label, n.dir]),
  hop1: adapter.neighbourhood(g, "risk.ledger-single-point", 1).sort(),
  hop2: adapter.neighbourhood(g, "risk.ledger-single-point", 2).length,
  sub: adapter.subgraph(g, ["system.payments", "datastore.ledger"]).edges.map(e => e.rel),
  search: adapter.search(g, "ledger").map(n => n.id),
  assumed: g.nodes.filter(n => adapter.assumed(n, d.evidenceable)).length,
  assumedStripped: adapter.assumed(Object.assign({}, g.byId[sys], {sources: [], evidence: []}), d.evidenceable),
  assumedDocument: adapter.assumed(Object.assign({}, g.byId["doc.handbook"], {sources: [], evidence: []}), d.evidenceable),
  columns: d.columns, evidenceable: d.evidenceable, threshold: d.threshold,
  meta: Object.fromEntries(Object.entries(d.typeMeta).map(([k, v]) => [k, [v.label, v.icon, v.colour.startsWith("oklch(")]])),
  overColumns: over.columns, overRisk: over.typeMeta.Risk, overEvidenceable: over.evidenceable, overThreshold: over.threshold, overTitle: over.title,
  icons: ["Document", "DecisionRecord", "Risk", "Team", "SuccessMetric", "Runbook", "DataStore", "Policy", "Claim", "Zebra"].map(defaults.icon),
  readable: [defaults.readable("DecisionRecord"), defaults.readable("data_store")]
}));
