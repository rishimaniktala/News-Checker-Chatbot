export interface QuoteSpan {
  before: string;
  match: string;
  after: string;
}

/** Splits text around the first exact occurrence of quote; null if absent. */
export function locateQuote(text: string, quote: string): QuoteSpan | null {
  if (!quote) return null;
  const i = text.indexOf(quote);
  if (i < 0) return null;
  return { before: text.slice(0, i), match: quote, after: text.slice(i + quote.length) };
}

export interface Segment {
  text: string;
  hit: boolean;
}

const QUOTE_CHARS: Record<string, string> = { "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-" };

/** Lower-noise form of text (typographic quotes, dashes, invisible characters, spacing) plus a map back to the original indices. */
function normalize(text: string): { s: string; map: number[] } {
  let s = "";
  const map: number[] = [];
  let prevSpace = false;
  for (let i = 0; i < text.length; i++) {
    for (let c of text[i].normalize("NFKC")) {
      if (/[­​-‏⁠﻿]/.test(c)) continue;
      if (/\s/.test(c)) {
        if (prevSpace) continue;
        c = " ";
        prevSpace = true;
      } else {
        prevSpace = false;
      }
      s += QUOTE_CHARS[c] ?? c;
      map.push(i);
    }
  }
  return { s, map };
}

/**
 * Splits text into plain and highlighted pieces for a quote. Matches the way the backend checks quotes:
 * typographic quotes and spacing are ignored, and a quote joined with "..." highlights each fragment in order.
 * Returns null if any fragment is missing.
 */
export function locateSegments(text: string, quote: string): Segment[] | null {
  const t = normalize(text);
  const fragments = normalize(quote).s.split(/\.{3}|…/).map((f) => f.trim()).filter(Boolean);
  if (fragments.length === 0) return null;
  const ranges: [number, number][] = [];
  let from = 0;
  for (const f of fragments) {
    const i = t.s.indexOf(f, from);
    if (i < 0) return null;
    ranges.push([t.map[i], t.map[i + f.length - 1] + 1]);
    from = i + f.length;
  }
  const out: Segment[] = [];
  let pos = 0;
  for (const [a, b] of ranges) {
    if (a > pos) out.push({ text: text.slice(pos, a), hit: false });
    out.push({ text: text.slice(a, b), hit: true });
    pos = b;
  }
  if (pos < text.length) out.push({ text: text.slice(pos), hit: false });
  return out;
}
