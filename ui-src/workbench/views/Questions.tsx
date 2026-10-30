/* Questions: the competency questions the vocabulary promises to answer (questions.json), one line
 * each: its id, who asks it, the question in their words, and whether the graph answers it today.
 * A tab of the Ontology page, since the questions are the vocabulary's contract, not a station of
 * the project. Read from the snapshot (api/status, or snapshot.json when exported). Read-only. */
import * as React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Empty } from "../components/common";
import type { Snapshot } from "../types";

type Question = Snapshot["vocabulary"]["questions"][number];
type Props = { questions: Question[] | null };

export function Questions({ questions }: Props) {
  if (!questions) return <Empty>No project snapshot here: this copy carries the graph only, and the questions live with the project.</Empty>;
  if (questions.length === 0) return <Empty>The vocabulary declares no competency question yet: questions.json is where they go.</Empty>;
  const answered = questions.filter(q => q.answered);
  const open = questions.filter(q => !q.answered);
  const row = (q: Question) => (
    <li key={q.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-md px-3 py-2 odd:bg-muted/40">
      <span className="min-w-12 font-mono text-xs text-muted-foreground">{q.id}</span>
      <span className="flex-1 basis-[28ch]">{q.question}</span>
      <span className="text-xs text-muted-foreground">{q.who ? "asked by " + q.who : "no one named"}</span>
      <Badge variant={q.answered ? "done" : "muted"}>{q.answered ? "answered" : "not answered"}</Badge>
    </li>
  );
  return (
    <Card>
      <CardHeader className="flex-row items-baseline justify-between">
        <div>
          <CardTitle>Questions it must answer</CardTitle>
          <CardDescription>The vocabulary's contract: what a reader may ask of this graph, and whether the graph answers it today.</CardDescription>
        </div>
        <span className="text-sm font-semibold text-done">{answered.length} of {questions.length}</span>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {open.length ? (
          <section className="flex flex-col gap-1">
            <h4 className="px-3 text-sm font-semibold text-attention">Not answered yet</h4>
            <ul className="flex flex-col text-sm">{open.map(row)}</ul>
          </section>
        ) : null}
        <section className="flex flex-col gap-1">
          <h4 className="px-3 text-sm font-semibold">Answered</h4>
          {answered.length ? <ul className="flex flex-col text-sm">{answered.map(row)}</ul> : <p className="px-3 text-sm text-muted-foreground">None yet.</p>}
        </section>
      </CardContent>
    </Card>
  );
}
