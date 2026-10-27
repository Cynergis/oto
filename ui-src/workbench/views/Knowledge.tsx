/* Knowledge: what the graph knows. Browse by kind or search, read one thing with its history and
 * evidence (the reader's pages), or see it all as a graph (the explorer, mounted as a component). */
import * as React from "react";
import { Search } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { Empty } from "../components/common";
import type { EntityLinks, GraphEdge, GraphNode, LinkTarget, Payload } from "../types";
import { linksOf } from "../links";
import { cn } from "../lib/utils";
import { Explorer } from "../../explorer/explorer.jsx";
import adapter from "../../explorer/adapter.js";
import defaults from "../../explorer/defaults.js";

type Props = { payload: Payload | null; selected: string | null; kind: string | null; onEntity: (id: string | null) => void; onKind: (k: string | null) => void; onGo?: (target: LinkTarget) => void };

function words(name: string) {
  return name.replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2").replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ").toLowerCase();
}
function fmt(v: unknown): string {
  if (v == null || v === "") return "—";
  if (Array.isArray(v)) return v.map(fmt).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function Knowledge({ payload, selected, kind, onEntity, onKind, onGo }: Props) {
  const [query, setQuery] = React.useState("");
  const index = React.useMemo(() => {
    const byId: Record<string, GraphNode> = {};
    const out: Record<string, GraphEdge[]> = {}, inn: Record<string, GraphEdge[]> = {};
    for (const n of payload?.nodes || []) byId[n.id] = n;
    for (const e of payload?.edges || []) { (out[e.from] ||= []).push(e); (inn[e.to] ||= []).push(e); }
    return { byId, out, inn };
  }, [payload]);
  const graph = React.useMemo(() => payload ? { full: adapter.toGraph(payload), d: defaults.fromVocabulary(payload.vocabulary, {}) } : null, [payload]);

  if (!payload) return <Empty>No graph to read: build the project first, then serve or export it.</Empty>;

  const current = payload.nodes.filter(n => n.status === "current");
  const kinds = Object.keys(payload.vocabulary.classes || {}).map(k => ({ k, n: current.filter(x => x.type === k).length })).filter(x => x.n > 0);
  const q = query.trim().toLowerCase();
  const listed = q
    ? payload.nodes.filter(n => [n.id, n.label, n.summary, ...(n.aliases || [])].some(t => (t || "").toLowerCase().includes(q)))
    : current.filter(n => !kind || n.type === kind);
  const node = selected ? index.byId[selected] : null;

  return (
    <Tabs defaultValue="browse">
      <TabsList><TabsTrigger value="browse">Browse</TabsTrigger><TabsTrigger value="graph">Graph</TabsTrigger></TabsList>
      <TabsContent value="browse">
        <div className="flex flex-wrap items-start gap-6">
          <nav aria-label="Kinds of thing" className="flex flex-[1_1_220px] flex-col gap-1">
            <label className="relative mb-2 block">
              <span className="sr-only">Search the knowledge base</span>
              <Search aria-hidden="true" className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search names, aliases, summaries"
                className="h-10 w-full rounded-md border border-input bg-card pl-9 pr-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
            </label>
            <KindButton active={!kind && !q} onClick={() => { setQuery(""); onKind(null); }} label="Everything current" n={current.length} />
            {kinds.map(({ k, n }) => <KindButton key={k} active={kind === k && !q} onClick={() => { setQuery(""); onKind(k); }} label={words(k)} n={n} />)}
          </nav>

          <Card className="min-w-0 flex-[2_1_300px]">
            <CardHeader><CardTitle>{q ? "Matching “" + query + "”" : kind ? words(kind) : "Everything current"}</CardTitle><CardDescription>{listed.length} shown</CardDescription></CardHeader>
            <CardContent className="flex flex-col gap-1">
              {listed.length === 0 ? <Empty>Nothing matches.</Empty> : listed.map(n => (
                <button key={n.id} type="button" onClick={() => onEntity(n.id)} aria-current={selected === n.id ? "true" : undefined}
                  className={cn("flex items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", selected === n.id && "bg-secondary")}>
                  <span className={cn("font-medium", n.status !== "current" && "text-muted-foreground line-through")}>{n.label}</span>
                  <span className="text-xs text-muted-foreground">{words(n.type)}</span>
                </button>
              ))}
            </CardContent>
          </Card>

          <div className="min-w-0 flex-[3_1_420px]">
            {node ? <Entity node={node} index={index} onEntity={onEntity} links={linksOf(payload, node.id)} onGo={onGo} /> : <Empty>Choose a thing to read what is known about it, where it came from, and how it changed.</Empty>}
          </div>
        </div>
      </TabsContent>
      <TabsContent value="graph">
        <div className="flex h-[72vh] min-h-[480px] flex-col overflow-hidden rounded-lg border bg-card p-3">
          {graph ? <Explorer full={graph.full} defaults={graph.d} /> : null}
        </div>
      </TabsContent>
    </Tabs>
  );
}

function KindButton({ active, onClick, label, n }: { active: boolean; onClick: () => void; label: string; n: number }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={active}
      className={cn("flex min-h-10 items-center justify-between gap-2 rounded-md px-3 text-left text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring first-letter:uppercase", active && "bg-secondary font-semibold text-secondary-foreground")}>
      <span className="first-letter:uppercase">{label}</span><span className="font-mono text-xs text-muted-foreground">{n}</span>
    </button>
  );
}

