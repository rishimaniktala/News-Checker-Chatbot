import type { ClaimReport, Citation, FinalReport, Label } from "@/lib/types";
import { LABEL_TEXT, confidenceLabel, consensusText } from "@/lib/labels";
import { locateQuote } from "@/lib/quote";

const BADGE: Record<Label, string> = {
  TRUE: "border-green-800 bg-green-50 text-green-900",
  FALSE: "border-red-800 bg-red-50 text-red-900",
  MISLEADING: "border-amber-800 bg-amber-50 text-amber-900",
  UNVERIFIABLE: "border-slate-500 bg-slate-100 text-slate-800",
};

function Badge({ label }: { label: Label }) {
  return <span className={`inline-block rounded-md border px-2 py-1 text-sm font-semibold ${BADGE[label]}`}>{LABEL_TEXT[label]}</span>;
}

function source(c: ClaimReport, cite: Citation) {
  const g = c.evidence?.guardian.find((e) => e.id === cite.evidence_id);
  if (g) return { name: g.source_name, title: g.title, url: g.url, text: g.passage };
  const f = c.evidence?.factchecks.find((e) => e.id === cite.evidence_id);
  if (f) return { name: f.publisher, title: `Rated "${f.raw_rating}"`, url: f.url, text: f.claim_reviewed };
  return null;
}

function EvidenceCard({ claim, cite }: { claim: ClaimReport; cite: Citation }) {
  const src = source(claim, cite);
  const span = src ? locateQuote(src.text, cite.quote) : null;
  return (
    <li className="rounded-md border border-slate-300 p-3 text-sm">
      {src ? (
        <p className="font-medium">
          {src.name}:{" "}
          {/^https?:\/\//.test(src.url) ? (
            <a href={src.url} target="_blank" rel="noopener noreferrer" className="text-blue-800 underline">{src.title}</a>
          ) : (
            src.title
          )}
        </p>
      ) : (
        <p className="font-medium">Source {cite.evidence_id}</p>
      )}
      <p className="mt-1 text-xs uppercase tracking-wide text-slate-600">Stance: {cite.stance}</p>
      <blockquote className="mt-2 border-l-4 border-slate-300 pl-3 text-slate-800">
        {span ? (
          <>
            {span.before}
            <mark className="bg-yellow-200 font-medium text-slate-900 underline decoration-yellow-700">{span.match}</mark>
            {span.after}
          </>
        ) : (
          cite.quote
        )}
      </blockquote>
    </li>
  );
}

function ClaimBlock({ claim }: { claim: ClaimReport }) {
  const c = claim.consensus;
  return (
    <div className="space-y-3 border-t border-slate-200 pt-4 first:border-0 first:pt-0">
      <h3 className="text-sm font-semibold">{claim.claim.text}</h3>
      <p className="flex flex-wrap items-center gap-2">
        <Badge label={claim.label} />
        <span className="text-sm">Confidence: {confidenceLabel(claim.confidence)}</span>
      </p>
      <p className="text-sm">{claim.answer}</p>
      <p className="text-sm text-slate-700">{claim.reasoning}</p>
      <div>
        <p className="text-sm font-medium">{consensusText(c.agreement_ratio, claim.citations.length)}</p>
        <div
          role="img"
          aria-label={consensusText(c.agreement_ratio, claim.citations.length)}
          className="mt-1 h-2 w-full overflow-hidden rounded bg-slate-200"
        >
          <div className="h-full bg-slate-700" style={{ width: `${Math.round(c.agreement_ratio * 100)}%` }} />
        </div>
        {c.single_source && <p className="mt-1 text-xs text-slate-700">Only one kind of source had usable evidence.</p>}
        {c.conflict && <p className="mt-1 text-xs font-medium text-amber-900">This disagrees with a published fact-check.</p>}
      </div>
      {claim.citations.length > 0 && (
        <ul className="space-y-2">
          {claim.citations.map((cite, i) => <EvidenceCard key={i} claim={claim} cite={cite} />)}
        </ul>
      )}
    </div>
  );
}

export default function Verdict({ report }: { report: FinalReport }) {
  return (
    <section aria-labelledby="verdict-h" className="space-y-4 rounded-lg border border-slate-300 bg-white p-4">
      <h2 id="verdict-h" className="text-base font-semibold">Verdict</h2>
      <p className="flex flex-wrap items-center gap-2">
        <Badge label={report.overall_label} />
        <span className="text-sm">Confidence: {confidenceLabel(report.overall_confidence)}</span>
      </p>
      <p className="text-base">{report.answer}</p>
      {report.claims.map((c) => <ClaimBlock key={c.claim.id} claim={c} />)}
      {report.skipped_claims.length > 0 && (
        <div className="border-t border-slate-200 pt-3 text-sm">
          <p className="font-medium">Not checked</p>
          <ul className="list-disc pl-5 text-slate-700">
            {report.skipped_claims.map((s) => <li key={s.id}>{s.text}{s.skip_reason ? ` (${s.skip_reason})` : ""}</li>)}
          </ul>
        </div>
      )}
      <p className="border-t border-slate-200 pt-3 text-xs text-slate-700">{report.disclaimer}</p>
    </section>
  );
}
