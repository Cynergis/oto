/* Rules: what the rule set derives and forbids, read by class (roadmap D2). A class list on the left
 * with how many rules reach each class; on the right the rules that apply to the chosen class (named
 * on it, on an ancestor, or on every node), each with its patterns in words, what it touches and who
 * confirmed it. Every class name is a link into the Ontology page. Read-only. */
import * as React from "react";
import { Search } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Empty } from "../components/common";
import type { OntologyModel, RuleEntry, RulesModel } from "../types";
import { cn } from "../lib/utils";

type Props = { model: RulesModel | null; ontology: OntologyModel | null; klass: string | null; onPick: (name: string | null) => void; onClass: (name: string) => void };

export function Rules({ model, ontology, klass, onPick, onClass }: Props) {
  const [query, setQuery] = React.useState("");
  if (!model) return <Empty>No rules to read: build the project first, then serve or export it.</Empty>;
  const labels: Record<string, string> = {};
  for (const c of ontology?.classes || []) labels[c.name] = c.label;
  const word = (name: string) => labels[name] || name;
  const classes = Object.keys(model.by_class).sort((a, b) => word(a).localeCompare(word(b)));
  const q = query.trim().toLowerCase();
  const wanted = klass && model.by_class[klass] ? new Set(model.by_class[klass]) : null;
  const lineage = klass ? model.lineage[klass] || [] : [];
  const via = (r: RuleEntry) => (!klass || r.every_node || r.classes.includes(klass)) ? null : lineage.find(a => r.classes.includes(a)) || null;
  const listed = model.rules
    .filter(r => !wanted || wanted.has(r.id))
    .filter(r => !q || [r.id, r.why, r.then, ...r.when, ...r.classes, ...r.relations].some(t => (t || "").toLowerCase().includes(q)));
  const link = (name: string) => <button key={name} type="button" onClick={() => onClass(name)} className="text-primary underline-offset-4 hover:underline first-letter:uppercase">{word(name)}</button>;
  const links = (names: string[]) => names.map((n, i) => <React.Fragment key={n}>{i ? ", " : ""}{link(n)}</React.Fragment>);

  return (
    <div className="flex flex-wrap items-start gap-6">
      <nav aria-label="Rules by class" className="flex flex-[1_1_240px] flex-col gap-0.5">
        <label className="relative mb-2 block">
          <span className="sr-only">Search the rules</span>
          <Search aria-hidden="true" className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search rules, patterns, reasons"
            className="h-10 w-full rounded-md border border-input bg-card pl-9 pr-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        </label>
        <p className="mb-1 px-3 text-xs text-muted-foreground">
          {model.counts.rules} rules: {model.counts.derive} derive, {model.counts.policy} policy · {model.counts.confirmed} confirmed
        </p>
        <button type="button" onClick={() => onPick(null)} aria-pressed={!klass}
          className={cn("flex min-h-9 items-center justify-between gap-2 rounded-md px-3 text-left text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", !klass && "bg-secondary font-semibold text-secondary-foreground")}>
          <span>Every rule</span><span className="font-mono text-xs text-muted-foreground">{model.counts.rules}</span>
        </button>
        {classes.map(name => (
          <button key={name} type="button" onClick={() => onPick(name)} aria-pressed={klass === name}
            className={cn("flex min-h-9 items-center justify-between gap-2 rounded-md px-3 text-left text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              klass === name && "bg-secondary font-semibold text-secondary-foreground", model.by_class[name].length === 0 && "text-muted-foreground")}>
            <span className="first-letter:uppercase">{word(name)}</span>
            <span className="font-mono text-xs text-muted-foreground">{model.by_class[name].length}</span>
          </button>
        ))}
      </nav>

      <div className="flex min-w-0 flex-[3_1_480px] flex-col gap-4">
        {klass ? (
          <p className="text-sm text-muted-foreground">
            Rules that apply to a <span className="font-medium text-foreground">{link(klass)}</span>
            {lineage.length ? <> as a kind of {links(lineage)}</> : null}: {listed.length} of {model.counts.rules}.
          </p>
        ) : null}
        {model.counts.rules === 0 ? <Empty>No rules declared: the project has no rules.json, or an empty one.</Empty>
          : listed.length === 0 ? <Empty>No rule matches.</Empty>
          : listed.map(r => <Rule key={r.id} rule={r} via={via(r)} links={links} />)}
      </div>
    </div>
  );
}

function Rule({ rule, via, links }: { rule: RuleEntry; via: string | null; links: (names: string[]) => React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={rule.kind === "policy" ? "attention" : "secondary"}>{rule.kind}</Badge>
          {rule.severity ? <Badge variant={rule.severity === "blocking" ? "default" : "outline"}>{rule.severity}</Badge> : null}
          {rule.every_node ? <Badge variant="muted">every node</Badge> : null}
          {via ? <span className="text-xs text-muted-foreground">through {links([via])}</span> : null}
          {rule.answers ? <span className="ml-auto font-mono text-xs text-muted-foreground">protects {rule.answers}</span> : null}
        </div>
        <CardTitle className="font-mono text-base">{rule.id}</CardTitle>
        {rule.why ? <CardDescription className="text-sm">{rule.why}</CardDescription> : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-4 text-sm">
        <div className="grid gap-x-4 gap-y-1.5 sm:grid-cols-[minmax(0,1fr)_minmax(0,5fr)]">
          <span className="text-muted-foreground">When</span>
          <ol className="flex flex-col gap-0.5 font-mono text-xs">{rule.when.map((w, i) => <li key={i}>{w}</li>)}</ol>
          <span className="text-muted-foreground">Then</span>
          <span className="font-mono text-xs">{rule.then}</span>
          <span className="text-muted-foreground">Classes</span>
          <span>{rule.classes.length ? links(rule.classes) : <span className="text-muted-foreground">{rule.every_node ? "any" : "—"}</span>}</span>
          {rule.relations.length ? <><span className="text-muted-foreground">Relations</span><span className="font-mono text-xs">{rule.relations.join(", ")}</span></> : null}
          {rule.attributes.length ? <><span className="text-muted-foreground">Attributes</span><span className="font-mono text-xs">{rule.attributes.join(", ")}</span></> : null}
        </div>
        <span className={rule.validated_by ? "text-done" : "text-attention"}>{rule.validated_by ? "Confirmed by " + rule.validated_by : "Nobody has confirmed it"}</span>
      </CardContent>
    </Card>
  );
}
