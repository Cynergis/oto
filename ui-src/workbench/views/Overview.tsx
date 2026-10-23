/* Overview: what the knowledge base knows, what changed, and what is still open (direction C). */
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Empty } from "../components/common";
import type { Snapshot } from "../types";

function plural(n: number, word: string) {
  return n + " " + word + (n === 1 ? "" : "s");
}

export function Overview({ snapshot, onOpen }: { snapshot: Snapshot; onOpen: (station: string) => void }) {
  const o = snapshot.overview;
  const q = o.questions;
  const answers = q.declared === 0 ? "and has no questions declared yet"
    : q.answered === q.declared ? "and answers all " + q.declared + " of its questions"
    : "and answers " + q.answered + " of its " + q.declared + " questions";
  return (
    <div className="flex flex-col gap-8">
      <header className="flex max-w-4xl flex-col gap-3">
        <h1 className="text-3xl font-semibold leading-tight md:text-4xl">
          It knows {plural(o.facts, "thing")} from {plural(o.documents, "document")} and {plural(o.conversations, "conversation")}, {answers}.
        </h1>
        <p className="text-base leading-relaxed text-muted-foreground">
          Every fact cites where it came from. When a fact changed, the old one is kept, so you can still ask what was believed on any date.
        </p>
      </header>

      <div className="flex flex-wrap items-start gap-6">
        <Card className="min-w-0 flex-[999_1_560px]">
          <CardHeader><CardTitle className="text-lg">What changed</CardTitle></CardHeader>
          <CardContent>
            {snapshot.curate.changes.length === 0 ? <Empty>Nothing has entered the graph yet.</Empty> : (
              <ol className="flex flex-col">
                {snapshot.curate.changes.map((c, i) => (
                  <li key={i} className="grid grid-cols-[110px_minmax(0,1fr)] gap-4 border-t py-4 first:border-t-0 first:pt-0">
                    <span className="pt-0.5 text-sm text-muted-foreground">{(c.at || "").slice(0, 10)}</span>
                    <div className="flex flex-col gap-2">
                      <p className="font-medium leading-snug">{c.note || plural(c.added, "fact") + " added"}</p>
                      {c.retired.map(r => (
                        <div key={r.id} className="grid gap-2 sm:grid-cols-2">
                          <div className="rounded-md border px-3 py-2 text-sm">
                            <span className="block text-xs uppercase tracking-wide text-muted-foreground">Until {r.valid_to || "?"} · kept</span>
                            <span className="font-mono text-muted-foreground line-through">{r.id}</span>
                          </div>
                          <div className="rounded-md border border-primary/40 bg-secondary px-3 py-2 text-sm">
                            <span className="block text-xs uppercase tracking-wide text-secondary-foreground">From {r.valid_to || "?"} · current</span>
                            <span className="font-mono font-medium">{r.superseded_by || "retired"}</span>
                          </div>
                          {r.change_note ? <p className="text-sm text-muted-foreground sm:col-span-2">{r.change_note}</p> : null}
                        </div>
                      ))}
                      <span className="text-sm text-muted-foreground">
                        {c.by}{c.sources.length ? " · " + c.sources.join(", ") : ""}
                      </span>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </CardContent>
        </Card>

        <section aria-labelledby="still-open" className="flex flex-[1_1_320px] flex-col gap-3">
          <h2 id="still-open" className="text-lg font-semibold">Still open</h2>
          {snapshot.open.length === 0 ? <Empty>Nothing waits on a person.</Empty> : snapshot.open.map((o, i) => (
            <button key={i} type="button" onClick={() => onOpen(o.station)}
              className="flex flex-col gap-1 rounded-md border border-attention/30 bg-attention-soft px-4 py-3 text-left text-sm leading-snug transition-colors hover:border-attention focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <span className="flex items-center justify-between gap-2">
                <strong className="font-semibold">{o.what}</strong>
                <Badge variant="outline" className="shrink-0 capitalize">{o.station}</Badge>
              </span>
              {o.detail ? <span className="text-attention">{o.detail}</span> : null}
            </button>
          ))}
        </section>
      </div>
    </div>
  );
}
