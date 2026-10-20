import type { Label } from "./types.ts";

export const HIGH_CONFIDENCE = 0.75;
export const MEDIUM_CONFIDENCE = 0.5;

export function confidenceLabel(c: number): "High" | "Medium" | "Low" {
  return c >= HIGH_CONFIDENCE ? "High" : c >= MEDIUM_CONFIDENCE ? "Medium" : "Low";
}

export const LABEL_TEXT: Record<Label, string> = {
  TRUE: "Supported",
  FALSE: "Contradicted",
  MISLEADING: "Misleading",
  UNVERIFIABLE: "Not enough evidence",
};

export function consensusText(agreementRatio: number, cited: number, label?: Label): string {
  if (cited === 0) return "No cited sources";
  if (label === "MISLEADING") return "Cited sources are mixed";
  const n = Math.round(agreementRatio * cited);
  return `${n} of ${cited} cited sources agree`;
}
