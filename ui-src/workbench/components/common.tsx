/* Small pieces every view uses: a station's dot, the hand-off to the agent, a section heading. */
import * as React from "react";
import { Check, Copy, Plug } from "lucide-react";
import { Button } from "./ui/button";
import type { StationState } from "../types";

const DOT: Record<StationState, string> = { done: "var(--done-dot)", attention: "var(--attention-dot)", not_started: "var(--idle-dot)" };
export const STATE_WORDS: Record<StationState, string> = { done: "done", attention: "needs a person", not_started: "not started" };

export function Dot({ state }: { state: StationState }) {
  return (
    <svg width="10" height="10" aria-hidden="true" className="shrink-0">
      <circle cx="5" cy="5" r="5" fill={DOT[state]} />
    </svg>
  );
}

/* The workbench changes nothing. Served beside the agent, it offers the request to copy into the
 * conversation; published, it says what it takes to make the change. */
export function AskAgent({ request, live }: { request: string; live: boolean }) {
  const [copied, setCopied] = React.useState(false);
  if (!live) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Plug aria-hidden="true" className="size-4" />
        To change this, add the oto plugin to Claude Code and ask there.
      </p>
    );
  }
  const copy = () => {
    navigator.clipboard?.writeText(request).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1600); });
  };
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
      <p className="flex-1 rounded-md border bg-card px-3 py-2 text-sm leading-relaxed">“{request}”</p>
      <Button onClick={copy} aria-label="Copy this request for the agent">
        {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
        {copied ? "Copied" : "Ask the agent"}
      </Button>
    </div>
  );
}

export function SectionTitle({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="text-xl font-semibold">{children}</h2>
      {aside ? <span className="text-sm text-muted-foreground">{aside}</span> : null}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">{children}</p>;
}
