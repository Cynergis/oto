/* The workbench: Overview, Knowledge, Ontology, Project and, when the vocabulary has work items, Work,
 * over one snapshot and one graph. Where the reader is lives in the address (#/overview, #/knowledge/<id>,
 * #/knowledge/kind/<Class>, #/ontology/<Class>, #/ontology/rules/<Class>, #/ontology/lexicon/<words>,
 * #/ontology/dependencies/<graph>, #/project/<station>, #/work), so a link to a page can be shared and the browser's back button works. */
import * as React from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";
import { Badge } from "./components/ui/badge";
import { Empty } from "./components/common";
import { Overview } from "./views/Overview";
import { Knowledge } from "./views/Knowledge";
import { Ontology } from "./views/Ontology";
import { Rules } from "./views/Rules";
import { Lexicon } from "./views/Lexicon";
import { Dependencies } from "./views/Dependencies";
import { Project } from "./views/Project";
import { Work } from "./views/Work";
import type { LinkTarget, StationId } from "./types";
import { follow, load, type Loaded } from "./data";

type OntologyView = "classes" | "rules" | "lexicon" | "dependencies";
type Route = { section: "overview" | "knowledge" | "ontology" | "project" | "work"; entity: string | null; kind: string | null; klass: string | null; view: OntologyView; term: string; graph: string | null; station: StationId };
const STATIONS: StationId[] = ["sources", "survey", "vocabulary", "curate", "build", "rules", "test", "deploy"];

function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  const route: Route = { section: "overview", entity: null, kind: null, klass: null, view: "classes", term: "", graph: null, station: "vocabulary" };
  if (parts[0] === "knowledge") {
    route.section = "knowledge";
    if (parts[1] === "kind") route.kind = parts[2] || null;
    else route.entity = parts[1] || null;
  } else if (parts[0] === "ontology") {
    route.section = "ontology";
    if (parts[1] === "rules") { route.view = "rules"; route.klass = parts[2] || null; }
    else if (parts[1] === "lexicon") { route.view = "lexicon"; route.term = parts.slice(2).join("/"); }
    else if (parts[1] === "dependencies") { route.view = "dependencies"; route.graph = parts[2] || null; }
    else route.klass = parts[1] || null;
  } else if (parts[0] === "project") {
    route.section = "project";
    if (STATIONS.includes(parts[1] as StationId)) route.station = parts[1] as StationId;
  } else if (parts[0] === "work") {
    route.section = "work";
  }
  return route;
}

function href(r: Partial<Route> & { section: Route["section"] }) {
  if (r.section === "knowledge") return "#/knowledge" + (r.entity ? "/" + encodeURIComponent(r.entity) : r.kind ? "/kind/" + encodeURIComponent(r.kind) : "");
  if (r.section === "ontology") {
    if (r.view === "rules") return "#/ontology/rules" + (r.klass ? "/" + encodeURIComponent(r.klass) : "");
    if (r.view === "lexicon") return "#/ontology/lexicon" + (r.term ? "/" + encodeURIComponent(r.term) : "");
    if (r.view === "dependencies") return "#/ontology/dependencies" + (r.graph ? "/" + encodeURIComponent(r.graph) : "");
    return "#/ontology" + (r.klass ? "/" + encodeURIComponent(r.klass) : "");
  }
  if (r.section === "project") return "#/project/" + (r.station || "vocabulary");
  if (r.section === "work") return "#/work";
  return "#/overview";
}

