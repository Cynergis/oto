/* Versions: the vocabulary's current version, the one last accepted and what changed since, and, when
 * served live from a git repository, the vocabulary at any ref compared with the working tree or
 * another ref (roadmap D6). The same comparison `oto ontology diff --from` prints and the checks
 * workflow posts on a pull request. Read-only. */
import * as React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Empty } from "../components/common";
import type { OntologyModel, VersionDiff } from "../types";

type Props = { model: OntologyModel | null; live: boolean };

const SEVERITY: Record<string, "default" | "attention" | "secondary" | "outline"> = { breaking: "attention", additive: "secondary", cosmetic: "outline" };

export function Versions({ model, live }: Props) {
  const versions = model?.versions || null;
  const [from, setFrom] = React.useState("HEAD");
  const [to, setTo] = React.useState("");
  const [asked, setAsked] = React.useState<{ from: string; to: string } | null>(null);
  const [diff, setDiff] = React.useState<VersionDiff | null>(null);
  const [problem, setProblem] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  if (!model || !versions) return <Empty>No versions to read: build the project first, then serve or export it.</Empty>;
  const canCompare = live && versions.git;

  const compare = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = "api/ontology/diff?from=" + encodeURIComponent(from.trim()) + (to.trim() ? "&to=" + encodeURIComponent(to.trim()) : "");
    setBusy(true); setProblem(null); setDiff(null); setAsked({ from: from.trim(), to: to.trim() });
    try {
      const r = await fetch(q, { cache: "no-store" });
      const body = await r.json();
      if (!r.ok) setProblem(body.error || (q + " " + r.status));
      else setDiff(body as VersionDiff);
    } catch (err) {
      setProblem(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-3 sm:grid-cols-3">
        <Fact label="Current version" value={String(versions.current)} note={model.counts.classes + " classes · " + model.counts.relations + " relations · " + model.counts.attributes + " attributes"} />
        <Fact label="Accepted version" value={versions.accepted == null ? "none" : String(versions.accepted)}
          note={versions.accepted == null ? "nobody ran oto ontology accept yet" : versions.since_accepted && versions.since_accepted.counts.changes ? versions.since_accepted.counts.changes + " changes since" : "no change since"} />
        <Fact label="Git" value={versions.git ? "yes" : "no"} note={versions.git ? (live ? "any ref can be compared below" : "compare a ref when served live") : "not in a repository: no ref to compare"} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Since the vocabulary was accepted</CardTitle>
          <CardDescription>What `oto ontology check` reports: every change from the accepted version to the working tree, most severe first, with how many things each breaking one touches.</CardDescription>
        </CardHeader>
        <CardContent>
          {versions.since_accepted ? <Changes diff={versions.since_accepted} /> : <Empty>No accepted vocabulary on record: `oto ontology accept` records this one as the baseline, then every change is diffed against it.</Empty>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Compare with a git ref</CardTitle>
          <CardDescription>The vocabulary as it was at a ref (HEAD, main, a tag, a commit) against the working tree, or against another ref. The same comparison `oto ontology diff --from` prints.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {canCompare ? (
            <form onSubmit={compare} className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1 text-xs text-muted-foreground">From
                <input value={from} onChange={e => setFrom(e.target.value)} required placeholder="HEAD" className="h-10 w-44 rounded-md border border-input bg-card px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" /></label>
              <label className="flex flex-col gap-1 text-xs text-muted-foreground">To
                <input value={to} onChange={e => setTo(e.target.value)} placeholder="the working tree" className="h-10 w-44 rounded-md border border-input bg-card px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" /></label>
              <button type="submit" disabled={busy || !from.trim()} className="h-10 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">{busy ? "Comparing…" : "Compare"}</button>
            </form>
          ) : <p className="text-sm text-muted-foreground">{!live ? "This is a published copy: serve the project live to compare a ref." : "The project is not in a git repository, so there is no ref to compare."}</p>}
          {problem ? <p className="rounded-md bg-attention-soft px-3 py-2 text-sm text-attention">{problem}</p> : null}
          {diff && asked ? <Changes diff={diff} /> : null}
        </CardContent>
      </Card>
    </div>
  );
}

function Fact({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-2xl font-bold">{value}</p>
      <p className="text-xs text-muted-foreground">{note}</p>
    </div>
  );
}

function Changes({ diff }: { diff: VersionDiff }) {
  const [a, b] = diff.labels || ["the former vocabulary", "the current one"];
  return (
    <div className="flex flex-col gap-3 text-sm">
      <p>
        {diff.counts.changes === 0 ? <span>No change from <span className="font-mono">{a}</span> to <span className="font-mono">{b}</span>.</span>
          : <span>{diff.counts.changes} {diff.counts.changes === 1 ? "change" : "changes"} from <span className="font-mono">{a}</span> (version {diff.from.version}, {diff.from.classes} classes) to <span className="font-mono">{b}</span> (version {diff.to.version}, {diff.to.classes} classes): {diff.counts.breaking} breaking, {diff.counts.additive} additive, {diff.counts.cosmetic} cosmetic.</span>}
      </p>
      {diff.bump_needed ? <p className="rounded-md bg-attention-soft px-3 py-2 text-attention">{diff.counts.breaking} breaking {diff.counts.breaking === 1 ? "change" : "changes"} with no version bump: raise ontology_version in ontology.config.json, then run oto ontology accept.</p>
        : diff.counts.breaking ? <p className="rounded-md bg-secondary px-3 py-2">{diff.counts.breaking} breaking {diff.counts.breaking === 1 ? "change" : "changes"}, acknowledged by the bump to version {diff.to.version}.</p> : null}
      {diff.changes.length ? (
        <Table>
          <TableHeader><TableRow><TableHead>Severity</TableHead><TableHead>Change</TableHead><TableHead>Subject</TableHead><TableHead>Detail</TableHead><TableHead className="text-right">Touches</TableHead></TableRow></TableHeader>
          <TableBody>
            {diff.changes.map((c, i) => (
              <TableRow key={i}>
                <TableCell><Badge variant={SEVERITY[c.severity] || "outline"}>{c.severity}</Badge></TableCell>
                <TableCell>{c.kind}</TableCell>
                <TableCell className="font-mono text-xs">{c.subject}</TableCell>
                <TableCell className="text-muted-foreground">{c.detail}</TableCell>
                <TableCell className="text-right tabular-nums">{c.affected || ""}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : null}
    </div>
  );
}
