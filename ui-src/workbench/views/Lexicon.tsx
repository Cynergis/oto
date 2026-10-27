/* Lexicon: every term of the vocabulary in every language the project declares, and the words people
 * use for the things in the graph (roadmap D3). A search over all of it: each hit names the element it
 * lands on (a class page, the class that carries a relation or an attribute, an entity of the
 * knowledge base) and a click goes there. With no search, the whole lexicon as two tables. Read-only. */
import * as React from "react";
import { Search } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Empty } from "../components/common";
import type { LexiconHit, LexiconModel, LexiconTarget, LexiconTerm, OntologyModel } from "../types";

type Props = { model: LexiconModel | null; ontology: OntologyModel | null; query: string; onQuery: (q: string) => void; onClass: (name: string) => void; onEntity: (id: string) => void };

const KIND_WORDS: Record<string, string> = { class: "class", relation: "relation", attribute: "attribute", temporal: "time", scheme: "scheme", concept: "concept", phrase: "people say" };

function score(wanted: string, text: string | null | undefined) {
  const t = (text || "").toLowerCase();
  if (!t) return 0;
  if (t === wanted) return 3;
  if (t.startsWith(wanted)) return 2;
  if (t.includes(wanted)) return 1;
  return 0;
}

function words(name: string) { return name.replace(/_/g, " "); }

/* The same ranking as oto/serve/lexicon.py search(): a term by label, alternative label or name in any language, then the phrases. */
export function search(m: LexiconModel, query: string): LexiconHit[] {
  const wanted = query.trim().replace(/\s+/g, " ").toLowerCase();
  if (!wanted) return [];
  const hits: { s: number; h: LexiconHit }[] = [];
  for (const t of m.terms) {
    const candidates: { language: string | null; text: string; how: string }[] = [];
    for (const [language, text] of Object.entries(t.labels)) candidates.push({ language, text, how: "label" });
    for (const [language, items] of Object.entries(t.alt_labels)) for (const text of items) candidates.push({ language, text, how: "alt_label" });
    candidates.push({ language: null, text: t.name, how: "name" }, { language: null, text: words(t.name).toLowerCase(), how: "name" });
    let best: { s: number; match: LexiconHit["match"] } | null = null;
    for (const c of candidates) {
      const s = score(wanted, c.text);
      if (s && (!best || s > best.s)) best = { s, match: c };
    }
    if (best) hits.push({ s: best.s, h: { kind: t.kind, name: t.name, owner: t.owner, label: t.labels[m.default_language], labels: t.labels, target: t.target, match: best.match } });
  }
  for (const p of m.phrases) {
    const s = Math.max(score(wanted, p.phrase), score(wanted, p.canonical));
    if (s) hits.push({ s, h: { kind: "phrase", name: p.phrase, owner: null, label: p.label, labels: {}, canonical: p.canonical, type: p.type, status: p.status, note: p.note,
      target: p.target ? { section: "knowledge", entity: p.target } : null, match: { language: null, text: score(wanted, p.phrase) >= score(wanted, p.canonical) ? p.phrase : p.canonical, how: "phrase" } } });
  }
  hits.sort((a, b) => b.s - a.s || a.h.match.text.length - b.h.match.text.length || a.h.name.toLowerCase().localeCompare(b.h.name.toLowerCase()));
  return hits.map(x => x.h);
}

