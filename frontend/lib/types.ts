export type Label = "TRUE" | "FALSE" | "MISLEADING" | "UNVERIFIABLE";
export type StepStatus = "started" | "completed" | "retry" | "failed";

export interface Citation {
  evidence_id: string;
  quote: string;
  stance: "supports" | "refutes" | "neutral";
}

export interface EvidenceItem {
  id: string;
  source_name: string;
  url: string;
  title: string;
  published_at?: string | null;
  passage: string;
}

export interface FactCheckReview {
  id: string;
  publisher: string;
  url: string;
  claim_reviewed: string;
  raw_rating: string;
}

export type ComponentStatus = "supported" | "contradicted" | "unknown";

export interface ComponentCheck {
  name: string;
  kind: "actor" | "action" | "time" | "quantity" | "place" | "other";
  status: ComponentStatus;
  evidence_ids: string[];
  note?: string | null;
}

export interface ClaimReport {
  claim: { id: string; text: string };
  label: Label;
  confidence: number;
  answer: string;
  reasoning: string;
  citations: Citation[];
  evidence?: { guardian: EvidenceItem[]; factchecks: FactCheckReview[] } | null;
  consensus: {
    agreement_ratio: number;
    single_source: boolean;
    conflict: boolean;
    notes?: string | null;
  };
  components?: ComponentCheck[];
  model_used?: string | null;
  fallback_used?: boolean;
  independent_sources?: number | null;
  confidence_factors?: Record<string, number>;
}

export interface FinalReport {
  run_id: string;
  overall_label: Label;
  overall_confidence: number;
  claims: ClaimReport[];
  skipped_claims: { id: string; text: string; skip_reason?: string | null }[];
  answer: string;
  disclaimer: string;
  prompt_version?: string | null;
  models_used?: string[];
}

export interface TraceEvent {
  type: "trace";
  run_id: string;
  step: string;
  status: StepStatus;
  claim_id?: string | null;
  message: string;
}

export interface DoneEvent {
  type: "done";
  run_id: string;
  cost_usd: number;
  latency_ms: number;
  tokens_in: number;
  tokens_out: number;
  cached: boolean;
  models_used?: string[];
  fallback_used?: boolean;
}

export type SseEvent =
  | TraceEvent
  | { type: "verdict"; report: FinalReport }
  | { type: "error"; message: string; code: string }
  | DoneEvent;

export type CheckRequest =
  | { kind: "text"; text: string }
  | { kind: "url"; url: string }
  | { kind: "image"; image_b64: string; mime: string };
