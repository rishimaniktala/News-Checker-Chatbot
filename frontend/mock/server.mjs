// Mock of POST /api/check for UI work. Scenario is picked from the input text:
//   "error" -> error event, "fourth primary" -> not enough evidence,
//   "429" -> HTTP 429 with Retry-After, "second opinion" -> components, fallback model, second-opinion step,
//   "shut down" -> contradicted (with a validator retry), anything else -> supported.
import http from "node:http";

const PORT = 8000;
const ORIGIN = "http://localhost:3000";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const RUN = "run_mock_0001";

const trace = (step, status, message, claim_id = null) => ({ type: "trace", run_id: RUN, step, status, claim_id, message, payload: null, ts: new Date().toISOString() });
const done = { type: "done", run_id: RUN, cost_usd: 0.0123, latency_ms: 4200, tokens_in: 5120, tokens_out: 640, cached: false };

const passage = "Sweden formally became the 32nd member of NATO on 7 March 2024, after Hungary ratified its accession. The move ended two centuries of military non-alignment.";
const guardian = { id: "E1", source_name: "The Guardian", url: "https://www.theguardian.com/world/2024/mar/07/sweden-joins-nato", title: "Sweden joins Nato as 32nd member", published_at: "2024-03-07T12:00:00Z", passage, rerank_score: 0.91 };
const factcheck = { id: "F1", publisher: "Example Fact Check", url: "https://example.org/factcheck/anthropic", claim_reviewed: "Anthropic has shut down.", raw_rating: "False" };

function claimReport(label, confidence, text, answer, reasoning, citations, evidence, ratio) {
  return {
    claim: { id: "c1", text, checkworthy: true, search_queries: [], time_sensitivity: "recent" },
    label, confidence, answer, reasoning, citations, evidence,
    consensus: { claim_id: "c1", final_label: label, final_confidence: confidence, agreement_ratio: ratio, single_source: false, conflict: false, label_changed: false },
    attempts: 1,
  };
}
function finalReport(c, answer) {
  return {
    run_id: RUN, input: { input_type: "text", text: c.claim.text }, overall_label: c.label, overall_confidence: c.confidence,
    claims: [c], skipped_claims: [{ id: "c2", text: "NATO is the best alliance.", checkworthy: false, skip_reason: "opinion" }], answer,
    disclaimer: "Verdicts reflect what The Guardian and published fact-checks report, not independently established truth.",
  };
}