export function App() {
  const [data, setData] = React.useState<Loaded | null>(null);
  const [route, setRoute] = React.useState<Route>(() => parse(window.location.hash));
  const latest = React.useRef<Loaded | null>(null);
  latest.current = data;

  React.useEffect(() => {
    const onHash = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  React.useEffect(() => {
    let stop = () => {};
    const refresh = () => load().then(d => { setData(d); return d; });
    refresh().then(() => { stop = follow(() => latest.current as Loaded, refresh); });
    return () => stop();
  }, []);
  React.useEffect(() => {
    const name = data?.snapshot?.project.name || data?.payload?.project.name;
    if (name) document.title = name + " · workbench";
  }, [data]);

  const go = (r: Partial<Route> & { section: Route["section"] }) => { window.location.hash = href(r); };
  const goTo = (t: LinkTarget) => {
    if (t.section === "knowledge") go({ section: "knowledge", entity: t.entity || null });
    else if (t.section === "rules") go({ section: "ontology", view: "rules", klass: t.class || null });
    else if (t.section === "lexicon") go({ section: "ontology", view: "lexicon", term: t.query || "" });
    else if (t.section === "dependencies") go({ section: "ontology", view: "dependencies", graph: t.graph || null });
    else go({ section: "ontology", klass: t.class || null });
  };
  if (!data) return <p className="p-10 text-muted-foreground">Loading…</p>;
  const s = data.snapshot;
  const name = s?.project.name || data.payload?.project.name || "OTO";

  return (
    <div className="min-h-screen">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-[1360px] flex-wrap items-center gap-x-8 gap-y-3 px-5 py-3 sm:px-10">
          <span className="text-lg font-bold">{name}</span>
          <Tabs value={route.section} onValueChange={v => go({ section: v as Route["section"], station: route.station })} className="flex-1">
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="knowledge">Knowledge</TabsTrigger>
              <TabsTrigger value="ontology">Ontology</TabsTrigger>
              <TabsTrigger value="project">Project</TabsTrigger>
              {s?.work ? <TabsTrigger value="work">Work{s.work.counts.blocked ? <span className="ml-1.5 rounded-full bg-attention/15 px-1.5 text-xs text-attention">{s.work.counts.blocked}</span> : null}</TabsTrigger> : null}
            </TabsList>
          </Tabs>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {data.live
              ? <Badge variant="done"><svg width="8" height="8" aria-hidden="true"><circle cx="4" cy="4" r="4" fill="var(--done-dot)" /></svg>Live{s ? " · " + s.token.slice(0, 6) : ""}</Badge>
              : <Badge variant="secondary">Published copy</Badge>}
            <Badge variant="outline">Read-only</Badge>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1360px] px-5 pb-16 pt-8 sm:px-10">
        {data.problem ? <Empty>{data.problem}</Empty> : null}
        <Tabs value={route.section}>
          <TabsContent value="overview" className="mt-0">
            {s ? <Overview snapshot={s} onOpen={st => go({ section: "project", station: st as StationId })} /> : <Empty>No project snapshot here: this copy carries the graph only.</Empty>}
          </TabsContent>
          <TabsContent value="knowledge" className="mt-0">
            <Knowledge payload={data.payload} selected={route.entity} kind={route.kind}
              onEntity={id => go({ section: "knowledge", entity: id })} onKind={k => go({ section: "knowledge", kind: k })} onGo={goTo} />
          </TabsContent>
          <TabsContent value="ontology" className="mt-0">
            <Tabs value={route.view} onValueChange={v => go({ section: "ontology", view: v as OntologyView, klass: v === "lexicon" ? null : route.klass })} className="mb-6">
              <TabsList>
                <TabsTrigger value="classes">Classes</TabsTrigger>
                <TabsTrigger value="rules">Rules</TabsTrigger>
                <TabsTrigger value="lexicon">Lexicon</TabsTrigger>
                <TabsTrigger value="dependencies">Dependencies{data.payload?.graphs?.counts.near_duplicates ? <span className="ml-1.5 rounded-full bg-attention/15 px-1.5 text-xs text-attention">{data.payload.graphs.counts.near_duplicates}</span> : null}</TabsTrigger>
              </TabsList>
            </Tabs>
            {route.view === "rules" ? (
              <Rules model={data.payload?.rules || null} ontology={data.payload?.ontology || null} klass={route.klass}
                onPick={k => go({ section: "ontology", view: "rules", klass: k })} onClass={k => go({ section: "ontology", klass: k })} />
            ) : route.view === "dependencies" ? (
              <Dependencies model={data.payload?.graphs || null} ontology={data.payload?.ontology || null} selected={route.graph}
                onPick={id => go({ section: "ontology", view: "dependencies", graph: id })} onClass={k => go({ section: "ontology", klass: k })} />
            ) : route.view === "lexicon" ? (
              <Lexicon model={data.payload?.terms || null} ontology={data.payload?.ontology || null} query={route.term}
                onQuery={q => go({ section: "ontology", view: "lexicon", term: q })}
                onClass={k => go({ section: "ontology", klass: k })} onEntity={id => go({ section: "knowledge", entity: id })} />
            ) : (
              <Ontology model={data.payload?.ontology || null} selected={route.klass} rules={data.payload?.rules || null}
                onClass={k => go({ section: "ontology", klass: k })} onKind={k => go({ section: "knowledge", kind: k })}
                onRules={k => go({ section: "ontology", view: "rules", klass: k })} />
            )}
          </TabsContent>
          <TabsContent value="project" className="mt-0">
            {s ? <Project snapshot={s} live={data.live} station={route.station} onStation={st => go({ section: "project", station: st })}
              onEntity={id => go({ section: "knowledge", entity: id })} onType={k => go({ section: "knowledge", kind: k })} />
              : <Empty>No project snapshot here: this copy carries the graph only.</Empty>}
          </TabsContent>
          <TabsContent value="work" className="mt-0">
            {s?.work ? <Work board={s.work} published={s.published} live={data.live} onEntity={id => go({ section: "knowledge", entity: id })} />
              : <Empty>This vocabulary has no work items; the board needs the work ontology.</Empty>}
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
