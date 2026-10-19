import type { FinalReport } from "@/lib/types";
import ClaimCard from "./ClaimCard";
import Confidence from "./Confidence";
import Stamp from "./Stamp";

export default function Verdict({ report }: { report: FinalReport }) {
  const many = report.claims.length > 1;
  return (
    <section aria-labelledby="verdict-h" className="rounded-2xl border border-rule bg-card p-5 shadow-[0_1px_0_var(--rule),0_18px_40px_-28px_rgba(0,0,0,0.35)] sm:p-7">
      <h2 id="verdict-h" className="sr-only">Verdict</h2>

      {report.claims.length === 0 && (
        <div className="rise space-y-3">
          <p className="font-mono text-xs uppercase tracking-[0.16em] text-muted">Nothing to check</p>
          <p className="font-display text-xl leading-snug sm:text-2xl">{report.answer}</p>
        </div>
      )}

      {many && (
        <div className="mb-6 space-y-3 border-b border-rule pb-6">
          <p className="font-mono text-xs uppercase tracking-[0.16em] text-muted">Overall</p>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            <Stamp label={report.overall_label} />
            <Confidence value={report.overall_confidence} />
          </div>
        </div>
      )}

      <div className="space-y-8 divide-y divide-rule [&>*:not(:first-child)]:pt-8">
        {report.claims.map((c, i) => <ClaimCard key={c.claim.id} claim={c} lead={!many || i === 0} />)}
      </div>

      {report.skipped_claims.length > 0 && (
        <div className="mt-6 rounded-xl border border-dashed border-rule p-4 text-sm">
          <p className="font-medium">Left unchecked</p>
          <ul className="mt-1 space-y-1 text-muted">
            {report.skipped_claims.map((s) => (
              <li key={s.id}>“{s.text}”{s.skip_reason ? <span className="ml-1 rounded bg-rule/60 px-1.5 py-0.5 text-xs">{s.skip_reason}</span> : null}</li>
            ))}
          </ul>
        </div>
      )}

      <p className="mt-6 border-t border-rule pt-4 text-xs leading-relaxed text-muted">{report.disclaimer}</p>
    </section>
  );
}
