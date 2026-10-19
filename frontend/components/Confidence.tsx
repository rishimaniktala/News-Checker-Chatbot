import { confidenceLabel } from "@/lib/labels";

export default function Confidence({ value }: { value: number }) {
  const level = confidenceLabel(value);
  const lit = { High: 3, Medium: 2, Low: 1 }[level];
  return (
    <span className="inline-flex items-center gap-2 text-sm text-muted">
      <span aria-hidden className="flex gap-1">
        {[1, 2, 3].map((n) => (
          <span key={n} className={`h-1.5 w-5 rounded-full transition-colors duration-500 ${n <= lit ? "bg-ink" : "bg-rule"}`} />
        ))}
      </span>
      Confidence: <span className="font-medium text-ink">{level}</span>
    </span>
  );
}
