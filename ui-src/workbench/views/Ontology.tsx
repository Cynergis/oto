/* Ontology: the vocabulary itself, not the things it types (roadmap D1). A class list on the left; the
 * chosen class with its parents and children, the relations it carries (declared or inherited) with
 * their cardinality, the relations that reach it, and its attributes. Every class name is a link, so a
 * reader walks from any class to its parents, children and relationships. Read-only. */
import * as React from "react";
import { Search } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Empty } from "../components/common";
import type { OntologyClass, OntologyModel, RulesModel } from "../types";
import { cn } from "../lib/utils";

type Props = { model: OntologyModel | null; selected: string | null; rules?: RulesModel | null; onClass: (name: string | null) => void; onKind: (name: string) => void; onRules?: (name: string) => void };

export function Ontology({ model, selected, rules, onClass, onKind, onRules }: Props) {
  const [query, setQuery] = React.useState("");
  if (!model) return <Empty>No ontology to read: build the project first, then serve or export it.</Empty>;
  const by: Record<string, OntologyClass> = {};
  for (const c of model.classes) by[c.name] = c;
  const q = query.trim().toLowerCase();
  const listed = q ? model.classes.filter(c => [c.name, c.label, c.definition].some(t => (t || "").toLowerCase().includes(q))) : model.classes;
  const roots = listed.filter(c => c.parents.length === 0 || !c.parents.some(p => by[p]));
  const current = selected ? by[selected] : null;
  const link = (name: string) => by[name]
    ? <button key={name} type="button" onClick={() => onClass(name)} className="text-primary underline-offset-4 hover:underline first-letter:uppercase">{by[name].label}</button>
    : <span key={name} className="font-mono">{name}</span>;
  const links = (names: string[]) => names.length ? names.map((n, i) => <React.Fragment key={n}>{i ? ", " : ""}{link(n)}</React.Fragment>) : <span className="text-muted-foreground">—</span>;

  const tree = (c: OntologyClass, depth: number): React.ReactNode => (
    <React.Fragment key={c.name}>
      <button type="button" onClick={() => onClass(c.name)} aria-pressed={selected === c.name}
        style={{ paddingLeft: 12 + depth * 14 }}
        className={cn("flex min-h-9 items-center justify-between gap-2 rounded-md pr-3 text-left text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          selected === c.name && "bg-secondary font-semibold text-secondary-foreground")}>
        <span className="first-letter:uppercase">{c.label}</span>
        <span className="font-mono text-xs text-muted-foreground">{c.things}</span>
      </button>
      {q ? null : c.children.filter(k => by[k]).map(k => tree(by[k], depth + 1))}
    </React.Fragment>
  );

  return (
    <div className="flex flex-wrap items-start gap-6">
      <nav aria-label="Classes" className="flex flex-[1_1_240px] flex-col gap-0.5">
        <label className="relative mb-2 block">
          <span className="sr-only">Search the classes</span>
          <Search aria-hidden="true" className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search classes and definitions"
            className="h-10 w-full rounded-md border border-input bg-card pl-9 pr-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        </label>
        <p className="mb-1 px-3 text-xs text-muted-foreground">
          {model.counts.classes} classes, {model.counts.relations} relations, {model.counts.attributes} attributes
          {model.version != null ? " · vocabulary version " + model.version : ""}{model.derived_from_data ? " · read from the data, nothing declared" : ""}
        </p>
        {(q ? listed : roots).map(c => tree(c, 0))}
        {listed.length === 0 ? <Empty>No class matches.</Empty> : null}
      </nav>

      <div className="min-w-0 flex-[3_1_480px]">
        {current ? (
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">class</Badge>
                <span className="font-mono text-xs text-muted-foreground">{current.name}</span>
                {current.things ? <button type="button" onClick={() => onKind(current.name)} className="text-xs text-primary underline-offset-4 hover:underline">{current.things} current {current.things === 1 ? "thing" : "things"} in the knowledge base</button>
                  : <span className="text-xs text-muted-foreground">nothing of exactly this class yet</span>}
                {rules && onRules ? <button type="button" onClick={() => onRules(current.name)} className="text-xs text-primary underline-offset-4 hover:underline">
                  {(rules.by_class[current.name] || []).length} {(rules.by_class[current.name] || []).length === 1 ? "rule applies" : "rules apply"}</button> : null}
              </div>
              <CardTitle className="text-2xl first-letter:uppercase">{current.label}</CardTitle>
              {current.definition ? <CardDescription className="text-base">{current.definition}</CardDescription> : null}
            </CardHeader>
            <CardContent className="flex flex-col gap-6 text-sm">
              <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,3fr)] gap-x-4 gap-y-1.5">
                <dt className="text-muted-foreground">A kind of</dt><dd>{links(current.parents)}</dd>
                {current.ancestors.length > current.parents.length ? <><dt className="text-muted-foreground">And so of</dt><dd>{links(current.ancestors.filter(a => !current.parents.includes(a)))}</dd></> : null}
                <dt className="text-muted-foreground">Kinds of it</dt><dd>{links(current.children)}</dd>
                {current.requires.length ? <><dt className="text-muted-foreground">Every one has</dt><dd className="font-mono">{current.requires.join(", ")}</dd></> : null}
                {current.scope_note ? <><dt className="text-muted-foreground">Scope</dt><dd>{current.scope_note}</dd></> : null}
                {current.example ? <><dt className="text-muted-foreground">Example</dt><dd>{current.example}</dd></> : null}
              </dl>

              <section className="flex flex-col gap-2">
                <h4 className="font-semibold">Relations it carries <span className="font-normal text-muted-foreground">({current.relations_out.length})</span></h4>
                {current.relations_out.length ? (
                  <Table>
                    <TableHeader><TableRow><TableHead>Relation</TableHead><TableHead>To</TableHead><TableHead>How many</TableHead><TableHead>Inverse</TableHead><TableHead>From</TableHead></TableRow></TableHeader>
                    <TableBody>
                      {current.relations_out.map(r => (
                        <TableRow key={r.name}>
                          <TableCell><span className="font-medium">{r.label}</span><span className="block font-mono text-xs text-muted-foreground">{r.name}</span>{r.definition ? <span title={r.definition} className="line-clamp-2 max-w-[28ch] text-xs text-muted-foreground">{r.definition}</span> : null}</TableCell>
                          <TableCell>{links(r.to)}</TableCell>
                          <TableCell className="font-mono">{r.cardinality}</TableCell>
                          <TableCell className="font-mono text-xs">{r.inverse || "—"}</TableCell>
                          <TableCell>{r.inherited_from ? <span className="text-xs text-muted-foreground">inherited from {link(r.inherited_from)}</span> : <Badge variant="secondary">declared here</Badge>}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : <p className="text-muted-foreground">None declared.</p>}
              </section>

              <section className="flex flex-col gap-2">
                <h4 className="font-semibold">Relations that reach it <span className="font-normal text-muted-foreground">({current.relations_in.length})</span></h4>
                {current.relations_in.length ? (
                  <Table>
                    <TableHeader><TableRow><TableHead>Read as</TableHead><TableHead>From</TableHead><TableHead>Relation</TableHead></TableRow></TableHeader>
                    <TableBody>
                      {current.relations_in.map(r => (
                        <TableRow key={r.name}>
                          <TableCell className="font-medium">{r.label}{r.inherited_from ? <span className="block text-xs font-normal text-muted-foreground">as a kind of {link(r.inherited_from)}</span> : null}</TableCell>
                          <TableCell>{links(r.from)}</TableCell>
                          <TableCell className="font-mono text-xs">{r.name}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : <p className="text-muted-foreground">Nothing points at it.</p>}
              </section>

              <section className="flex flex-col gap-2">
                <h4 className="font-semibold">Attributes <span className="font-normal text-muted-foreground">({current.attributes.length})</span></h4>
                {current.attributes.length ? (
                  <Table>
                    <TableHeader><TableRow><TableHead>Attribute</TableHead><TableHead>Type</TableHead><TableHead>Rules</TableHead></TableRow></TableHeader>
                    <TableBody>
                      {current.attributes.map(a => (
                        <TableRow key={a.name}>
                          <TableCell><span className="font-medium">{a.label}</span><span className="block font-mono text-xs text-muted-foreground">{a.name}</span>{a.definition ? <span title={a.definition} className="line-clamp-2 max-w-[36ch] text-xs text-muted-foreground">{a.definition}</span> : null}</TableCell>
                          <TableCell className="font-mono text-xs">{a.values ? a.values.join(" | ") : a.type}</TableCell>
                          <TableCell className="flex flex-wrap gap-1">
                            {a.required ? <Badge variant="attention">required</Badge> : null}
                            {a.decision ? <Badge variant="secondary">a person decides</Badge> : null}
                            {a.default != null && a.default !== "" ? <Badge variant="outline">default {String(a.default)}</Badge> : null}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : <p className="text-muted-foreground">None declared{model.derived_from_data ? ": the vocabulary is read from the data" : ""}.</p>}
              </section>
            </CardContent>
          </Card>
        ) : <Empty>Choose a class to read what it is a kind of, what kinds of it exist, which relations it carries and which attributes it declares.</Empty>}
      </div>
    </div>
  );
}
