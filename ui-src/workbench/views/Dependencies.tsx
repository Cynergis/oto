/* Dependencies: this graph and the graphs it depends on, read from their descriptors (roadmap D4).
 * This graph first, then each dependency with its subject, where it is reached, the classes it says it
 * holds (a link into the Ontology page when this vocabulary declares the class), who depends on whom,
 * and the pairs an agent could not tell apart, flagged with the words that set them apart. Read-only. */
import * as React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Empty } from "../components/common";
import type { GraphEntry, GraphsModel, OntologyModel } from "../types";
import { cn } from "../lib/utils";

type Props = { model: GraphsModel | null; ontology: OntologyModel | null; selected: string | null; onPick: (id: string | null) => void; onClass: (name: string) => void };

export function Dependencies({ model, ontology, selected, onPick, onClass }: Props) {
  if (!model) return <Empty>No descriptors to read: build the project first, then serve or export it.</Empty>;
  const declared: Record<string, string> = {};
  for (const c of ontology?.classes || []) declared[c.name] = c.label;
  const by: Record<string, GraphEntry> = {};
  for (const g of model.graphs) by[g.id] = g;
  const link = (id: string) => by[id]
    ? <button key={id} type="button" onClick={() => onPick(id)} className="text-primary underline-offset-4 hover:underline">{by[id].label || id}</button>
    : <span key={id} className="font-mono">{id}</span>;
  const links = (ids: string[]) => ids.length ? ids.map((id, i) => <React.Fragment key={id}>{i ? ", " : ""}{link(id)}</React.Fragment>) : <span className="text-muted-foreground">—</span>;
  const listed = selected && by[selected] ? [by[selected]] : model.graphs;

  if (model.counts.graphs === 0) return <Empty>This graph holds no descriptor of itself or of any other graph: `oto graph describe --record` writes its own, `oto graph depend` declares a dependency.</Empty>;
  return (
    <div className="flex flex-wrap items-start gap-6">
      <nav aria-label="Graphs" className="flex flex-[1_1_240px] flex-col gap-0.5">
        <p className="mb-1 px-3 text-xs text-muted-foreground">
          {model.counts.graphs} {model.counts.graphs === 1 ? "graph" : "graphs"}, {model.counts.dependencies} {model.counts.dependencies === 1 ? "dependency" : "dependencies"}
          {model.counts.near_duplicates ? <span className="text-attention"> · {model.counts.near_duplicates} near-duplicate {model.counts.near_duplicates === 1 ? "pair" : "pairs"}</span> : " · none a near-duplicate of another"}
        </p>
        <button type="button" onClick={() => onPick(null)} aria-pressed={!selected}
          className={cn("flex min-h-9 items-center justify-between gap-2 rounded-md px-3 text-left text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", !selected && "bg-secondary font-semibold text-secondary-foreground")}>
          <span>Every graph</span><span className="font-mono text-xs text-muted-foreground">{model.counts.graphs}</span>
        </button>
        {model.graphs.map(g => (
          <button key={g.id} type="button" onClick={() => onPick(g.id)} aria-pressed={selected === g.id}
            className={cn("flex min-h-9 items-center justify-between gap-2 rounded-md px-3 text-left text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", selected === g.id && "bg-secondary font-semibold text-secondary-foreground")}>
            <span className="truncate">{g.label || g.id}</span>
            <span className="flex shrink-0 items-center gap-1">
              {g.own ? <Badge variant="done">this graph</Badge> : null}
              {g.near_duplicates.length ? <Badge variant="attention">≈</Badge> : null}
            </span>
          </button>
        ))}
      </nav>

      <div className="flex min-w-0 flex-[3_1_480px] flex-col gap-4">
        {listed.map(g => (
          <Card key={g.id}>
            <CardHeader>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">graph</Badge>
                {g.own ? <Badge variant="done">this graph</Badge> : <Badge variant="secondary">a dependency</Badge>}
                <span className="font-mono text-xs text-muted-foreground">{g.id}</span>
                {g.reach ? <span className="ml-auto font-mono text-xs text-muted-foreground">{g.reach}</span> : null}
              </div>
              <CardTitle className="text-xl">{g.label || g.id}</CardTitle>
              {g.subject ? <CardDescription className="text-base">{g.subject}</CardDescription> : null}
            </CardHeader>
            <CardContent className="flex flex-col gap-4 text-sm">
              <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,4fr)] gap-x-4 gap-y-1.5">
                <dt className="text-muted-foreground">Depends on</dt><dd>{links(g.depends_on)}</dd>
                <dt className="text-muted-foreground">Depended on by</dt><dd>{links(g.depended_on_by)}</dd>
                <dt className="text-muted-foreground">Holds</dt>
                <dd className="flex flex-wrap gap-1.5">
                  {g.classes.length ? g.classes.map(c => declared[c]
                    ? <button key={c} type="button" onClick={() => onClass(c)} className="rounded-md border px-2 py-0.5 text-xs text-primary underline-offset-4 hover:underline first-letter:uppercase">{declared[c]}</button>
                    : <span key={c} className="rounded-md border px-2 py-0.5 font-mono text-xs text-muted-foreground" title="not a class of this vocabulary">{c}</span>)
                    : <span className="text-muted-foreground">—</span>}
                </dd>
              </dl>
              {g.near_duplicates.map(n => (
                <div key={n.other} className="rounded-md bg-attention-soft px-3 py-2 text-attention">
                  <p className="font-medium">{n.same_reach ? "The same graph described twice as " : "Hard to tell apart from "}{link(n.other)}{n.same_reach ? "" : " (" + Math.round(n.similarity * 100) + "% of the words in common)"}</p>
                  {!n.same_reach ? <p className="mt-1 text-xs">Told apart only by <span className="font-mono">{n.told_apart.this.join(", ") || "(nothing)"}</span> here and <span className="font-mono">{n.told_apart.other.join(", ") || "(nothing)"}</span> there. A question naming none of those words reaches both: say in one subject what only that graph holds, or merge them.</p>
                    : <p className="mt-1 text-xs">Both descriptors are reached at {g.reach}: keep one.</p>}
                </div>
              ))}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
