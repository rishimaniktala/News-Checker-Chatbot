import type { TraceLine } from "@/lib/reducer";

const MARK = { ok: "✓", failed: "✗", retry: "↻" } as const;
const SR = { running: "Running", ok: "Done", failed: "Failed", retry: "Re-asking" } as const;

export default function Trace({ lines }: { lines: TraceLine[] }) {
  return (
    <section aria-labelledby="trace-h" className="rounded-lg border border-slate-300 bg-white p-4">
      <h2 id="trace-h" className="mb-3 text-base font-semibold">Live trace</h2>
      {lines.length === 0 ? (
        <p className="text-sm text-slate-600">Steps appear here while a check runs.</p>
      ) : (
        <ol aria-live="polite" className="space-y-2 text-sm">
          {lines.map((l, i) => (
            <li key={i} className="flex gap-2">
              <span aria-hidden className="w-4 shrink-0 text-center font-bold">
                {l.state === "running" ? (
                  <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-slate-500 border-t-transparent motion-reduce:animate-none" />
                ) : (
                  MARK[l.state]
                )}
              </span>
              <span className="sr-only">{SR[l.state]}: </span>
              <span>
                <span className="font-medium">{l.step}{l.claim_id ? ` (${l.claim_id})` : ""}</span>
                {l.state === "retry" && <span className="font-medium"> re-asking.</span>}
                {l.message && <span className="text-slate-700"> {l.message}</span>}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
