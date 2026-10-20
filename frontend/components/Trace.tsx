import { STEP_NAME } from "@/lib/pipeline";
import type { TraceLine } from "@/lib/reducer";

const RETRY_NOTE: Record<string, string> = {
  validate: "fixing a quote",
  retrieve: "searching again with new queries",
};
const SR = { running: "Running", ok: "Done", failed: "Failed", retry: "Re-asking" } as const;

function Mark({ state }: { state: TraceLine["state"] }) {
  if (state === "running") return <span className="mt-1 inline-block h-2.5 w-2.5 animate-spin rounded-full border-2 border-accent border-t-transparent motion-reduce:animate-none" />;
  const glyph = { ok: "✓", failed: "✗", retry: "↻" }[state];
  const tone = { ok: "text-ok", failed: "text-accent", retry: "text-warn" }[state];
  return <span className={`font-bold ${tone}`}>{glyph}</span>;
}

export default function Trace({ lines, running }: { lines: TraceLine[]; running: boolean }) {
  return (
    <section aria-labelledby="trace-h" className="rounded-2xl border border-rule bg-card p-4 sm:p-5">
      <h2 id="trace-h" className="mb-3 flex items-center gap-2 font-mono text-xs uppercase tracking-[0.18em] text-muted">
        <span className={`h-2 w-2 rounded-full ${running ? "bg-accent pulse-ring" : "bg-rule"}`} aria-hidden /> The wire
      </h2>
      {lines.length === 0 ? (
        <p className="font-mono text-sm text-muted">Every step shows up here, live, as it happens.</p>
      ) : (
        <ol aria-live="polite" className="space-y-2 font-mono text-[0.8rem] leading-snug">
          {lines.map((l, i) => (
            <li key={i} className="rise flex gap-2.5" style={{ ["--d" as string]: "0ms" }}>
              <span aria-hidden className="w-3.5 shrink-0 text-center">
                <Mark state={l.state} />
              </span>
              <span className="sr-only">{SR[l.state]}: </span>
              <span className="min-w-0">
                <span className="font-medium text-ink">{STEP_NAME[l.step] ?? l.step}</span>
                {l.claim_id && <span className="ml-1.5 rounded bg-rule/60 px-1 text-[0.65rem] text-muted">{l.claim_id}</span>}
                {l.state === "retry" && <span className="ml-1 text-warn"> {RETRY_NOTE[l.step] ?? "trying again"}</span>}
                {l.message && <span className="block break-words text-muted">{l.message}</span>}
              </span>
            </li>
          ))}
          {running && <li aria-hidden className="caret pl-6 text-muted">working</li>}
        </ol>
      )}
    </section>
  );
}
