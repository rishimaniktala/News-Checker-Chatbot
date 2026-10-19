import type { Label } from "@/lib/types";
import { consensusText } from "@/lib/labels";

export default function Consensus({ ratio, cited, label, singleSource, conflict }: {
  ratio: number;
  cited: number;
  label: Label;
  singleSource: boolean;
  conflict: boolean;
}) {
  const agree = Math.round(ratio * cited);
  const text = consensusText(ratio, cited, label);
  return (
    <div>
      <div className="flex items-center gap-3">
        <span role="img" aria-label={text} className="flex gap-1.5">
          {Array.from({ length: cited }, (_, i) => (
            <span
              key={i}
              className={`rise h-3 w-3 rounded-full border-2 ${i < agree ? "border-ink bg-ink" : "border-rule bg-transparent"}`}
              style={{ ["--d" as string]: `${300 + i * 90}ms` }}
            />
          ))}
        </span>
        <span className="text-sm font-medium">{text}</span>
      </div>
      {singleSource && <p className="mt-1 text-xs text-muted">Only one kind of source had usable evidence.</p>}
      {conflict && <p className="mt-1 text-xs font-medium text-warn">A published fact-check disagrees with the first read; we followed the fact-check.</p>}
    </div>
  );
}
