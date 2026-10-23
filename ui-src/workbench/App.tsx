/* The workbench: Overview, Knowledge and Project over one snapshot and one graph. Where the reader is
 * lives in the address (#/overview, #/knowledge/<id>, #/knowledge/kind/<Class>, #/project/<station>),
 * so a link to a page can be shared and the browser's back button works. */
import * as React from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";
import { Badge } from "./components/ui/badge";
import { Empty } from "./components/common";
import { Overview } from "./views/Overview";
import { Knowledge } from "./views/Knowledge";
import { Project } from "./views/Project";
import type { StationId } from "./types";
import { follow, load, type Loaded } from "./data";

type Route = { section: "overview" | "knowledge" | "project"; entity: string | null; kind: string | null; station: StationId };
const STATIONS: StationId[] = ["sources", "survey", "vocabulary", "curate", "build", "rules", "test", "deploy"];

function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  const route: Route = { section: "overview", entity: null, kind: null, station: "vocabulary" };
  if (parts[0] === "knowledge") {
    route.section = "knowledge";
    if (parts[1] === "kind") route.kind = parts[2] || null;
    else route.entity = parts[1] || null;
  } else if (parts[0] === "project") {
    route.section = "project";
    if (STATIONS.includes(parts[1] as StationId)) route.station = parts[1] as StationId;
  }
  return route;
}

function href(r: Partial<Route> & { section: Route["section"] }) {
  if (r.section === "knowledge") return "#/knowledge" + (r.entity ? "/" + encodeURIComponent(r.entity) : r.kind ? "/kind/" + encodeURIComponent(r.kind) : "");
  if (r.section === "project") return "#/project/" + (r.station || "vocabulary");
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
              <TabsTrigger value="project">Project</TabsTrigger>
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
              onEntity={id => go({ section: "knowledge", entity: id })} onKind={k => go({ section: "knowledge", kind: k })} />
          </TabsContent>
          <TabsContent value="project" className="mt-0">
            {s ? <Project snapshot={s} live={data.live} station={route.station} onStation={st => go({ section: "project", station: st })}
              onEntity={id => go({ section: "knowledge", entity: id })} onType={k => go({ section: "knowledge", kind: k })} />
              : <Empty>No project snapshot here: this copy carries the graph only.</Empty>}
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
