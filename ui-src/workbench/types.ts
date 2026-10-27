/* The project snapshot (oto/snapshot.py, contract version SNAPSHOT) and the parts of the graph
 * payload (oto/serve/payload.py) the workbench reads. Keep these in step with the Python side. */

export const SNAPSHOT = 1;
export type StationState = "done" | "attention" | "not_started";
export type StationId = "sources" | "survey" | "vocabulary" | "curate" | "build" | "rules" | "test" | "deploy";

export interface Snapshot {
  snapshot: number;
  token: string;
  project: { name: string | null; slug: string | null };
  /* true in the copy a static site carries; `withheld` names, as dotted paths, what it left out */
  published: boolean;
  withheld: string[];
  overview: { facts: number; documents: number; conversations: number; questions: { declared: number; answered: number } };
  stations: { id: StationId; title: string; state: StationState; line: string }[];
  sources: {
    inbox: string[]; processing: string[]; open_runs: string[];
    errors: { file: string; reason: string | null; run: string }[];
    documents: { slug: string; title: string }[];
    waiting: { inbox: number; processing: number; errors: number; open_runs: number };
  };
  survey: { accepted: number; rejected: number; latest: { term: string; verdict: string; as: string | null; by: string; at: string; note: string | null }[] };
  vocabulary: {
    accepted: boolean; version: number | string | null; relations: number; attributes: number;
    classes: { name: string; definition: string | null; things: number; why: string | null; validated_by: string | null }[];
    questions: { id: string; who: string | null; question: string; answered: boolean }[];
    parts: { name: string; release: string | null; origin: string | null }[];
  };
  curate: {
    candidate: boolean; assertions: number; reattest: number;
    changes: { at: string; by: string; note: string | null; sources: string[]; added: number;
               retired: { id: string; superseded_by: string | null; valid_to: string | null; change_note: string | null }[] }[];
  };
  build: { built: boolean; stale: boolean; facts: number; current: number; superseded: number; links: number };
  rules: {
    rules: { id: string; kind: string; severity: string | null; why: string | null; validated_by: string | null }[];
    findings: { rule: string; node: string | null; label: string | null; severity: string; message: string }[];
  };
  test: {
    gold: { questions: number; authored_by: string | null; audited_fraction: number | null } | null;
    bench: { at: string; systems: Record<string, { right: number; wrong: number; abstained: number; precision: number | null; coverage: number | null; score: number | null }> } | null;
    feedback: { id: string; verdict: string; question: string; by: string; at: string; expected: string | null; promoted: boolean }[];
    feedback_counts: Record<string, number>;
    feedback_waiting: number;
  };
  deploy: { backend: string; targets: string[]; site: boolean };
  /* the board (oto/work.py), or null when the vocabulary declares no work item */
  work: Board | null;
  open: { station: StationId; what: string; detail: string | null }[];
}

export interface Board {
  counts: { open: number; blocked: number; deployed: number };
  open: { id: string; label: string; kind: string | null; due: string | null }[];
  blocked: { id: string; label: string; since: string | null; reason: string | null; by: string | null; transition: string | null;
             waiting_on: { id: string; label: string; type: string | null } | null }[];
  deployed: { id: string; label: string; environment: string | null; at: string | null }[];
}

export interface GraphNode {
  id: string; type: string; label: string; status: string; summary: string; source_doc?: string | null;
  as_of: string | null; valid_from: string | null; valid_to: string | null;
  superseded_by: string | null; supersedes: string | string[] | null;
  attributes: Record<string, unknown>; aliases: string[]; sources: string[];
  evidence: { doc: string; where?: string; quote?: string }[];
}
export interface GraphEdge { from: string; rel: string; to: string; status: string; derived_by: string | null }
export interface Payload {
  build_seq: string | number | null; token?: string;
  project: { name: string | null; slug: string | null };
  vocabulary: { classes: Record<string, { definition?: string; subclass_of?: string[] | string }>; properties: Record<string, unknown> };
  /* the vocabulary as a navigable model (oto/serve/ontology.py); absent in a payload older than it */
  ontology?: OntologyModel | null;
  /* the rules as a person reads them and the lexicon (oto/serve/rules.py, oto/serve/lexicon.py) */
  rules?: RulesModel | null;
  terms?: LexiconModel | null;
  graphs?: GraphsModel | null;
  nodes: GraphNode[]; edges: GraphEdge[];
}

