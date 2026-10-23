/* Project: the stations in the order work moves (direction A), each opening its page; Test carries
 * the bench (direction B). Read-only: what waits on a person becomes a request for the agent. */
import * as React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { AskAgent, Dot, Empty, STATE_WORDS } from "../components/common";
import type { Snapshot, StationId } from "../types";
import { cn } from "../lib/utils";

type Props = { snapshot: Snapshot; live: boolean; station: StationId; onStation: (s: StationId) => void; onEntity: (id: string) => void; onType: (t: string) => void };

export function Project({ snapshot, live, station, onStation, onEntity, onType }: Props) {
  const open = snapshot.open.filter(o => o.station === station);
  const name = snapshot.project.name || "this knowledge base";
  return (
    <div className="flex flex-col gap-6">
      <ol aria-label="Stations" className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
        {snapshot.stations.map((s, i) => (
          <li key={s.id}>
            <button type="button" onClick={() => onStation(s.id)} aria-current={station === s.id ? "page" : undefined}
              className={cn("flex h-full min-h-28 w-full flex-col gap-1.5 rounded-lg border bg-card p-3.5 text-left transition-colors hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                station === s.id && "border-2 border-primary shadow-sm")}>
              <span className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
                <Dot state={s.state} />{i + 1}<span className="sr-only">, {STATE_WORDS[s.state]}</span>
              </span>
              <span className="font-semibold">{s.title}</span>
              <span className="text-sm leading-snug text-muted-foreground">{s.line}</span>
            </button>
          </li>
        ))}
      </ol>
      <p className="flex flex-wrap gap-4 text-sm text-muted-foreground">
        {(["done", "attention", "not_started"] as const).map(k => <span key={k} className="inline-flex items-center gap-1.5"><Dot state={k} />{STATE_WORDS[k]}</span>)}
      </p>

      <StationPage snapshot={snapshot} station={station} onEntity={onEntity} onType={onType} />

      {open.length ? (
        <Card className="border-primary/30 bg-secondary">
          <CardHeader><CardTitle>Next at this station</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-4">
            {open.map((o, i) => (
              <div key={i} className="flex flex-col gap-2">
                <p className="text-sm"><strong className="font-semibold">{o.what}</strong>{o.detail ? " " + o.detail : ""}</p>
                <AskAgent live={live} request={"In " + name + ": " + o.what.replace(/\.$/, "") + ". Help me resolve it, at the gates."} />
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function StationPage({ snapshot, station, onEntity, onType }: { snapshot: Snapshot; station: StationId; onEntity: (id: string) => void; onType: (t: string) => void }) {
  switch (station) {
    case "sources": return <Sources s={snapshot} />;
    case "survey": return <Survey s={snapshot} />;
    case "vocabulary": return <Vocabulary s={snapshot} onType={onType} />;
    case "curate": return <Curate s={snapshot} />;
    case "build": return <Build s={snapshot} />;
    case "rules": return <Rules s={snapshot} onEntity={onEntity} />;
    case "test": return <Test s={snapshot} />;
    case "deploy": return <Deploy s={snapshot} />;
  }
}

function Sources({ s }: { s: Snapshot }) {
  const src = s.sources;
  return (
    <div className="flex flex-wrap items-start gap-6">
      <Card className="min-w-0 flex-[999_1_520px]">
        <CardHeader><CardTitle>Documents in the corpus</CardTitle><CardDescription>{src.documents.length} read and kept as Markdown</CardDescription></CardHeader>
        <CardContent>
          {src.documents.length === 0 ? <Empty>No document has been read yet.</Empty> : (
            <ul className="flex flex-col divide-y">
              {src.documents.map(d => <li key={d.slug} className="flex justify-between gap-4 py-2 text-sm"><span>{d.title}</span><span className="font-mono text-xs text-muted-foreground">{d.slug}</span></li>)}
            </ul>
          )}
        </CardContent>
      </Card>
      <div className="flex flex-[1_1_320px] flex-col gap-4">
        <Card>
          <CardHeader><CardTitle>Could not be read</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-3 text-sm">
            {src.errors.length === 0 ? <span className="text-muted-foreground">Nothing.</span> : src.errors.map((e, i) => (
              <div key={i}><strong className="font-medium">{e.file}</strong><br /><span className="text-muted-foreground">{e.reason}</span></div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Waiting</CardTitle></CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {src.inbox.length} in the inbox · {src.processing.length} being worked on · {src.open_runs.length} run{src.open_runs.length === 1 ? "" : "s"} open
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Survey({ s }: { s: Snapshot }) {
  return (
    <Card>
      <CardHeader><CardTitle>Terms decided</CardTitle><CardDescription>{s.survey.accepted} accepted · {s.survey.rejected} rejected, each by a named person</CardDescription></CardHeader>
      <CardContent>
        {s.survey.latest.length === 0 ? <Empty>No term has been decided yet.</Empty> : (
          <Table>
            <TableHeader><TableRow><TableHead>Term</TableHead><TableHead>Decision</TableHead><TableHead>As</TableHead><TableHead>By</TableHead><TableHead>Why</TableHead></TableRow></TableHeader>
            <TableBody>
              {s.survey.latest.map(d => (
                <TableRow key={d.term}>
                  <TableCell className="font-medium">{d.term}</TableCell>
                  <TableCell><Badge variant={d.verdict === "accepted" ? "done" : "muted"}>{d.verdict}</Badge></TableCell>
                  <TableCell>{d.as || "—"}</TableCell>
                  <TableCell>{d.by}, {d.at}</TableCell>
                  <TableCell className="text-muted-foreground">{d.note || ""}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function Vocabulary({ s, onType }: { s: Snapshot; onType: (t: string) => void }) {
  const v = s.vocabulary;
  return (
    <div className="flex flex-wrap items-start gap-6">
      <Card className="min-w-0 flex-[999_1_620px]">
        <CardHeader>
          <CardTitle>Vocabulary{v.accepted ? " · version " + v.version : " · not accepted"}</CardTitle>
          <CardDescription>{v.classes.length} classes · {v.relations} relations · {v.attributes} attributes</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader><TableRow><TableHead>Class</TableHead><TableHead>What it is</TableHead><TableHead className="text-right">Things</TableHead><TableHead>Confirmed by</TableHead></TableRow></TableHeader>
            <TableBody>
              {v.classes.map(c => (
                <TableRow key={c.name}>
                  <TableCell><button type="button" onClick={() => onType(c.name)} className="font-mono text-sm text-primary underline-offset-4 hover:underline">{c.name}</button></TableCell>
                  <TableCell>{c.definition}</TableCell>
                  <TableCell className="text-right tabular-nums">{c.things}</TableCell>
                  <TableCell className={c.validated_by ? "text-done" : "text-attention"}>{c.validated_by || "nobody yet"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <div className="flex flex-[1_1_320px] flex-col gap-4">
        <Card>
          <CardHeader><CardTitle>Made of</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            {v.parts.map(p => <div key={p.name} className="flex justify-between gap-3"><span className="font-mono">{p.name}</span><span className="text-muted-foreground">{[p.release && "@" + p.release, p.origin].filter(Boolean).join(" · ")}</span></div>)}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex-row items-baseline justify-between"><CardTitle>Questions it must answer</CardTitle>
            <span className="text-sm font-semibold text-done">{v.questions.filter(q => q.answered).length} of {v.questions.length}</span></CardHeader>
          <CardContent>
            <ul className="flex flex-col gap-2 text-sm">
              {v.questions.map(q => (
                <li key={q.id} className="flex gap-3">
                  <span className="min-w-9 pt-0.5 font-mono text-xs text-muted-foreground">{q.id}</span>
                  <span className={q.answered ? "" : "text-attention"}>{q.question}{q.answered ? "" : " (not answered)"}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Curate({ s }: { s: Snapshot }) {
  const c = s.curate;
  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <Fact label="Open change" value={c.candidate ? "yes, not applied" : "none"} tone={c.candidate ? "attention" : undefined} />
      <Fact label="Applied changes" value={String(c.changes.length)} />
      <Fact label="Recorded statements" value={String(c.assertions)} />
      <Card className="sm:col-span-3">
        <CardHeader><CardTitle>Applied, newest first</CardTitle></CardHeader>
        <CardContent>
          {c.changes.length === 0 ? <Empty>Nothing has been applied yet.</Empty> : (
            <Table>
              <TableHeader><TableRow><TableHead>When</TableHead><TableHead>By</TableHead><TableHead>Why</TableHead><TableHead>Retired</TableHead></TableRow></TableHeader>
              <TableBody>
                {c.changes.map((e, i) => (
                  <TableRow key={i}>
                    <TableCell className="whitespace-nowrap">{(e.at || "").replace("T", " ").slice(0, 16)}</TableCell>
                    <TableCell>{e.by}</TableCell>
                    <TableCell>{e.note}</TableCell>
                    <TableCell className="font-mono text-xs">{e.retired.map(r => r.id + " → " + (r.superseded_by || "—")).join(", ") || "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Build({ s }: { s: Snapshot }) {
  const b = s.build;
  if (!b.built) return <Empty>Not built yet: nothing can be asked until it is.</Empty>;
  return (
    <div className="grid gap-4 sm:grid-cols-4">
      <Fact label="Current facts" value={String(b.current)} />
      <Fact label="Kept for history" value={String(b.superseded)} />
      <Fact label="Links" value={String(b.links)} />
      <Fact label="Build" value={b.stale ? "older than the graph" : "up to date"} tone={b.stale ? "attention" : undefined} />
    </div>
  );
}

function Rules({ s, onEntity }: { s: Snapshot; onEntity: (id: string) => void }) {
  const r = s.rules;
  return (
    <div className="flex flex-wrap items-start gap-6">
      <Card className="min-w-0 flex-[999_1_520px]">
        <CardHeader><CardTitle>Warnings</CardTitle><CardDescription>What the policies find in the graph as it stands</CardDescription></CardHeader>
        <CardContent className="flex flex-col gap-3">
          {r.findings.length === 0 ? <Empty>No policy finds anything.</Empty> : r.findings.map((f, i) => (
            <div key={i} className="rounded-md border px-3 py-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={f.severity === "blocking" ? "default" : "attention"}>{f.severity}</Badge>
                {f.node ? <button type="button" onClick={() => onEntity(f.node as string)} className="font-medium text-primary underline-offset-4 hover:underline">{f.label || f.node}</button> : null}
              </div>
              <p className="mt-1 text-muted-foreground">{f.message}</p>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card className="flex-[1_1_360px]">
        <CardHeader><CardTitle>Rules</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          {r.rules.length === 0 ? <Empty>No rules declared.</Empty> : r.rules.map(x => (
            <div key={x.id} className="flex flex-col gap-1">
              <span className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs">{x.id}</span><Badge variant="outline">{x.kind}</Badge></span>
              <span className="text-muted-foreground">{x.why}</span>
              <span className={x.validated_by ? "text-done" : "text-attention"}>{x.validated_by ? "Confirmed by " + x.validated_by : "Nobody has confirmed it"}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function pct(n: number, total: number) { return (total ? (n / total) * 100 : 0).toFixed(2) + "%"; }
function signed(x: number | null) { return x == null ? "—" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(3); }

function Test({ s }: { s: Snapshot }) {
  const t = s.test;
  const systems = t.bench ? Object.entries(t.bench.systems) : [];
  const oto = t.bench && t.bench.systems.oto;
  return (
    <div className="flex flex-col gap-4">
      {oto ? (
        <div className="grid gap-3 sm:grid-cols-4">
          <Fact label="oto score" value={signed(oto.score)} note="right +1 · abstained 0 · wrong −1" />
          <Fact label="Precision" value={oto.precision == null ? "—" : oto.precision.toFixed(3)} note="right among answered" />
          <Fact label="Coverage" value={oto.coverage == null ? "—" : oto.coverage.toFixed(3)} note="answered at all" />
          <Fact label="Abstained" value={oto.abstained + " / " + (oto.right + oto.wrong + oto.abstained)} note="refused rather than guessed" />
        </div>
      ) : <Empty>No bench run yet.</Empty>}
      <div className="flex flex-wrap items-start gap-4">
        {systems.length ? (
          <Card className="min-w-0 flex-[999_1_520px]">
            <CardHeader><CardTitle>Answers, strict</CardTitle><CardDescription>Bench of {t.bench!.at}</CardDescription></CardHeader>
            <CardContent className="flex flex-col gap-3">
              {systems.map(([name, x]) => {
                const total = x.right + x.wrong + x.abstained;
                return (
                  <div key={name} className="grid grid-cols-[90px_minmax(0,1fr)_72px] items-center gap-3">
                    <span className="font-mono text-sm">{name}</span>
                    <div className="flex h-5 overflow-hidden rounded bg-muted" role="img" aria-label={name + ": " + x.right + " right, " + x.abstained + " abstained, " + x.wrong + " wrong"}>
                      <div style={{ width: pct(x.right, total), background: "var(--bar-right)" }} />
                      <div style={{ width: pct(x.abstained, total), background: "var(--bar-abstained)" }} />
                      <div style={{ width: pct(x.wrong, total), background: "var(--bar-wrong)" }} />
                    </div>
                    <span className={cn("text-right font-mono", (x.score || 0) >= 0 ? "text-done" : "text-attention")}>{signed(x.score)}</span>
                  </div>
                );
              })}
              <p className="text-sm text-muted-foreground">Green right · grey abstained, no guess · orange wrong</p>
            </CardContent>
          </Card>
        ) : null}
        <Card className="flex-[1_1_340px]">
          <CardHeader><CardTitle>Gold set and feedback</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-3 text-sm">
            {t.gold ? <p>{t.gold.questions} gold questions, written by {t.gold.authored_by || "an unknown author"}; {Math.round((t.gold.audited_fraction || 0) * 100)}% audited by a person.</p> : <p className="text-muted-foreground">No gold set.</p>}
            {t.feedback.map(f => (
              <div key={f.id} className="flex items-start gap-2">
                <Badge variant={f.verdict === "right" ? "done" : f.promoted ? "secondary" : "attention"}>{f.promoted ? "now a test" : f.verdict}</Badge>
                <span>{f.question} <span className="text-muted-foreground">({f.by})</span></span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Deploy({ s }: { s: Snapshot }) {
  const d = s.deploy;
  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <Fact label="Served from" value={d.backend} />
      <Fact label="Build targets" value={d.targets.length ? d.targets.join(", ") : "the defaults"} />
      <Fact label="Published site" value={d.site ? "built" : "not built"} tone={d.site ? undefined : "attention"} />
    </div>
  );
}

function Fact({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: "attention" }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-1 p-4">
        <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
        <span className={cn("font-mono text-2xl", tone === "attention" && "text-attention")}>{value}</span>
        {note ? <span className="text-sm text-muted-foreground">{note}</span> : null}
      </CardContent>
    </Card>
  );
}
