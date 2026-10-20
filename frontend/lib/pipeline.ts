export const STAGES = [
  { id: "normalize", label: "Read" },
  { id: "extract_claims", label: "Find claims" },
  { id: "retrieve", label: "Search" },
  { id: "verdict", label: "Judge" },
  { id: "validate", label: "Verify" },
  { id: "consensus", label: "Cross-check" },
] as const;

export type StageState = "done" | "active" | "failed" | "pending";
type RunStatus = "idle" | "running" | "done" | "error";

/** Where the run has got to, taken from the furthest step seen in the trace. */
export function stageStates(trace: { step: string }[], status: RunStatus): StageState[] {
  if (status === "done") return STAGES.map(() => "done");
  const reached = trace.reduce((m, l) => Math.max(m, STAGES.findIndex((s) => s.id === l.step)), -1);
  return STAGES.map((_, i) => (i < reached ? "done" : i === reached ? (status === "error" ? "failed" : status === "running" ? "active" : "pending") : "pending"));
}

export const STEP_NAME: Record<string, string> = {
  normalize: "Reading the input",
  extract_claims: "Finding the claims",
  retrieve: "Searching sources",
  verdict: "Judging",
  validate: "Checking the quotes",
  second_opinion: "Getting a second opinion",
  consensus: "Cross-checking",
};
