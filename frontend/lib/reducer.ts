import type { DoneEvent, FinalReport, SseEvent } from "./types.ts";

export interface TraceLine {
  key: string;
  step: string;
  claim_id: string | null;
  message: string;
  state: "running" | "ok" | "failed" | "retry";
}

export interface State {
  status: "idle" | "running" | "done" | "error";
  trace: TraceLine[];
  report: FinalReport | null;
  error: string | null;
  done: DoneEvent | null;
}

export type Action =
  | { type: "start" }
  | { type: "event"; event: SseEvent }
  | { type: "fail"; message: string }
  | { type: "cancel" }
  | { type: "reset" };

export const initialState: State = { status: "idle", trace: [], report: null, error: null, done: null };

const keyOf = (step: string, claim: string | null | undefined) => `${step}:${claim ?? ""}`;

function applyTrace(trace: TraceLine[], e: Extract<SseEvent, { type: "trace" }>): TraceLine[] {
  const claim = e.claim_id ?? null;
  const key = keyOf(e.step, claim);
  const idx = trace.findLastIndex((l) => l.key === key && l.state === "running");
  const line = (state: TraceLine["state"]): TraceLine => ({ key, step: e.step, claim_id: claim, message: e.message, state });
  if (e.status === "started") return [...trace, line("running")];
  const state = e.status === "completed" ? "ok" : e.status === "failed" ? "failed" : "retry";
  if (idx < 0) return [...trace, line(state)];
  const next = [...trace];
  next[idx] = { ...next[idx], message: e.message || next[idx].message, state };
  return next;
}

export function reducer(s: State, a: Action): State {
  switch (a.type) {
    case "start":
      return { ...initialState, status: "running" };
    case "reset":
      return initialState;
    case "cancel":
      return {
        ...s,
        status: "idle",
        trace: s.trace.map((l) => (l.state === "running" ? { ...l, state: "failed", message: "Cancelled" } : l)),
      };
    case "fail":
      return { ...s, status: "error", error: a.message };
    case "event": {
      const e = a.event;
      if (e.type === "done" && s.status === "error") return { ...s, done: e };
      if (s.status !== "running") return s;
      if (e.type === "trace") return { ...s, trace: applyTrace(s.trace, e) };
      if (e.type === "verdict") return { ...s, report: e.report };
      if (e.type === "error") return { ...s, status: "error", error: e.message };
      if (!s.report) return { ...s, status: "error", error: "The check ended without a result.", done: e };
      return { ...s, status: "done", done: e };
    }
  }
}
