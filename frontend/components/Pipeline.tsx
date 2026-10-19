import { STAGES, stageStates } from "@/lib/pipeline";
import type { TraceLine } from "@/lib/reducer";

type Status = "idle" | "running" | "done" | "error";

export default function Pipeline({ trace, status }: { trace: TraceLine[]; status: Status }) {
  const states = stageStates(trace, status);
  return (
    <ol aria-label="Progress" className="flex items-start">
      {STAGES.map((s, i) => {
        const st = states[i];
        return (
          <li key={s.id} aria-current={st === "active" ? "step" : undefined} className="relative flex flex-1 flex-col items-center text-center">
            {i > 0 && (
              <span aria-hidden className={`absolute right-1/2 top-[0.6rem] h-0.5 w-full transition-colors duration-500 ${states[i - 1] === "done" ? "bg-ink" : "bg-rule"}`} />
            )}
            <span
              aria-hidden
              className={`relative z-10 grid h-[1.35rem] w-[1.35rem] place-items-center rounded-full border-2 text-[0.65rem] font-bold transition-all duration-300
                ${st === "done" ? "border-ink bg-ink text-paper" : st === "active" ? "pulse-ring border-accent bg-accent text-white" : st === "failed" ? "border-accent bg-card text-accent" : "border-rule bg-card text-transparent"}`}
            >
              {st === "done" ? "✓" : st === "failed" ? "✗" : ""}
            </span>
            <span className={`mt-1.5 text-[0.7rem] leading-tight sm:text-xs ${st === "pending" ? "text-muted/70" : "font-medium text-ink"} ${st === "active" ? "" : "hidden sm:block"}`}>
              {s.label}
              <span className="sr-only">: {st}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
