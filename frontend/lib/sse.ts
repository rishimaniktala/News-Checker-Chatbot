import type { SseEvent } from "./types.ts";

const KNOWN = new Set(["trace", "verdict", "error", "done"]);

/** Feed raw text; returns complete events plus the unfinished tail to pass back next time. */
export function parseSse(buffer: string, chunk: string): { events: SseEvent[]; rest: string } {
  const blocks = (buffer + chunk).replace(/\r\n/g, "\n").split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: SseEvent[] = [];
  for (const block of blocks) {
    const data = block
      .split("\n")
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).replace(/^ /, ""))
      .join("\n");
    if (!data) continue;
    try {
      const obj = JSON.parse(data);
      if (obj && KNOWN.has(obj.type)) events.push(obj as SseEvent);
    } catch {
      // a malformed message is dropped; the stream carries on
    }
  }
  return { events, rest };
}
