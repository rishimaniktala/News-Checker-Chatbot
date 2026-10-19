import type { DoneEvent } from "@/lib/types";

export default function Details({ done }: { done: DoneEvent }) {
  const rows: [string, string][] = [
    ["Run id", done.run_id],
    ["Cost", `$${done.cost_usd.toFixed(4)}`],
    ["Latency", `${(done.latency_ms / 1000).toFixed(1)} s`],
    ["Tokens in", String(done.tokens_in)],
    ["Tokens out", String(done.tokens_out)],
    ["Cached", done.cached ? "yes" : "no"],
  ];
  return (
    <details className="rounded-lg border border-slate-300 bg-white p-4">
      <summary className="cursor-pointer text-sm font-semibold">Run details</summary>
      <dl className="mt-3 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-slate-700">{k}</dt>
            <dd className="break-all font-mono">{v}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