function Entity({ node, index, onEntity, links, onGo }: { node: GraphNode; index: { byId: Record<string, GraphNode>; out: Record<string, GraphEdge[]>; inn: Record<string, GraphEdge[]> }; onEntity: (id: string) => void; links: EntityLinks | null; onGo?: (target: LinkTarget) => void }) {
  const link = (id: string | null) => id && index.byId[id]
    ? <button type="button" onClick={() => onEntity(id)} className="text-primary underline-offset-4 hover:underline">{index.byId[id].label}</button>
    : <span className="font-mono">{id || "—"}</span>;
  const attributes = Object.entries(node.attributes || {});
  const out = index.out[node.id] || [], inn = index.inn[node.id] || [];
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="capitalize">{words(node.type)}</Badge>
          <Badge variant={node.status === "current" ? "done" : "muted"}>{node.status}</Badge>
          <span className="font-mono text-xs text-muted-foreground">{node.id}</span>
        </div>
        <CardTitle className="text-2xl">{node.label}</CardTitle>
        {node.summary ? <CardDescription className="text-base">{node.summary}</CardDescription> : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-5 text-sm">
        <p className="text-muted-foreground">
          True from {node.valid_from || "?"}{node.valid_to ? " until " + node.valid_to : ""} · recorded {node.as_of || "?"}
        </p>
        {node.superseded_by ? <p className="rounded-md bg-attention-soft px-3 py-2 text-attention">Replaced by {link(node.superseded_by)} from {node.valid_to}. Kept for history.</p> : null}
        {node.supersedes ? <p className="rounded-md bg-secondary px-3 py-2">Replaces {[node.supersedes].flat().map((id, i) => <React.Fragment key={id}>{i ? ", " : ""}{link(id)}</React.Fragment>)}</p> : null}
        {attributes.length ? (
          <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-x-4 gap-y-1">
            {attributes.map(([k, v]) => <React.Fragment key={k}><dt className="text-muted-foreground">{words(k)}</dt><dd className="font-mono">{fmt(v)}</dd></React.Fragment>)}
          </dl>
        ) : null}
        {out.length || inn.length ? (
          <div className="flex flex-col gap-1">
            <h4 className="font-semibold">Links</h4>
            {out.map((e, i) => <p key={"o" + i}>{words(e.rel)} → {link(e.to)}{e.derived_by ? <Badge variant="muted" className="ml-2">derived</Badge> : null}</p>)}
            {inn.map((e, i) => <p key={"i" + i}>{link(e.from)} → {words(e.rel)} this{e.derived_by ? <Badge variant="muted" className="ml-2">derived</Badge> : null}</p>)}
          </div>
        ) : null}
        {links && onGo ? <Related links={links} onGo={onGo} /> : null}
        <div className="flex flex-col gap-2">
          <h4 className="font-semibold">Where it came from</h4>
          {(node.evidence || []).length === 0 ? <p className="text-attention">No evidence quoted: a fact nobody can locate is not checkable.</p> : node.evidence.map((ev, i) => (
            <figure key={i} className="rounded-md border-l-4 border-primary/50 bg-muted px-3 py-2">
              {ev.quote ? <blockquote className="leading-relaxed">“{ev.quote}”</blockquote> : null}
              <figcaption className="mt-1 text-xs text-muted-foreground">{ev.doc}{ev.where ? " · " + ev.where : ""}</figcaption>
            </figure>
          ))}
          {node.sources?.length ? <p className="text-xs text-muted-foreground">Sources: {node.sources.join(", ")}</p> : null}
        </div>
      </CardContent>
    </Card>
  );
}

