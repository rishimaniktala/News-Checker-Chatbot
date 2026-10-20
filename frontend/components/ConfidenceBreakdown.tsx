"use client";
import { useId, useState } from "react";
import { factorRows, factorStrength } from "@/lib/report";

export default function ConfidenceBreakdown({ factors }: { factors?: Record<string, number> }) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  const rows = factorRows(factors);
  if (rows.length === 0) return null;
  return (
    <div>
      <button type="button" aria-expanded={open} aria-controls={panel} onClick={() => setOpen(!open)} className="text-sm text-muted underline decoration-rule underline-offset-4 hover:text-ink hover:decoration-accent">
        {open ? "Hide" : "Why this confidence?"}
      </button>
      {open && (
        <ul id={panel} className="mt-2 max-w-md space-y-2">
          {rows.map((r) => (
            <li key={r.key} className="text-sm">
              <div className="flex justify-between gap-3"><span>{r.name}</span><span className="font-mono text-muted">{Math.round(r.value * 100)}% · {factorStrength(r.value)}</span></div>
              <div role="meter" aria-label={r.name} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(r.value * 100)} className="mt-1 h-1.5 rounded-full bg-rule">
                <div className="h-full rounded-full bg-ink" style={{ width: `${r.value * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
