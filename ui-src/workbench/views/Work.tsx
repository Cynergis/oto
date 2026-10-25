/* Work: the board (roadmap M5). Three columns over the snapshot's `work` section, which the engine
 * derives the way a build does: blocked first, grouped by whom or what each item waits on, so "what's
 * blocked, and on whom?" is one glance; deployed by environment, prod being done; open, soonest due
 * first. Read-only: a block names the person to ask, and the agent can send the message (M6). */
import * as React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { AskAgent, Empty } from "../components/common";
import type { Board } from "../types";

type Props = { board: Board; published: boolean; live: boolean; onEntity: (id: string) => void };
const ENVIRONMENTS = ["qa", "preprod", "prod"] as const;

export function Work({ board, published, live, onEntity }: Props) {
  const c = board.counts;
  const total = c.open + c.blocked + c.deployed;
  const groups = new Map<string, Board["blocked"]>();
  for (const b of board.blocked) {
    const key = b.waiting_on ? b.waiting_on.label + (b.waiting_on.type ? " · " + b.waiting_on.type.toLowerCase() : "") : "nothing named";
    groups.set(key, [...(groups.get(key) || []), b]);
  }
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-2xl font-semibold">{total} item{total === 1 ? "" : "s"}: {c.open} open, {c.blocked} blocked, {c.deployed} deployed</h1>
        <p className="text-sm text-muted-foreground">An item's state is what its latest recorded change says; nobody writes it on the item.</p>
      </header>
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="border-attention/40">
          <CardHeader><CardTitle>Blocked <Badge variant={c.blocked ? "attention" : "muted"}>{c.blocked}</Badge></CardTitle><CardDescription>by whom or what each waits on</CardDescription></CardHeader>
          <CardContent className="flex flex-col gap-5">
            {board.blocked.length === 0 ? <Empty>Nothing is blocked.</Empty> : [...groups.entries()].map(([who, items]) => (
              <section key={who} className="flex flex-col gap-3">
                <h3 className="text-sm font-semibold">waits on {who}</h3>
                {items.map(b => (
                  <div key={b.id} className="flex flex-col gap-1.5 rounded-md border bg-background p-3 text-sm">
                    <button type="button" onClick={() => onEntity(b.id)} className="text-left font-medium text-primary underline-offset-4 hover:underline">{b.label}</button>
                    <span className="text-muted-foreground">since {b.since || "?"}{b.by ? ", raised by " + b.by : ""}</span>
                    {b.reason ? <p>{b.reason}</p> : null}
                    {!published && b.waiting_on ? <AskAgent live={live} request={"Send the message for " + b.label + ": run oto work notify on it, so " + b.waiting_on.label + " gets the block's reason and date."} /> : null}
                  </div>
                ))}
              </section>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Open <Badge variant="secondary">{c.open}</Badge></CardTitle><CardDescription>soonest due first</CardDescription></CardHeader>
          <CardContent>
            {board.open.length === 0 ? <Empty>Nothing is open.</Empty> : (
              <ul className="flex flex-col divide-y">
                {board.open.map(i => (
                  <li key={i.id} className="flex items-baseline justify-between gap-3 py-2 text-sm">
                    <button type="button" onClick={() => onEntity(i.id)} className="text-left text-primary underline-offset-4 hover:underline">{i.label}</button>
                    <span className="whitespace-nowrap text-xs text-muted-foreground">{[i.kind, i.due && "due " + i.due].filter(Boolean).join(" · ")}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card className="border-done/40">
          <CardHeader><CardTitle>Deployed <Badge variant="done">{c.deployed}</Badge></CardTitle><CardDescription>by environment; prod is done</CardDescription></CardHeader>
          <CardContent className="flex flex-col gap-4">
            {board.deployed.length === 0 ? <Empty>Nothing is deployed yet.</Empty> : ENVIRONMENTS.filter(e => board.deployed.some(d => d.environment === e)).map(env => (
              <section key={env} className="flex flex-col gap-1.5">
                <h3 className="font-mono text-xs uppercase tracking-wide text-muted-foreground">{env}</h3>
                <ul className="flex flex-col divide-y">
                  {board.deployed.filter(d => d.environment === env).map(d => (
                    <li key={d.id} className="flex items-baseline justify-between gap-3 py-2 text-sm">
                      <button type="button" onClick={() => onEntity(d.id)} className="text-left text-primary underline-offset-4 hover:underline">{d.label}</button>
                      <span className="whitespace-nowrap text-xs text-muted-foreground">{d.at || ""}</span>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
