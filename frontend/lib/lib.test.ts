import { test } from "node:test";
import assert from "node:assert/strict";
import { parseSse } from "./sse.ts";
import { reducer, initialState, type State } from "./reducer.ts";
import { locateQuote } from "./quote.ts";
import { confidenceLabel, consensusText } from "./labels.ts";
import { imageProblem } from "./image.ts";
import { stageStates } from "./pipeline.ts";
import type { FinalReport, SseEvent } from "./types.ts";

const tr = (step: string, status: string, message = "", claim_id: string | null = null) =>
  ({ type: "trace", run_id: "r", step, status, claim_id, message }) as SseEvent;
const report = { run_id: "r", overall_label: "TRUE" } as FinalReport;
const done = { type: "done", run_id: "r", cost_usd: 0, latency_ms: 1, tokens_in: 1, tokens_out: 1, cached: false } as SseEvent;
const run = (events: SseEvent[], from: State = reducer(initialState, { type: "start" })) =>
  events.reduce((s, event) => reducer(s, { type: "event", event }), from);

test("parser: event split across chunks", () => {
  const a = parseSse("", 'data: {"type":"done","run');
  assert.equal(a.events.length, 0);
  const b = parseSse(a.rest, '_id":"x"}\n\n');
  assert.equal(b.events.length, 1);
  assert.equal(b.rest, "");
});

test("parser: several events in one chunk, CRLF", () => {
  const { events, rest } = parseSse("", 'data: {"type":"trace"}\r\n\r\ndata: {"type":"done"}\r\n\r\ndata: {"ty');
  assert.deepEqual(events.map((e) => e.type), ["trace", "done"]);
  assert.equal(rest, 'data: {"ty');
});

test("parser: malformed and unknown messages are skipped", () => {
  const { events } = parseSse("", 'data: {not json\n\ndata: {"type":"weird"}\n\n: comment\n\ndata: {"type":"error"}\n\n');
  assert.deepEqual(events.map((e) => e.type), ["error"]);
});

test("reducer: start, trace lifecycle, verdict, done", () => {
  let s = run([tr("normalize", "started", "Reading")]);
  assert.equal(s.trace[0].state, "running");
  s = run([tr("normalize", "completed", "Read")], s);
  assert.equal(s.trace.length, 1);
  assert.equal(s.trace[0].state, "ok");
  s = run([{ type: "verdict", report }, done], s);
  assert.equal(s.status, "done");
  assert.equal(s.report, report);
});

test("reducer: failed validator shows a retry line then a new running line", () => {
  let s = run([tr("validate", "started", "", "c1"), tr("validate", "retry", "Re-asking: quote not found", "c1")]);
  assert.equal(s.trace[0].state, "retry");
  s = run([tr("verdict", "started", "", "c1")], s);
  assert.equal(s.trace.length, 2);
});

test("reducer: error event, then done keeps the error", () => {
  const s = run([{ type: "error", message: "Bad link", code: "unsafe_url" }, done]);
  assert.equal(s.status, "error");
  assert.equal(s.error, "Bad link");
  assert.ok(s.done);
});

test("reducer: done without a verdict is an error", () => {
  assert.equal(run([done]).status, "error");
});

test("reducer: cancel returns to idle and stops running lines; late events ignored", () => {
  let s = run([tr("normalize", "started")]);
  s = reducer(s, { type: "cancel" });
  assert.equal(s.status, "idle");
  assert.equal(s.trace[0].state, "failed");
  assert.equal(run([{ type: "verdict", report }], s).report, null);
});

test("reducer: network failure", () => {
  assert.equal(reducer(reducer(initialState, { type: "start" }), { type: "fail", message: "x" }).status, "error");
});

test("quote: exact span", () => {
  assert.deepEqual(locateQuote("The sky is blue today.", "is blue"), { before: "The sky ", match: "is blue", after: " today." });
});

