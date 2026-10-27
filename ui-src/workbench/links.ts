/* What bears on one entity, computed from the payload: the same answer as oto/serve/links.py
 * for_entity(), so the exported site needs no server. Keep the two in step. */
import type { EntityLinks, Payload } from "./types";

const DECISION_CLASSES = ["Decision", "DecisionRecord"];
const FILE_CLASSES: Record<string, [string, string | null]> = { Repository: ["repository", "url"], CodeModule: ["code", "path"], Commit: ["commit", "sha"], Document: ["document", null] };

function parents(classes: Payload["vocabulary"]["classes"], name: string): string[] {
  const p = classes[name]?.subclass_of;
  return Array.isArray(p) ? p : p ? [p] : [];
}
function lineage(classes: Payload["vocabulary"]["classes"], name: string): string[] {
  if (!classes[name]) return [name];
  const out = [name], seen = new Set([name]);
  for (let i = 0; i < out.length; i++) for (const p of parents(classes, out[i])) if (!seen.has(p)) { seen.add(p); out.push(p); }
  return out;
}
function kindOf(classes: Payload["vocabulary"]["classes"], name: string, wanted: string[]) {
  return lineage(classes, name).find(w => wanted.includes(w)) || null;
}
function words(name: string) {
  return name.replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2").replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ").toLowerCase();
}

export function linksOf(payload: Payload, entityId: string): EntityLinks | null {
  const byId: Record<string, Payload["nodes"][number]> = {};
  for (const n of payload.nodes) byId[n.id] = n;
  const node = byId[entityId];
  if (!node) return null;
  const classes = payload.vocabulary.classes || {};
  const kind = node.type;
  const line = lineage(classes, kind);
  const attrsOf = (n: Payload["nodes"][number]) => (n.attributes || {}) as Record<string, unknown>;

  const rulesModel = payload.rules;
  const wanted = new Set(rulesModel?.by_class[kind] || []);
  const rules: EntityLinks["rules"] = (rulesModel?.rules || []).filter(r => wanted.has(r.id)).map(r => ({
    id: r.id, kind: r.kind, severity: r.severity,
    via: r.classes.includes(kind) || r.every_node ? null : line.slice(1).find(a => r.classes.includes(a)) || null,
    target: { section: "rules", class: kind } }));

  const termsModel = payload.terms;
  const classTerm = termsModel?.terms.find(t => t.kind === "class" && t.name === kind);
  const terms: EntityLinks["terms"] = [{ kind: "class", name: kind, label: classTerm?.labels[termsModel?.default_language || "en"] || words(kind), target: { section: "ontology", class: kind } }];
  for (const p of termsModel?.phrases || []) if (p.target === entityId) terms.push({ kind: "phrase", phrase: p.phrase, canonical: p.canonical, target: { section: "lexicon", query: p.phrase } });

  const graphs: EntityLinks["graphs"] = (payload.graphs?.graphs || []).filter(g => line.some(c => g.classes.includes(c)))
    .map(g => ({ id: g.id, label: g.label, own: g.own, reach: g.reach, target: { section: "dependencies", graph: g.id } }));

  const decisions: EntityLinks["decisions"] = [], files: EntityLinks["files"] = [];
  for (const e of payload.edges) {
    if ((e.status || "current") !== "current") continue;
    let other: Payload["nodes"][number] | undefined, direction: "in" | "out";
    if (e.from === entityId) { other = byId[e.to]; direction = "out"; }
    else if (e.to === entityId) { other = byId[e.from]; direction = "in"; }
    else continue;
    if (!other || other.id === entityId || (other.status || "current") !== "current") continue;
    const attrs = attrsOf(other);
    if (kindOf(classes, other.type, DECISION_CLASSES)) {
      decisions.push({ id: other.id, label: other.label, rel: e.rel, direction, status: attrs.status, decided_on: attrs.decided_on, target: { section: "knowledge", entity: other.id } });
    }
    const fileClass = kindOf(classes, other.type, Object.keys(FILE_CLASSES));
    if (fileClass) {
      const [fileKind, attribute] = FILE_CLASSES[fileClass];
      files.push({ id: other.id, label: other.label, kind: fileKind, where: (attribute ? (attrs[attribute] as string | undefined) : null) || other.label, rel: e.rel, target: { section: "knowledge", entity: other.id } });
    }
  }
  const docs: [string, string | null][] = [];
  for (const ev of node.evidence || []) if (ev.doc && !docs.some(d => d[0] === ev.doc)) docs.push([ev.doc, ev.where || null]);
  if (node.source_doc && !docs.some(d => d[0] === node.source_doc)) docs.push([node.source_doc, null]);
  for (const [doc, where] of docs) {
    const document = byId["document." + doc] || payload.nodes.find(n => n.type === "Document" && n.label === doc);
    files.push({ id: document?.id || null, label: document?.label || doc, kind: "source", where: doc + (where ? " · " + where : ""), rel: null,
      target: document ? { section: "knowledge", entity: document.id } : null });
  }
  return { entity: entityId, type: kind, rules, terms, graphs, decisions, files,
    counts: { rules: rules.length, terms: terms.length, graphs: graphs.length, decisions: decisions.length, files: files.length } };
}