/* Cross-artifact navigation (roadmap D5): the rules that apply to this thing's class, the terms and
 * words that name it, the graphs whose descriptor covers it, the decisions about it, the files behind it. */
function Related({ links, onGo }: { links: EntityLinks; onGo: (target: LinkTarget) => void }) {
  const go = (target: LinkTarget | null, text: React.ReactNode, key: string) => target
    ? <button key={key} type="button" onClick={() => onGo(target)} className="text-primary underline-offset-4 hover:underline">{text}</button>
    : <span key={key}>{text}</span>;
  const row = (label: string, items: React.ReactNode[], empty: string) => (
    <React.Fragment key={label}>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="flex flex-wrap items-center gap-x-2 gap-y-1">{items.length ? items : <span className="text-muted-foreground">{empty}</span>}</dd>
    </React.Fragment>
  );
  return (
    <div className="flex flex-col gap-2">
      <h4 className="font-semibold">Related</h4>
      <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,3fr)] gap-x-4 gap-y-1.5">
        {row("Rules", links.rules.map(r => go(r.target, <span><span className="font-mono text-xs">{r.id}</span>{r.via ? <span className="text-xs text-muted-foreground"> through {words(r.via)}</span> : null}</span>, "r:" + r.id)),
          "no rule applies to a " + words(links.type))}
        {row("Terms", links.terms.map(t => t.kind === "class"
          ? go(t.target, <span>class <span className="first-letter:uppercase">{t.label}</span></span>, "t:class")
          : go(t.target, <span>people say “{t.phrase}”</span>, "t:" + t.phrase)), "")}
        {row("Graphs", links.graphs.map(g => go(g.target, <span>{g.label || g.id}{g.own ? <span className="text-xs text-muted-foreground"> (this graph)</span> : null}</span>, "g:" + g.id)),
          "no descriptor says it holds a " + words(links.type))}
        {row("Decisions", links.decisions.map(d => go(d.target, <span>{d.label || d.id}<span className="text-xs text-muted-foreground"> {d.direction === "in" ? words(d.rel) + " this" : "this " + words(d.rel) + " it"}{d.status ? " · " + String(d.status) : ""}</span></span>, "d:" + d.id)),
          "no decision is about it")}
        {row("Files", links.files.map((f, i) => (
          <span key={"f:" + i} className="inline-flex flex-wrap items-center gap-1">
            <Badge variant="outline">{f.kind}</Badge>
            {go(f.target, f.label || f.where || f.id, "fl:" + i)}
            {f.where && /^https?:\/\//.test(f.where) ? <a href={f.where} target="_blank" rel="noopener noreferrer" className="font-mono text-xs text-muted-foreground underline-offset-4 hover:underline">{f.where}</a>
              : f.where && f.where !== f.label ? <span className="font-mono text-xs text-muted-foreground">{f.where}</span> : null}
          </span>)), "no repository, code, commit or document behind it")}
      </dl>
    </div>
  );
}