export function Lexicon({ model, ontology, query, onQuery, onClass, onEntity }: Props) {
  const [typed, setTyped] = React.useState(query);
  React.useEffect(() => { setTyped(query); }, [query]);
  if (!model) return <Empty>No lexicon to read: build the project first, then serve or export it.</Empty>;
  const labels: Record<string, string> = {};
  for (const c of ontology?.classes || []) labels[c.name] = c.label;
  const word = (name: string) => labels[name] || name;
  const go = (target: LexiconTarget | null) => {
    if (!target) return;
    if (target.section === "knowledge" && target.entity) onEntity(target.entity);
    else if (target.section === "ontology" && target.class) onClass(target.class);
  };
  const where = (target: LexiconTarget | null) => {
    if (!target) return "nowhere: not in the graph";
    if (target.section === "knowledge") return "the knowledge base";
    if (target.attribute && target.class) return "attribute " + target.attribute + " of " + word(target.class);
    if (target.relation) return target.class ? "relation " + words(target.relation) + " on " + word(target.class) : "relation " + words(target.relation) + ", no class carries it";
    if (target.scheme) return "scheme " + target.scheme + ", no attribute uses it";
    return target.class ? "class " + word(target.class) : "the ontology";
  };
  const hits = search(model, query);
  const submit = (e: React.FormEvent) => { e.preventDefault(); onQuery(typed); };

  return (
    <div className="flex flex-col gap-6">
      <form onSubmit={submit} className="flex flex-wrap items-center gap-3">
        <label className="relative block min-w-[260px] flex-1">
          <span className="sr-only">Search the lexicon</span>
          <Search aria-hidden="true" className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input value={typed} onChange={e => setTyped(e.target.value)} placeholder={"A word in any language: " + model.languages.join(", ")}
            className="h-10 w-full rounded-md border border-input bg-card pl-9 pr-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        </label>
        <button type="submit" className="h-10 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90">Find</button>
        {query ? <button type="button" onClick={() => onQuery("")} className="text-sm text-primary underline-offset-4 hover:underline">Clear</button> : null}
        <span className="text-xs text-muted-foreground">{model.counts.terms} terms, {model.counts.phrases} words people use · {model.languages.join(" / ")}</span>
      </form>

      {query ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{hits.length ? hits.length + (hits.length === 1 ? " element" : " elements") + " named by " : "Nothing is named by "}<span className="font-mono">{query}</span></CardTitle>
            <CardDescription>Each hit lands on the element it names; open it with a click.</CardDescription>
          </CardHeader>
          <CardContent>
            {hits.length ? (
              <ul className="flex flex-col gap-2">
                {hits.map((h, i) => (
                  <li key={h.kind + ":" + (h.owner || "") + ":" + h.name + ":" + i} className="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm">
                    <Badge variant={h.kind === "phrase" ? "secondary" : "outline"}>{KIND_WORDS[h.kind] || h.kind}</Badge>
                    <button type="button" onClick={() => go(h.target)} disabled={!h.target} className="font-medium text-primary underline-offset-4 enabled:hover:underline disabled:text-muted-foreground disabled:no-underline">
                      {h.kind === "phrase" ? (h.label || h.name) : (h.label || h.name)}
                    </button>
                    <span className="font-mono text-xs text-muted-foreground">{h.owner ? h.owner + "." : ""}{h.name}</span>
                    <span className="text-xs text-muted-foreground">
                      {h.match.how === "phrase" ? "people say " : (h.match.language ? h.match.language + " " : "") + (h.match.how === "alt_label" ? "also " : h.match.how === "name" ? "name " : "")}
                      <span className="font-medium">{h.match.text}</span>
                      {h.status && h.status !== "current" ? " · " + h.status : ""}
                    </span>
                    <span className="ml-auto text-xs text-muted-foreground">→ {where(h.target)}</span>
                  </li>
                ))}
              </ul>
            ) : <Empty>No term, label or phrase contains it. The lexicon knows {model.counts.terms} terms and {model.counts.phrases} words people use.</Empty>}
          </CardContent>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader><CardTitle className="text-base">Terms</CardTitle><CardDescription>Every class, relation, attribute and controlled value, with its label in each declared language.</CardDescription></CardHeader>
            <CardContent>
              {model.terms.length ? (
                <Table>
                  <TableHeader><TableRow><TableHead>Term</TableHead>{model.languages.map(l => <TableHead key={l}>{l}</TableHead>)}<TableHead>Means</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {model.terms.map(t => <TermRow key={t.kind + ":" + (t.owner || "") + ":" + t.name} term={t} languages={model.languages} fallback={model.default_language} go={go} />)}
                  </TableBody>
                </Table>
              ) : <Empty>The vocabulary declares no terms.</Empty>}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle className="text-base">Words people use</CardTitle><CardDescription>Jargon, acronyms and nicknames mapped to the entity they mean, as a person recorded them in lexicon.json.</CardDescription></CardHeader>
            <CardContent>
              {model.phrases.length ? (
                <Table>
                  <TableHeader><TableRow><TableHead>Word</TableHead><TableHead>Stands for</TableHead><TableHead>Means</TableHead><TableHead>Note</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {model.phrases.map((p, i) => (
                      <TableRow key={p.phrase + ":" + (p.target || "") + ":" + i}>
                        <TableCell className="font-medium">{p.phrase}</TableCell>
                        <TableCell>{p.canonical}</TableCell>
                        <TableCell>{p.target
                          ? <button type="button" onClick={() => onEntity(p.target as string)} className="text-primary underline-offset-4 hover:underline">{p.label || p.target}</button>
                          : <span className="text-muted-foreground">nothing in the graph{p.status !== "current" ? " · " + p.status : ""}</span>}
                          {p.type ? <span className="ml-1 text-xs text-muted-foreground">({word(p.type)})</span> : null}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">{p.note}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : <Empty>No lexicon.json yet: nothing maps the words people use to the things in the graph.</Empty>}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function TermRow({ term, languages, fallback, go }: { term: LexiconTerm; languages: string[]; fallback: string; go: (t: LexiconTarget | null) => void }) {
  const canGo = term.target.section === "ontology" && !!term.target.class;
  return (
    <TableRow>
      <TableCell>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{KIND_WORDS[term.kind] || term.kind}</Badge>
          <button type="button" onClick={() => go(term.target)} disabled={!canGo} className="font-mono text-xs text-primary underline-offset-4 enabled:hover:underline disabled:text-foreground disabled:no-underline">{term.owner ? term.owner + "." : ""}{term.name}</button>
        </div>
      </TableCell>
      {languages.map(l => (
        <TableCell key={l}>
          {term.labels[l] ? <span className="first-letter:uppercase">{term.labels[l]}</span> : <span className="text-muted-foreground">—</span>}
          {term.alt_labels[l]?.length ? <span className="block text-xs text-muted-foreground">also {term.alt_labels[l].join(", ")}</span> : null}
        </TableCell>
      ))}
      <TableCell title={term.definition[fallback] || ""} className="line-clamp-2 max-w-[40ch] text-xs text-muted-foreground">{term.definition[fallback] || ""}</TableCell>
    </TableRow>
  );
}
