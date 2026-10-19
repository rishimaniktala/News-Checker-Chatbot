"use client";
import { useState } from "react";
import { API_BASE } from "@/lib/stream";
import type { DoneEvent } from "@/lib/types";

export default function Receipt({ done }: { done: DoneEvent }) {
  const [copied, setCopied] = useState(false);
  const chips: [string, string][] = [
    ["Cost", `$${done.cost_usd.toFixed(4)}`],
    ["Time", `${(done.latency_ms / 1000).toFixed(1)} s`],
    ["Tokens", `${done.tokens_in} in / ${done.tokens_out} out`],
  ];
  async function copy() {
    try {
      await navigator.clipboard.writeText(done.run_id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }
  return (
    <footer aria-label="Run details" className="rise flex flex-wrap items-center gap-2 font-mono text-xs text-muted">
      {chips.map(([k, v]) => (
        <span key={k} className="rounded-full border border-rule px-3 py-1"><span className="uppercase tracking-wider">{k}</span> <span className="text-ink">{v}</span></span>
      ))}
      {done.cached && <span className="rounded-full border border-warn px-3 py-1 text-warn">cached</span>}
      <button type="button" onClick={copy} aria-label="Copy run id" className="rounded-full border border-rule px-3 py-1 hover:border-ink hover:text-ink">
        {copied ? "Copied ✓" : `Run ${done.run_id}`}
      </button>
      <a href={`${API_BASE}/api/runs/${done.run_id}`} target="_blank" rel="noopener noreferrer" className="rounded-full border border-rule px-3 py-1 hover:border-ink hover:text-ink">
        Full trace ↗<span className="sr-only"> (opens in a new tab)</span>
      </a>
    </footer>
  );
}