test("quote: not found and empty", () => {
  assert.equal(locateQuote("abc", "xyz"), null);
  assert.equal(locateQuote("abc", ""), null);
});

test("quote: repeated text highlights the first occurrence", () => {
  const r = locateQuote("go go go", "go");
  assert.equal(r?.before, "");
  assert.equal(r?.after, " go go");
});

test("confidence label bounds", () => {
  assert.deepEqual([0.9, 0.75, 0.6, 0.5, 0.49, 0].map(confidenceLabel), ["High", "High", "Medium", "Medium", "Low", "Low"]);
});

test("consensus text", () => {
  assert.equal(consensusText(0.67, 3), "2 of 3 cited sources agree");
  assert.equal(consensusText(0, 0), "No cited sources");
  assert.equal(consensusText(0.5, 2, "MISLEADING"), "Cited sources are mixed");
});

test("image validation", () => {
  assert.equal(imageProblem({ type: "image/png", size: 10 }), null);
  assert.ok(imageProblem({ type: "image/gif", size: 10 }));
  assert.ok(imageProblem({ type: "image/jpeg", size: 5 * 1024 * 1024 + 1 }));
});

test("pipeline stages follow the furthest step reached", () => {
  assert.deepEqual(stageStates([], "running"), ["pending", "pending", "pending", "pending", "pending", "pending"]);
  const mid = stageStates([{ step: "normalize" }, { step: "retrieve" }, { step: "retrieve" }], "running");
  assert.deepEqual(mid, ["done", "done", "active", "pending", "pending", "pending"]);
  assert.equal(stageStates([{ step: "verdict" }], "error")[3], "failed");
  assert.ok(stageStates([{ step: "normalize" }], "done").every((s) => s === "done"));
});

import { componentSummary, factorName, factorRows, parseRetryAfter, rateLimitMessage } from "./report.ts";
import { HIGH_CONFIDENCE, MEDIUM_CONFIDENCE } from "./labels.ts";
import { STEP_NAME } from "./pipeline.ts";

test("components: summary counts and skips zero groups", () => {
  const p = (status: "supported" | "contradicted" | "unknown") => ({ name: "x", kind: "other" as const, status, evidence_ids: [] });
  assert.equal(componentSummary([p("supported"), p("supported"), p("unknown")]), "3 parts: 2 supported, 1 not found");
  assert.equal(componentSummary([p("contradicted")]), "1 part: 1 contradicted");
});

test("factors: known keys get plain names, unknown are humanised, values clamped, junk dropped", () => {
  assert.equal(factorName("quotes_verified"), "Quotes verified");
  assert.equal(factorName("source_age"), "Source age");
  const rows = factorRows({ model_quality: 1.4, judge_agreement: Number.NaN, quotes_verified: 0.5 });
  assert.deepEqual(rows.map((r) => [r.name, r.value]), [["Model quality", 1], ["Quotes verified", 0.5]]);
  assert.deepEqual(factorRows(undefined), []);
});

test("retry-after: seconds parsed, bad values ignored", () => {
  assert.equal(parseRetryAfter("12"), 12);
  assert.equal(parseRetryAfter("0"), null);
  assert.equal(parseRetryAfter("Wed, 21 Oct 2026 07:28:00 GMT"), null);
  assert.equal(parseRetryAfter(null), null);
  assert.equal(rateLimitMessage("30"), "Too many checks at once, try again in 30 seconds.");
  assert.equal(rateLimitMessage("1"), "Too many checks at once, try again in 1 second.");
  assert.equal(rateLimitMessage("x"), "Too many checks at once, try again in a moment.");
});

test("labels: cutoffs are exported and applied", () => {
  assert.equal(confidenceLabel(HIGH_CONFIDENCE), "High");
  assert.equal(confidenceLabel(MEDIUM_CONFIDENCE), "Medium");
  assert.equal(confidenceLabel(MEDIUM_CONFIDENCE - 0.01), "Low");
  assert.equal(STEP_NAME.second_opinion, "Getting a second opinion");
});
