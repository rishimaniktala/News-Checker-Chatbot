import type { Label } from "@/lib/types";
import { LABEL_TEXT } from "@/lib/labels";

const LOOK: Record<Label, { glyph: string; tone: string }> = {
  TRUE: { glyph: "✓", tone: "text-ok border-ok" },
  FALSE: { glyph: "✗", tone: "text-accent border-accent" },
  MISLEADING: { glyph: "≈", tone: "text-warn border-warn" },
  UNVERIFIABLE: { glyph: "?", tone: "text-neutral border-neutral" },
};

export default function Stamp({ label, size = "lg" }: { label: Label; size?: "lg" | "sm" }) {
  const { glyph, tone } = LOOK[label];
  return (
    <span
      className={`stamp inline-flex w-fit items-center gap-2 rounded-md border-2 font-display font-bold uppercase tracking-[0.12em] ring-1 ring-current/30 ring-offset-2 ring-offset-card ${tone} ${size === "lg" ? "px-4 py-1.5 text-xl sm:text-2xl" : "px-2.5 py-0.5 text-xs"}`}
    >
      <span aria-hidden>{glyph}</span>
      {LABEL_TEXT[label]}
    </span>
  );
}
