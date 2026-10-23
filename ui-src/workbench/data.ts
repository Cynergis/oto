/* Where the workbench's two objects come from, and when to fetch them again.
 *
 * Served (`oto serve --http`): the snapshot is in api/status and the graph in data.json; api/changes
 * says when either moved, so an open page follows the agent's work. Published (a static export):
 * snapshot.json and data.json beside the page, read once. The workbench never reads a project's files. */
import type { Payload, Snapshot } from "./types";
import { SNAPSHOT } from "./types";

export interface Loaded { snapshot: Snapshot | null; payload: Payload | null; live: boolean; problem: string | null }

async function json<T>(url: string): Promise<T> {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(url + " " + r.status);
  return r.json() as Promise<T>;
}

export async function load(): Promise<Loaded> {
  let snapshot: Snapshot | null = null, live = false, problem: string | null = null;
  try {
    const status = await json<{ snapshot: Snapshot | null }>("api/status");
    snapshot = status.snapshot;
    live = true;
  } catch {
    snapshot = await json<Snapshot>("snapshot.json").catch(() => null);
  }
  if (snapshot && snapshot.snapshot !== SNAPSHOT) {
    problem = "This page reads snapshot version " + SNAPSHOT + "; the engine wrote version " + snapshot.snapshot + ". Update one of them.";
    snapshot = null;
  }
  const payload = await json<Payload>("data.json").catch(() => null);
  return { snapshot, payload, live, problem };
}

/* Calls `changed` when the build or the snapshot moves; stops when the page is static. */
export function follow(current: () => Loaded, changed: () => void) {
  let timer: number | undefined;
  const tick = async () => {
    const now = current();
    if (!now.live) return;
    try {
      const seq = (now.payload && (now.payload.token || now.payload.build_seq)) || "";
      const c = await json<{ changed: boolean; snapshot_token: string | null }>("api/changes?since=" + encodeURIComponent(String(seq)));
      if ((now.payload && c.changed) || (c.snapshot_token && now.snapshot && c.snapshot_token !== now.snapshot.token)) changed();
    } catch {
      /* the server went away: keep showing what was loaded */
    }
    timer = window.setTimeout(tick, 4000);
  };
  timer = window.setTimeout(tick, 4000);
  return () => window.clearTimeout(timer);
}
