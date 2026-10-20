import type { ClaimReport } from "@/lib/types";
import Stamp from "./Stamp";
import Confidence from "./Confidence";
import Consensus from "./Consensus";
import ConfidenceBreakdown from "./ConfidenceBreakdown";
import ComponentTable, { evidenceAnchor } from "./ComponentTable";
import SourcesBadge from "./SourcesBadge";
import ModelNote from "./ModelNote";
import Evidence from "./Evidence";

export default function ClaimCard({ claim, lead }: { claim: ClaimReport; lead: boolean }) {
  const c = claim.consensus;
  const cited = new Set(claim.citations.map((x) => x.evidence_id));
  return (
    <article className="space-y-4">
      <p className="font-mono text-xs uppercase tracking-[0.16em] text-muted">The claim</p>
      <h3 className="-mt-2 font-display text-xl leading-snug sm:text-2xl">“{claim.claim.text}”</h3>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <Stamp label={claim.label} size={lead ? "lg" : "sm"} />
        <Confidence value={claim.confidence} />
        <SourcesBadge count={claim.independent_sources} />
      </div>
      <ConfidenceBreakdown factors={claim.confidence_factors} />
      <ModelNote model={claim.model_used} fallback={claim.fallback_used} />
      <p className="rise text-lg font-medium leading-snug" style={{ ["--d" as string]: "250ms" }}>{claim.answer}</p>
      <p className="rise max-w-prose text-[0.95rem] leading-relaxed text-muted" style={{ ["--d" as string]: "330ms" }}>{claim.reasoning}</p>
      <ComponentTable claimId={claim.claim.id} parts={claim.components ?? []} citedIds={cited} />
      {claim.citations.length > 0 && (
        <>
          <Consensus ratio={c.agreement_ratio} cited={claim.citations.length} label={claim.label} singleSource={c.single_source} conflict={c.conflict} />
          <ul className="space-y-3">
            {claim.citations.map((cite, i) => <Evidence key={i} claim={claim} cite={cite} index={i} anchor={claim.citations.findIndex((x) => x.evidence_id === cite.evidence_id) === i ? evidenceAnchor(claim.claim.id, cite.evidence_id) : undefined} />)}
          </ul>
        </>
      )}
    </article>
  );
}
