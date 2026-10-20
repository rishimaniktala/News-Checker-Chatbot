"use client";
import { useReducer, useRef } from "react";
import InputPanel from "@/components/InputPanel";
import Trace from "@/components/Trace";
import Verdict from "@/components/Verdict";
import Pipeline from "@/components/Pipeline";
import Receipt from "@/components/Receipt";
import Skeleton from "@/components/Skeleton";
import { initialState, reducer } from "@/lib/reducer";
import { streamCheck } from "@/lib/stream";
import type { CheckRequest } from "@/lib/types";

const TIMEOUT_MS = 120_000;

export default function Page() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const abort = useRef<AbortController | null>(null);

  async function run(req: CheckRequest) {
    const ctrl = new AbortController();
    abort.current = ctrl;
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; ctrl.abort(); }, TIMEOUT_MS);
    dispatch({ type: "start" });
    try {
      let finished = false;
      for await (const event of streamCheck(req, ctrl.signal)) {
        dispatch({ type: "event", event });
        if (event.type === "done") finished = true;
      }
      if (!finished) dispatch({ type: "fail", message: "The connection closed before the check finished. Please try again." });
    } catch (err) {
      if (timedOut) dispatch({ type: "fail", message: "The check took too long. Please try again." });
      else if (!ctrl.signal.aborted && err instanceof Error && err.message.startsWith("Too many")) dispatch({ type: "fail", message: err.message });
      else if (!ctrl.signal.aborted) dispatch({ type: "fail", message: "Could not reach the server. Check your connection and try again." });
    } finally {
      clearTimeout(timer);
    }
  }

  function cancel() {
    abort.current?.abort();
    dispatch({ type: "cancel" });
  }

  const running = state.status === "running";
  return (
    <main className="mx-auto max-w-6xl px-4 pb-16 pt-8 sm:px-6 sm:pt-12">
      <header className="rise mb-7 sm:mb-9">
        <p className="font-mono text-xs uppercase tracking-[0.22em] text-accent">Claims in · receipts out</p>
        <h1 className="mt-1 font-display text-4xl font-bold leading-none tracking-tight sm:text-6xl">News Checker</h1>
        <p className="mt-3 max-w-xl text-base text-muted sm:text-lg">
          Paste a claim, a link or a screenshot. We check it against The Guardian and published fact-checks, and show our working.
        </p>
      </header>

      <InputPanel running={running} onSubmit={run} onCancel={cancel} />

      {state.status !== "idle" || state.trace.length > 0 ? (
        <div className="mt-8 space-y-6">
          <Pipeline trace={state.trace} status={state.status} />
          <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_21rem]">
            <div className="space-y-4">
              {state.status === "error" && (
                <section role="alert" className="rise rounded-2xl border-2 border-accent bg-card p-5">
                  <h2 className="font-display text-xl font-bold text-accent">That didn&apos;t work</h2>
                  <p className="mt-1 text-base">{state.error}</p>
                </section>
              )}
              {state.report && <Verdict report={state.report} />}
              {!state.report && running && <Skeleton />}
              {state.done && <Receipt done={state.done} models={state.report?.models_used} promptVersion={state.report?.prompt_version} />}
            </div>
            <div className="lg:sticky lg:top-6">
              <Trace lines={state.trace} running={running} />
            </div>
          </div>
        </div>
      ) : (
        <p className="rise mt-10 text-center font-display text-lg italic text-muted" style={{ ["--d" as string]: "200ms" }}>
          Nothing checked yet. Try one of the examples above.
        </p>
      )}
    </main>
  );
}
