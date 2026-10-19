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
