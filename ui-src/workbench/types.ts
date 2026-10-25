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
  id: string; type: string; label: string; status: string; summary: string;
  as_of: string | null; valid_from: string | null; valid_to: string | null;
  superseded_by: string | null; supersedes: string | string[] | null;
  attributes: Record<string, unknown>; aliases: string[]; sources: string[];
  evidence: { doc: string; where?: string; quote?: string }[];
}
export interface GraphEdge { from: string; rel: string; to: string; status: string; derived_by: string | null }
export interface Payload {
  build_seq: string | number | null; token?: string;
  project: { name: string | null; slug: string | null };
  vocabulary: { classes: Record<string, { definition?: string }>; properties: Record<string, unknown> };
  nodes: GraphNode[]; edges: GraphEdge[];
}
