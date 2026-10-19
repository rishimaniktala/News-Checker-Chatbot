import type { ClaimReport } from "@/lib/types";
import Stamp from "./Stamp";
import Confidence from "./Confidence";
import Consensus from "./Consensus";
import Evidence from "./Evidence";

export default function ClaimCard({ claim, lead }: { claim: ClaimReport; lead: boolean }) {
  const c = claim.consensus;
  return (
    <article className="space-y-4">
      <p className="font-mono text-xs uppercase tracking-[0.16em] text-muted">The claim</p>
      <h3 className="-mt-2 font-display text-xl leading-snug sm:text-2xl">“{claim.claim.text}”</h3>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <Stamp label={claim.label} size={lead ? "lg" : "sm"} />
        <Confidence value={claim.confidence} />
      </div>
      <p className="rise text-lg font-medium leading-snug" style={{ ["--d" as string]: "250ms" }}>{claim.answer}</p>
      <p className="rise max-w-prose text-[0.95rem] leading-relaxed text-muted" style={{ ["--d" as string]: "330ms" }}>{claim.reasoning}</p>
      {claim.citations.length > 0 && (
        <>
          <Consensus ratio={c.agreement_ratio} cited={claim.citations.length} label={claim.label} singleSource={c.single_source} conflict={c.conflict} />
          <ul className="space-y-3">
            {claim.citations.map((cite, i) => <Evidence key={i} claim={claim} cite={cite} index={i} />)}
          </ul>
        </>
      )}
    </article>
  );
}
