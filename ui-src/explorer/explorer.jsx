/* The graph explorer: a columnar React Flow canvas, a legend of class chips that filter, hover to
 * light a neighbourhood, click for the detail panel, expand to the full window. Ported from the
 * Ascent prototype's reusable GraphExplorer (D-042) and made vocabulary-driven: the columns, the
 * palette and what counts as evidenceable come from `defaults.js`, and the detail panel shows
 * what an OTO node carries: provenance, attributes, evidence quotes, derived edges with their rule
 * and premises, history.
 */
import React from "react";
import { ReactFlow, ReactFlowProvider, Handle, Position, Controls, useReactFlow } from "@xyflow/react";
import adapter from "./adapter.js";

const NODE_W = 172, NODE_H = 46, COL_PITCH = 236, ROW_PITCH = 58, PAD = 24;

const ICONS = {
  doc: <path d="M4 2.5h5l3 3v8H4zM9 2.5V5.5h3" />,
  check: <path d="M3.5 8.5l3 3 6-6.5" />,
  warn: <path d="M8 2.5 14 13H2zM8 6.5v3M8 11h.01" />,
  user: <path d="M8 8a2.6 2.6 0 1 0 0-5.2 2.6 2.6 0 0 0 0 5.2M3 13.5c.5-2.4 2.5-4 5-4s4.5 1.6 5 4" />,
  metric: <path d="M2.5 11.5a5.5 5.5 0 1 1 11 0M8 8l2.6-2.2" />,
  journey: <path d="M3 13s0-4 5-4 5-4 5-4M3 6.5h.01M13 9.5h.01" />,
  graph: <path d="M4 4.5h3.5v3.5H4zM10 8h2.5v3.5H10zM5.7 8v2.2a1 1 0 0 0 1 1H10" />,
  policy: <path d="M8 2.2 3 4.2v3.3c0 3 2.1 5 5 6.3 2.9-1.3 5-3.3 5-6.3V4.2zM6 8l1.5 1.5L10.5 6.5" />,
  usecase: <path d="M8 2 2.8 4.8v6.4L8 14l5.2-2.8V4.8z M2.8 4.8 8 7.6l5.2-2.8M8 7.6V14" />,
  x: <path d="M4 4l8 8M12 4l-8 8" />,
  expand: <path d="M9.5 2.5H13.5V6.5M13.5 2.5 9 7M6.5 13.5H2.5V9.5M2.5 13.5 7 9" />,
  collapse: <path d="M13 3 9.5 6.5M9.5 6.5V3.5M9.5 6.5H13M3 13 6.5 9.5M6.5 9.5V13M6.5 9.5H3" />,
};
export function Ico({ k, w = 16 }) {
  return <svg width={w} height={w} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">{ICONS[k] || ICONS.usecase}</svg>;
}

/* ---- layout: one column per class group, rows centred ---- */
export function layout(g, columns) {
  const cols = [];
  columns.forEach(group => { const ns = g.nodes.filter(n => group.includes(n.type)); if (ns.length) cols.push(ns); });
  const stray = g.nodes.filter(n => !columns.some(group => group.includes(n.type)));
  if (stray.length) cols.push(stray);
  const pos = {}; let maxRows = 0;
  cols.forEach((ns, ci) => { maxRows = Math.max(maxRows, ns.length); ns.forEach((n, ri) => { pos[n.id] = { x: PAD + ci * COL_PITCH, y: PAD + ri * ROW_PITCH }; }); });
  cols.forEach(ns => { const off = (maxRows - ns.length) * ROW_PITCH / 2; ns.forEach(n => { pos[n.id].y += off; }); });
  return { pos, cols };
}

const HANDLE = { opacity: 0, width: 1, height: 1, minWidth: 1, minHeight: 1, border: 0, background: "transparent" };
function GNode({ data }) {
  const { n, dim, sel, assumed, colour, icon } = data;
  return (
    <div className={"mx-gnode" + (sel ? " sel" : "") + (dim ? " dim" : "") + (assumed ? " assumed" : "") + (n.status !== "current" ? " " + n.status : "") + (n.pending ? " pending" : "")}
      style={{ width: NODE_W, height: NODE_H, "--gc": colour }} title={n.id + (n.pending ? " · pending: " + n.pending.station : "")}>
      <Handle id="tl" type="target" position={Position.Left} style={HANDLE} />
      <Handle id="tr" type="target" position={Position.Right} style={HANDLE} />
      <Handle id="sl" type="source" position={Position.Left} style={HANDLE} />
      <Handle id="sr" type="source" position={Position.Right} style={HANDLE} />
      <span className="mx-gnode-ico"><Ico k={icon} w={12} /></span>
      <span className="mx-gnode-txt">
        <span className="ty">{n.type}{n.pending && <span className="mx-gnode-flag pending">{n.pending.station}</span>}{assumed && !n.pending && <span className="mx-gnode-flag">unsourced</span>}{n.status !== "current" && <span className="mx-gnode-flag">{n.status}</span>}{n.attributes && n.attributes.last_run && <span className="mx-gnode-flag ran" title={"last run " + n.attributes.last_run.at + " on " + n.attributes.last_run.on + " by " + n.attributes.last_run.by}>ran {n.attributes.last_run.at}</span>}</span>
        <span className="lb">{n.label}</span>
      </span>
    </div>
  );
}
const NODE_TYPES = { mx: GNode };

