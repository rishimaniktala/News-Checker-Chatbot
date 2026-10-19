"use client";
import { useReducer, useRef } from "react";
import InputPanel from "@/components/InputPanel";
import Trace from "@/components/Trace";
import Verdict from "@/components/Verdict";
import Details from "@/components/Details";
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
    } catch {
      if (timedOut) dispatch({ type: "fail", message: "The check took too long. Please try again." });
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
    <main className="mx-auto max-w-6xl space-y-4 p-4">
      <h1 className="text-2xl font-bold">News Checker</h1>
      <InputPanel running={running} onSubmit={run} onCancel={cancel} />
      <div className="grid gap-4 md:grid-cols-2">
        <Trace lines={state.trace} />
        <div className="space-y-4">
          {state.status === "error" && (
            <section role="alert" className="rounded-lg border border-red-800 bg-red-50 p-4 text-red-900">
              <h2 className="text-base font-semibold">Something went wrong</h2>
              <p className="mt-1 text-sm">{state.error}</p>
            </section>
          )}
          {state.report && <Verdict report={state.report} />}
          {!state.report && state.status !== "error" && (
            <section className="rounded-lg border border-slate-300 bg-white p-4 text-sm text-slate-600">
              {running ? "Working on it..." : "The verdict appears here."}
            </section>
          )}
          {state.done && <Details done={state.done} />}
        </div>
      </div>
    </main>
  );
}
