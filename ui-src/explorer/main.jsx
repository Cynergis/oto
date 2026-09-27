/* Mounts the explorer: loads data.json (the graph payload) and, when present, explorer.json (a
 * ontology's or project's overrides), polls the engine's change signal in live mode, and
 * reloads on a new build. */
import React from "react";
import { createRoot } from "react-dom/client";
import { Explorer } from "./explorer.jsx";
import adapter from "./adapter.js";
import defaults from "./defaults.js";

function fetchJson(url) {
  return fetch(url, { cache: "no-store" }).then(r => { if (!r.ok) throw new Error(url + " " + r.status); return r.json(); });
}

function App({ payload, override }) {
  const full = React.useMemo(() => adapter.toGraph(payload), [payload]);
  const d = React.useMemo(() => defaults.fromVocabulary(payload.vocabulary, override), [payload, override]);
  return <Explorer full={full} defaults={d} />;
}

function boot() {
  const mount = document.getElementById("explorer");
  const root = createRoot(mount);
  const fresh = document.getElementById("freshness");
  const brand = document.getElementById("brand-name");
  let seq = null, live = false;
  function regime(p) {
    const m = p.mode || {};
    if (m.regime === "watch") return "watch · rebuilt " + (m.preview_built_at || "?").replace("T", " ").slice(0, 19) + (m.differs ? " · " + m.differs + " pending change" + (m.differs === 1 ? "" : "s") : "") + (m.error ? " · rebuild failed" : "");
    if (m.regime === "preview") return "preview · built " + (m.preview_built_at || "?").replace("T", " ").slice(0, 19) + (m.differs ? " · " + m.differs + " pending change" + (m.differs === 1 ? "" : "s") : "");
    return (live ? "live" : "static") + " · build " + (p.build_seq || "?") + " · " + (p.backend || "");
  }
  function freshness(p) { fresh.textContent = regime(p); }
  function load() {
    return Promise.all([fetchJson("data.json"), fetchJson("explorer.json").catch(() => ({}))]).then(([payload, override]) => {
      seq = payload.token || payload.build_seq;
      const name = (payload.project && payload.project.name) || "OTO";
      brand.textContent = (override && override.title) || name;
      document.title = name + " · explorer";
      root.render(<App payload={payload} override={override || {}} />);
      freshness(payload);
      return payload;
    });
  }
  function poll(payload) {
    fetch("api/changes?since=" + encodeURIComponent(seq || ""), { cache: "no-store" })
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(c => { const was = live; live = true; if (c.mode) payload.mode = c.mode; if (!was) freshness(payload); if (c.changed && seq) load().then(poll); else setTimeout(() => poll(payload), 4000); })
      .catch(() => { live = false; freshness(payload); });
  }
  load().then(poll).catch(e => {
    mount.innerHTML = '<div class="mx-empty">No data: ' + e.message + '. Serve this app with <code>oto serve --http</code> or export it with <code>oto build --target site</code>.</div>';
  });
}

boot();
