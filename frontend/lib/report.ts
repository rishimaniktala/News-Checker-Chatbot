import { HIGH_CONFIDENCE } from "./labels.ts";
import type { ComponentCheck, ComponentStatus } from "./types.ts";

export const COMPONENT_STATUS: Record<ComponentStatus, { mark: string; word: string; explain: string }> = {
  supported: { mark: "✓", word: "Supported", explain: "The sources back this part up." },
  contradicted: { mark: "✗", word: "Contradicted", explain: "The sources say something different." },
  unknown: { mark: "?", word: "Not found", explain: "The sources do not settle this part." },
};

export function componentSummary(parts: ComponentCheck[]): string {
  const n = (s: ComponentStatus) => parts.filter((p) => p.status === s).length;
  const bits = [`${n("supported")} supported`, `${n("contradicted")} contradicted`, `${n("unknown")} not found`];
  return `${parts.length} ${parts.length === 1 ? "part" : "parts"}: ${bits.filter((b) => !b.startsWith("0 ")).join(", ")}`;
}

const FACTOR_NAME: Record<string, string> = {
  evidence_strength: "Parts of the claim settled",
  source_independence: "Independent outlets",
  corroboration: "Fact-check agreement",
  independent_sources: "Independent outlets",
  independent_outlets: "Independent outlets",
  quotes_verified: "Quotes verified",
  quote_validity: "Quotes verified",
  factcheck_agreement: "Fact-check agreement",
  judge_agreement: "Judges agreed",
  judges_agreed: "Judges agreed",
  model_quality: "Model quality",
};

export function factorName(key: string): string {
  if (FACTOR_NAME[key]) return FACTOR_NAME[key];
  const words = key.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function factorRows(factors?: Record<string, number>): { key: string; name: string; value: number }[] {
  return Object.entries(factors ?? {})
    .filter(([, v]) => typeof v === "number" && Number.isFinite(v))
    .map(([key, v]) => ({ key, name: factorName(key), value: Math.min(1, Math.max(0, v)) }));
}

export const factorStrength = (v: number) => (v >= HIGH_CONFIDENCE ? "strong" : v >= 0.5 ? "fair" : "weak");

/** Seconds from a Retry-After header, or null when it is missing or not a positive integer. */
export function parseRetryAfter(header: string | null | undefined): number | null {
  const n = Number(header?.trim());
  return header && Number.isInteger(n) && n > 0 ? n : null;
}

export function rateLimitMessage(header: string | null | undefined): string {
  const s = parseRetryAfter(header);
  return s ? `Too many checks at once, try again in ${s} ${s === 1 ? "second" : "seconds"}.` : "Too many checks at once, try again in a moment.";
}
