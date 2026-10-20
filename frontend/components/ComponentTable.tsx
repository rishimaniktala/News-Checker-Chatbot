import type { ComponentCheck } from "@/lib/types";
import { COMPONENT_STATUS, componentSummary } from "@/lib/report";

export const evidenceAnchor = (claimId: string, evidenceId: string) => `ev-${claimId}-${evidenceId}`;

const TONE = { supported: "text-ok", contradicted: "text-accent", unknown: "text-muted" } as const;

export default function ComponentTable({ claimId, parts, citedIds }: { claimId: string; parts: ComponentCheck[]; citedIds: Set<string> }) {
  if (parts.length === 0) return null;
  return (
    <section aria-labelledby={`cmp-${claimId}`} className="rise rounded-xl border border-rule bg-card/60 p-4">
      <h4 id={`cmp-${claimId}`} className="font-mono text-xs uppercase tracking-[0.16em] text-muted">What we checked</h4>
      <p className="sr-only">{componentSummary(parts)}</p>
      <ul className="mt-2 divide-y divide-rule">
        {parts.map((p, i) => {
          const s = COMPONENT_STATUS[p.status];
          return (
            <li key={i} className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 py-2.5">
              <span className={`font-mono text-sm font-semibold ${TONE[p.status]}`}>
                <span aria-hidden>{s.mark} </span>{s.word}
              </span>
              <span className="min-w-0 break-words font-medium">{p.name}</span>
              <span className="col-start-2 text-sm text-muted">
                {p.note || s.explain}
                {p.evidence_ids.length > 0 && (
                  <>
                    {" "}Sources:{" "}
                    {p.evidence_ids.map((id, k) => (
                      <span key={id}>
                        {k > 0 && ", "}
                        {citedIds.has(id) ? (
                          <a href={`#${evidenceAnchor(claimId, id)}`} className="font-mono underline decoration-rule underline-offset-4 hover:decoration-accent">{id}</a>
                        ) : <span className="font-mono">{id}</span>}
                      </span>
                    ))}
                  </>
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
