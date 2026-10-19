import { parseSse } from "./sse.ts";
import type { CheckRequest, SseEvent } from "./types.ts";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/** POSTs the request and yields SSE events as they arrive. Throws on network or HTTP failure. */
export async function* streamCheck(req: CheckRequest, signal: AbortSignal): AsyncGenerator<SseEvent> {
  const res = await fetch(`${API_BASE}/api/check`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(req),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`The server answered with status ${res.status}.`);
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let rest = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    const parsed = parseSse(rest, value);
    rest = parsed.rest;
    yield* parsed.events;
  }
}
