import type { Citation, ClaimReport } from "@/lib/types";
import { locateQuote } from "@/lib/quote";

const STANCE = { supports: "＋ Supports", refutes: "－ Refutes", neutral: "· Context" } as const;

function lookup(c: ClaimReport, cite: Citation) {
  const g = c.evidence?.guardian.find((e) => e.id === cite.evidence_id);
  if (g) return { kind: "Article", name: g.source_name, title: g.title, url: g.url, text: g.passage, date: g.published_at };
  const f = c.evidence?.factchecks.find((e) => e.id === cite.evidence_id);
  if (f) return { kind: "Fact-check", name: f.publisher, title: `Rated “${f.raw_rating}”`, url: f.url, text: f.claim_reviewed, date: null };
  return null;
}

const when = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : null;

export default function Evidence({ claim, cite, index }: { claim: ClaimReport; cite: Citation; index: number }) {
  const src = lookup(claim, cite);
  const span = src ? locateQuote(src.text, cite.quote) : null;
  const safe = src && /^https?:\/\//.test(src.url);
  return (
    <li className="rise rounded-xl border border-rule bg-paper/50 p-4" style={{ ["--d" as string]: `${200 + index * 110}ms` }}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-xs text-muted">
        <span className="font-mono uppercase tracking-wider">{src ? `${src.kind} · ${src.name}` : `Source ${cite.evidence_id}`}{when(src?.date) ? ` · ${when(src?.date)}` : ""}</span>
        <span className="font-medium text-ink">{STANCE[cite.stance]}</span>
      </div>
      {src && (
        <p className="mt-1 font-display text-base font-semibold leading-snug">
          {safe ? (
            <a href={src.url} target="_blank" rel="noopener noreferrer" className="underline decoration-rule decoration-2 underline-offset-4 hover:decoration-accent">
              {src.title}<span aria-hidden> ↗</span><span className="sr-only"> (opens in a new tab)</span>
            </a>
          ) : src.title}
        </p>
      )}
      <blockquote className="mt-2 border-l-[3px] border-accent/50 pl-3 text-[0.95rem] leading-relaxed text-ink/90">
        {span ? (<>{span.before}<mark className="rounded-sm bg-mark px-0.5 font-medium text-ink">{span.match}</mark>{span.after}</>) : <em>{cite.quote}</em>}
      </blockquote>
    </li>
  );
}