export interface OntologyAttribute {
  name: string; label: string; type: string; values: string[] | null; definition: string;
  required: boolean; default: unknown; decision: boolean;
}
export interface OntologyRelationOut { name: string; label: string; to: string[]; cardinality: string; inverse: string | null; definition: string; inherited_from: string | null }
export interface OntologyRelationIn { name: string; label: string; from: string[]; inverse: string | null; inherited_from: string | null }
export interface OntologyClass {
  name: string; label: string; definition: string; scope_note: string; example: string;
  parents: string[]; ancestors: string[]; children: string[]; requires: string[]; things: number;
  attributes: OntologyAttribute[]; relations_out: OntologyRelationOut[]; relations_in: OntologyRelationIn[];
}
export interface OntologyRelation {
  name: string; label: string; domain: string[]; range: string[]; inverse: string | null; inverse_label: string | null;
  cardinality: string; definition: string; subproperty_of: string | null; derived: boolean; things: number;
}
export interface OntologyModel {
  version: number | string | null; derived_from_data: boolean;
  counts: { classes: number; relations: number; attributes: number; things: number | null };
  classes: OntologyClass[]; relations: OntologyRelation[];
  /* current and accepted versions and what changed since; absent in a payload older than it */
  versions?: OntologyVersions | null;
}

/* The rules as a person reads them (oto/serve/rules.py, roadmap D2) */
export interface RuleEntry {
  id: string; kind: string; severity: string | null; why: string | null; validated_by: string | null; answers: string | null;
  when: string[]; then: string;
  scope: Record<string, { classes: string[]; how: "declared" | "implied" }>;
  classes: string[]; relations: string[]; attributes: string[]; every_node: boolean;
}
export interface RulesModel {
  counts: { rules: number; derive: number; policy: number; confirmed: number };
  rules: RuleEntry[];
  /* every declared class -> the ids of the rules that apply to it, directly, through an ancestor or to every node */
  by_class: Record<string, string[]>;
  lineage: Record<string, string[]>;
}

/* The lexicon: every term in every language, and the words people use (oto/serve/lexicon.py, roadmap D3) */
export interface LexiconTarget { section: "ontology" | "knowledge"; class?: string | null; relation?: string; attribute?: string | null; scheme?: string; entity?: string }
export interface LexiconTerm {
  kind: "class" | "relation" | "attribute" | "temporal" | "scheme" | "concept"; name: string; owner: string | null;
  labels: Record<string, string>; alt_labels: Record<string, string[]>; definition: Record<string, string>; target: LexiconTarget;
}
export interface LexiconPhrase { phrase: string; canonical: string; status: string; note: string; target: string | null; label: string | null; type: string | null }
export interface LexiconHit {
  kind: LexiconTerm["kind"] | "phrase"; name: string; owner: string | null; label: string | null; labels: Record<string, string>;
  target: LexiconTarget | null; match: { language: string | null; text: string; how: string };
  canonical?: string; type?: string | null; status?: string; note?: string;
}
export interface LexiconModel {
  languages: string[]; default_language: string; terms: LexiconTerm[]; phrases: LexiconPhrase[];
  counts: { terms: number; phrases: number; languages: number };
}

/* The graph descriptors as a person reads them (oto/serve/graphs.py, roadmap D4) */
export interface GraphNear { other: string; similarity: number; same_reach: boolean; told_apart: { this: string[]; other: string[] }; message: string }
export interface GraphEntry {
  id: string; label: string | null; subject: string | null; classes: string[]; reach: string | null; slug: string | null; own: boolean;
  depends_on: string[]; depended_on_by: string[]; near_duplicates: GraphNear[];
}
export interface GraphsModel { own: string | null; counts: { graphs: number; dependencies: number; near_duplicates: number }; graphs: GraphEntry[]; pairs: unknown[] }

/* What bears on one entity (oto/serve/links.py, roadmap D5); ui-src/workbench/links.ts computes the same client-side */
export interface LinkTarget { section: "ontology" | "rules" | "lexicon" | "dependencies" | "knowledge"; class?: string | null; query?: string; graph?: string; entity?: string }
export interface EntityLinks {
  entity: string; type: string;
  rules: { id: string; kind: string; severity: string | null; via: string | null; target: LinkTarget }[];
  terms: ({ kind: "class"; name: string; label: string; target: LinkTarget } | { kind: "phrase"; phrase: string; canonical: string; target: LinkTarget })[];
  graphs: { id: string; label: string | null; own: boolean; reach: string | null; target: LinkTarget }[];
  decisions: { id: string; label: string | null; rel: string; direction: "in" | "out"; status: unknown; decided_on: unknown; target: LinkTarget }[];
  files: { id: string | null; label: string | null; kind: string; where: string | null; rel: string | null; target: LinkTarget | null }[];
  counts: { rules: number; terms: number; graphs: number; decisions: number; files: number };
}

/* The vocabulary's versions and a diff between two of them (oto/serve/versions.py, roadmap D6) */
export interface VersionChange { kind: string; severity: "breaking" | "additive" | "cosmetic"; subject: string; detail: string; affected: number }
export interface VersionDiff {
  from: { version: number; classes: number; relations: number; attributes: number };
  to: { version: number; classes: number; relations: number; attributes: number };
  labels: [string, string] | null; changes: VersionChange[];
  counts: { changes: number; breaking: number; additive: number; cosmetic: number }; bump_needed: boolean;
}
export interface OntologyVersions { current: number; accepted: number | null; since_accepted: VersionDiff | null; git: boolean }