function edgeStyle(dash, dim, lit, pending) {
  return {
    stroke: lit ? "var(--accent)" : pending ? "var(--warn)" : dash ? "var(--derived)" : "var(--edge)",
    strokeWidth: lit ? 1.9 : 1.4,
    strokeDasharray: dash ? "4 3" : pending ? "2 4" : undefined,
    opacity: dim ? 0.12 : 1,
  };
}

function Canvas({ g, L, sel, setSel, hover, setHover, typeFilter, expanded, meta, evidenceable }) {
  const rf = useReactFlow();
  React.useEffect(() => { const id = setTimeout(() => rf.fitView({ padding: 0.2 }), 140); return () => clearTimeout(id); }, [expanded, g, rf]);
  const focusId = hover || sel;
  const nbr = React.useMemo(() => new Set(focusId ? adapter.neighbors(g, focusId).map(n => n.id) : []), [g, focusId]);
  const active = id => !focusId || id === focusId || nbr.has(id);
  const edgeActive = e => !focusId || e.from === focusId || e.to === focusId;
  const rfNodes = React.useMemo(() => g.nodes.map(n => {
    const p = L.pos[n.id]; const ty = meta[n.type] || { colour: "oklch(0.5 0.02 260)", icon: "usecase" };
    return { id: n.id, type: "mx", position: p, width: NODE_W, height: NODE_H,
             data: { n, dim: (typeFilter && n.type !== typeFilter) || !active(n.id), sel: sel === n.id,
                     assumed: adapter.assumed(n, evidenceable), colour: ty.colour, icon: ty.icon } };
  }), [g, L, focusId, typeFilter, sel, meta, evidenceable]);
  const rfEdges = React.useMemo(() => g.edges.map((e, i) => {
    const a = L.pos[e.from], b = L.pos[e.to];
    const dim = (typeFilter && !(g.byId[e.from].type === typeFilter || g.byId[e.to].type === typeFilter)) || !edgeActive(e);
    const forward = b.x >= a.x;
    return { id: "e" + i, source: e.from, target: e.to, sourceHandle: forward ? "sr" : "sl", targetHandle: forward ? "tl" : "tr",
             type: "default", style: edgeStyle(e.dash, dim, !!focusId && edgeActive(e), !!e.pending), label: focusId && edgeActive(e) ? (e.pending ? e.rel + " · " + e.pending.station : e.rel) : undefined,
             labelStyle: { fill: "var(--muted)", fontSize: 10 }, labelBgStyle: { fill: "var(--surface)" } };
  }), [g, L, focusId, typeFilter]);
  return (
    <ReactFlow nodes={rfNodes} edges={rfEdges} nodeTypes={NODE_TYPES}
      onNodeMouseEnter={(_, nd) => setHover(nd.id)} onNodeMouseLeave={() => setHover(null)}
      onNodeClick={(_, nd) => setSel(nd.id)} onPaneClick={() => setSel(null)}
      fitView fitViewOptions={{ padding: 0.2 }} minZoom={0.15} maxZoom={1.8}
      nodesConnectable={false} nodesDraggable elementsSelectable proOptions={{ hideAttribution: true }} panOnScroll zoomOnScroll={false}>
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

/* ---- the detail panel: what an OTO node carries ---- */
function fmt(v) { if (v == null || v === "") return ""; if (Array.isArray(v)) return v.map(fmt).join(", "); if (typeof v === "object") return JSON.stringify(v); return String(v); }

export function Detail({ g, full, node, onSelect, meta, evidenceable }) {
  const ty = meta[node.type] || { label: node.type, colour: "oklch(0.5 0.02 260)" };
  const ns = adapter.neighbors(full, node.id);
  const byLabel = {};
  ns.forEach(nb => { (byLabel[nb.label] = byLabel[nb.label] || []).push(nb); });
  const attrs = Object.keys(node.attributes || {}).filter(k => { const v = node.attributes[k]; return v !== null && v !== "" && !(Array.isArray(v) && !v.length); });
  const isAssumed = adapter.assumed(node, evidenceable);
  const preds = full.nodes.filter(m => m.superseded_by === node.id);
  return (
    <div className="mx-gd">
      <div className="mx-gd-head" style={{ "--gc": ty.colour }}>
        <span className="mx-gd-type"><span className="dot"></span>{ty.label}</span>
        <div className="mx-gd-name">{node.label}</div>
        <div className="mx-gd-id">{node.id}</div>
      </div>
      {node.pending && <div className="mx-gd-pending"><span className="mx-flag pending">{node.pending.station} · {node.pending.verdict}</span> Not yet believed: {node.pending.verdict === "new" ? "this entity would be added" : node.pending.verdict === "retire" ? "this entity would be retired" : "this entity would change"} from <code>{node.pending.source}</code>.{node.pending.reason ? " " + node.pending.reason : ""}</div>}
      <div className="mx-gd-prov">
        <span>status={node.status || "current"}</span>
        {node.as_of && <span>as_of={node.as_of}</span>}
        {node.valid_from && <span>valid_from={node.valid_from}</span>}
        {node.valid_to && <span>valid_to={node.valid_to}</span>}
        {node.source_doc && <span>source_doc={node.source_doc}</span>}
      </div>
      {node.summary && <p className="mx-gd-desc">{node.summary}</p>}
      {(node.aliases || []).length > 0 && <p className="mx-gd-muted">aka {node.aliases.join(", ")}</p>}
      {attrs.length > 0 && (
        <div className="mx-gd-sect"><div className="mx-gd-sh">Attributes</div>
          <dl className="mx-gd-attrs">{attrs.map(k => <React.Fragment key={k}><dt>{k}</dt><dd>{fmt(node.attributes[k])}</dd></React.Fragment>)}</dl>
        </div>)}
      <div className="mx-gd-sect">
        <div className="mx-gd-sh">{isAssumed ? "Evidence" : "Evidence (" + ((node.evidence || []).length) + ")"}</div>
        {isAssumed && <div className="mx-gd-assumed"><span className="mx-flag">unsourced</span> No document is cited for this entity, so nothing about it can be checked.</div>}
        {(node.evidence || []).map((e, i) => (
          <blockquote className="mx-gd-ev" key={i}>{e.quote || <span className="mx-gd-muted">no quote</span>}<span className="where">{e.doc}{e.where ? " · " + e.where : ""}</span></blockquote>))}
        {!isAssumed && !(node.evidence || []).length && (node.sources || []).length > 0 && <div className="mx-gd-muted">Sources: {node.sources.join(", ")}</div>}
      </div>
      {(preds.length > 0 || node.superseded_by) && (
        <div className="mx-gd-sect"><div className="mx-gd-sh">History</div>
          {node.superseded_by && full.byId[node.superseded_by] && <button className="mx-gd-nb" onClick={() => onSelect(node.superseded_by)}><span className="nl">Superseded by {full.byId[node.superseded_by].label}</span><span className="dir">→</span></button>}
          {preds.map(m => <button className="mx-gd-nb" key={m.id} onClick={() => onSelect(m.id)}><span className="nl">Supersedes {m.label}</span><span className="mx-gd-muted"> valid {m.valid_from || "?"} → {m.valid_to || "?"}</span></button>)}
        </div>)}
      <div className="mx-gd-sect">
        <div className="mx-gd-sh">Connections ({ns.length})</div>
        {ns.length === 0 && <div className="mx-gd-muted">No edges.</div>}
        {Object.keys(byLabel).sort().map(label => (
          <div className="mx-gd-grp" key={label}>
            <div className="mx-gd-kl">{label}</div>
            {byLabel[label].map((nb, i) => {
              const tn = full.byId[nb.id]; if (!tn) return null;
              const tm = meta[tn.type] || {};
              return (
                <div key={i}>
                  <button className={"mx-gd-nb" + (g.byId[nb.id] ? "" : " outside")} onClick={() => onSelect(nb.id)} style={{ "--gc": tm.colour }}>
                    <span className="dot"></span><span className="nl">{tn.label}</span>
                    {nb.edge.dash && <span className="mx-flag derived">derived by {nb.edge.derived_by}</span>}
                    {nb.edge.pending && <span className="mx-flag pending">{nb.edge.pending.station}</span>}
                    <span className="dir">{nb.dir === "out" ? "→" : "←"}</span>
                  </button>
                  {nb.edge.dash && nb.edge.premises && nb.edge.premises.length > 0 && (
                    <details className="mx-gd-premises"><summary>rests on {nb.edge.premises.length}</summary>
                      <ul>{nb.edge.premises.map((p, j) => <li key={j}>{p}</li>)}</ul></details>)}
                </div>);
            })}
          </div>))}
      </div>
    </div>
  );
}

/* ---- the explorer ---- */
export function Explorer({ full, defaults, title }) {
  const { columns, typeMeta: meta, evidenceable, threshold, hops } = defaults;
  const focusMode = full.nodes.length > threshold;
  const [sel, setSel] = React.useState(null);
  const [hover, setHover] = React.useState(null);
  const [typeFilter, setTypeFilter] = React.useState(null);
  const [expanded, setExpanded] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [focus, setFocus] = React.useState(null);
  React.useEffect(() => {
    if (!expanded) return;
    const onKey = e => { if (e.key === "Escape") setExpanded(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded]);
  // Inside a frame (the catalog embeds the explorer), "the full window" is the parent's: tell
  // it, and it grows the frame; nothing happens when the explorer is the page.
  React.useEffect(() => {
    if (window.parent === window) return;
    try { window.parent.postMessage({ oto: "explorer", expanded }, "*"); } catch (e) { /* a parent that will not listen */ }
  }, [expanded]);

  const g = React.useMemo(() => {
    if (!focusMode) return full;
    if (!focus) return adapter.subgraph(full, []);
    return adapter.subgraph(full, adapter.neighbourhood(full, focus, hops));
  }, [full, focusMode, focus, hops]);
  const L = React.useMemo(() => layout(g, columns), [g, columns]);
  const select = id => { setSel(id); if (focusMode && id) setFocus(id); };
  const hits = React.useMemo(() => adapter.search(full, query, 10), [full, query]);
  const presentTypes = columns.flat().filter(t => full.nodes.some(n => n.type === t));
  const selNode = sel ? full.byId[sel] : null;

  return (
    <div className={"mx-explorer" + (expanded ? " expanded" : "")}>
      <div className="mx-toolbar">
        <div className="mx-legend">
          {presentTypes.map(t => (
            <button key={t} className={"mx-chip" + (typeFilter === t ? " on" : "")} onClick={() => setTypeFilter(typeFilter === t ? null : t)} style={{ "--gc": meta[t].colour }}>
              <span className="dot"></span>{meta[t].label}<span className="ct">{full.nodes.filter(n => n.type === t).length}</span>
            </button>))}
          {sel && <button className="mx-chip clear" onClick={() => setSel(null)}><Ico k="x" w={9} /> clear</button>}
        </div>
        <div className="mx-search">
          <input type="search" value={query} placeholder={focusMode ? "Find an entity to start from" : "Find an entity"} aria-label="Find an entity"
            onChange={e => setQuery(e.target.value)} />
          {query && hits.length > 0 && (
            <ul className="mx-hits">{hits.map(n => <li key={n.id}><button onClick={() => { select(n.id); setQuery(""); }}><span className="dot" style={{ "--gc": (meta[n.type] || {}).colour }}></span>{n.label}<span className="ty">{n.type}</span></button></li>)}</ul>)}
        </div>
      </div>
      {full.pending > 0 && (
        <p className="mx-focus-note"><span className="mx-flag pending">{full.pending - full.refused.length} pending</span> facts on their way in are drawn with their station and are not believed{full.refused.length ? "; " + full.refused.length + " would be refused (see the panel of an entity that cites them, or `oto preview --show`)" : ""}.</p>)}
      {focusMode && (
        <p className="mx-focus-note">{full.nodes.length} entities: more than the whole-graph view draws at once. {focus ? "Showing " + (full.byId[focus] || {}).label + " and everything within " + hops + " hop" + (hops > 1 ? "s" : "") + "; click a neighbour to move." : "Find an entity above, or pick a class, to start."}</p>)}
      <div className="mx-body">
        <div className="mx-canvas">
          <button type="button" className="mx-fsbtn" onClick={() => setExpanded(v => !v)} title={expanded ? "Collapse (Esc)" : "Expand to the full window"} aria-label={expanded ? "Collapse" : "Expand"}>
            <Ico k={expanded ? "collapse" : "expand"} w={15} />
          </button>
          {g.nodes.length > 0 ? (
            <ReactFlowProvider>
              <Canvas g={g} L={L} sel={sel} setSel={select} hover={hover} setHover={setHover} typeFilter={typeFilter} expanded={expanded} meta={meta} evidenceable={evidenceable} />
            </ReactFlowProvider>
          ) : <div className="mx-empty">{focusMode ? "Nothing drawn yet." : "The graph holds no entities."}</div>}
        </div>
        <aside className="mx-detail">
          {!selNode ? (
            <div className="mx-gd-empty">
              <div className="ico"><Ico k="graph" w={20} /></div>
              <div className="t">Walk the graph</div>
              <div className="s">Click an entity to see its provenance, evidence and everything it connects to. Hover to light up its neighbourhood. A dashed edge was derived by a rule; a dashed node cites no document.</div>
            </div>
          ) : <Detail g={g} full={full} node={selNode} onSelect={select} meta={meta} evidenceable={evidenceable} />}
        </aside>
      </div>
    </div>
  );
}