function scenario(text) {
  const t = text.toLowerCase();
  const steps = (retry) => [
    [300, trace("normalize", "started", "Reading the input")],
    [500, trace("normalize", "completed", "Input is plain text")],
    [300, trace("extract_claims", "started", "Finding checkable claims")],
    [700, trace("extract_claims", "completed", "1 claim found, 1 skipped as opinion")],
    [300, trace("retrieve", "started", "Searching The Guardian and fact-checks", "c1")],
    [800, trace("retrieve", "completed", "Found 1 article and 1 fact-check", "c1")],
    [300, trace("verdict", "started", "Asking the model for a verdict", "c1")],
    ...(retry
      ? [
          [800, trace("verdict", "completed", "Verdict drafted", "c1")],
          [300, trace("validate", "started", "Checking every quote against the sources", "c1")],
          [500, trace("validate", "retry", "Quote not found in E1, re-asking", "c1")],
          [300, trace("verdict", "started", "Asking again with the failure noted", "c1")],
        ]
      : []),
    [800, trace("verdict", "completed", "Verdict drafted", "c1")],
    [300, trace("validate", "started", "Checking every quote against the sources", "c1")],
    [500, trace("validate", "completed", "All quotes found", "c1")],
    [300, trace("consensus", "started", "Comparing sources", "c1")],
    [400, trace("consensus", "completed", "Sources agree", "c1")],
  ];
  if (t.includes("error"))
    return [[300, trace("normalize", "started", "Reading the input")], [600, trace("normalize", "failed", "Could not read the input")], [200, { type: "error", message: "We could not read that input. Try pasting the text of the claim instead.", code: "bad_input" }], [100, done]];
  if (t.includes("fourth primary")) {
    const c = claimReport("UNVERIFIABLE", 0.3, "A man in Ohio invented a fourth primary colour.", "I couldn't confirm this.", "No article or fact-check covers this claim, so there is nothing to base a verdict on.", [], { claim_id: "c1", guardian: [], factchecks: [] }, 0);
    return [...steps(false).slice(0, 6), [300, trace("verdict", "started", "Asking the model for a verdict", "c1")], [600, trace("verdict", "completed", "No usable evidence", "c1")], [300, { type: "verdict", report: finalReport(c, "I couldn't confirm this.") }], [100, done]];
  }
  if (t.includes("second opinion")) {
    const c = claimReport("MISLEADING", 0.58, "Sweden joined NATO in 2023.", "Partly. Sweden joined NATO, but in 2024, not 2023.", "The Guardian dates the accession to 7 March 2024.", [{ evidence_id: "E1", quote: "became the 32nd member of NATO on 7 March 2024", stance: "refutes" }], { claim_id: "c1", guardian: [guardian], factchecks: [] }, 0.5);
    Object.assign(c, {
      components: [
        { name: "Sweden joined NATO", kind: "action", status: "supported", evidence_ids: ["E1"], note: "The Guardian reports the accession." },
        { name: "in 2023", kind: "time", status: "contradicted", evidence_ids: ["E1"], note: "It happened in March 2024." },
        { name: "as the 32nd member", kind: "quantity", status: "unknown", evidence_ids: [], note: null },
      ],
      model_used: "gemini-3.5-flash-lite", fallback_used: true, independent_sources: 1,
      confidence_factors: { independent_sources: 0.35, quotes_verified: 1, factcheck_agreement: 0.5, judge_agreement: 0.6, model_quality: 0.4 },
    });
    const report = { ...finalReport(c, c.answer), prompt_version: "v2.1", models_used: ["gemini-3.6-flash", "gemini-3.5-flash-lite"] };
    return [...steps(false).slice(0, 14), [300, trace("second_opinion", "started", "Asking a second model", "c1")], [800, trace("second_opinion", "completed", "Second opinion agrees", "c1")], [300, { type: "verdict", report }], [100, { ...done, cached: true, models_used: report.models_used, fallback_used: true }]];
  }
  if (t.includes("shut down")) {
    const c = claimReport("FALSE", 0.88, "Anthropic has shut down.", "No, Anthropic has not shut down.", "A published fact-check rates this claim False.", [{ evidence_id: "F1", quote: "Anthropic has shut down.", stance: "refutes" }], { claim_id: "c1", guardian: [], factchecks: [factcheck] }, 1);
    return [...steps(true), [300, { type: "verdict", report: finalReport(c, "No, Anthropic has not shut down.") }], [100, done]];
  }
  const c = claimReport("TRUE", 0.93, "Sweden joined NATO in 2024.", "Yes, Sweden joined NATO in March 2024.", "The Guardian reports Sweden became the 32nd member on 7 March 2024.", [
    { evidence_id: "E1", quote: "became the 32nd member of NATO on 7 March 2024", stance: "supports" },
    { evidence_id: "E1", quote: "a quote the model garbled", stance: "supports" },
  ], { claim_id: "c1", guardian: [guardian], factchecks: [] }, 0.5);
  c.consensus.single_source = true;
  return [...steps(false), [300, { type: "verdict", report: finalReport(c, "Yes, Sweden joined NATO in March 2024.") }], [100, done]];
}

http.createServer(async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", ORIGIN);
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  if (req.method === "OPTIONS") return res.writeHead(204).end();
  if (req.method === "GET" && req.url === "/health") return res.writeHead(200, { "Content-Type": "application/json" }).end('{"status":"ok"}');
  if (req.method !== "POST" || req.url !== "/api/check") return res.writeHead(404).end();
  let body = "";
  for await (const chunk of req) body += chunk;
  let input;
  try { input = JSON.parse(body); } catch { input = {}; }
  const text = input.text ?? input.url ?? (input.kind === "image" ? "image" : "");
  if (text.toLowerCase().includes("429")) return res.writeHead(429, { "Content-Type": "application/json", "Retry-After": "17", "Access-Control-Expose-Headers": "Retry-After" }).end('{"detail":"rate limited"}');
  res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
  let open = true;
  res.on("close", () => (open = false));
  for (const [delay, event] of scenario(text)) {
    await sleep(delay);
    if (!open) return;
    res.write(`data: ${JSON.stringify(event)}\n\n`);
  }
  res.end();
}).listen(PORT, () => console.log(`mock api on http://localhost:${PORT}`));
