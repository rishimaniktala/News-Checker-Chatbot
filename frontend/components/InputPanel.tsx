"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import type { CheckRequest } from "@/lib/types";
import { fileToBase64, imageProblem } from "@/lib/image";

export const EXAMPLES = [
  { name: "True claim", text: "Sweden joined NATO in 2024." },
  { name: "False claim", text: "The Great Wall of China is visible from the Moon with the naked eye." },
  { name: "Odd claim", text: "A man in Ohio says he invented a fourth primary colour." },
  { name: "Swedish claim", text: "Sverige gick med i Nato 2024." },
];

const TABS = [
  { id: "text", label: "Claim" },
  { id: "url", label: "Link" },
  { id: "image", label: "Screenshot" },
] as const;
type Tab = (typeof TABS)[number]["id"];

const field =
  "w-full rounded-xl border border-rule bg-paper/60 px-4 py-3 text-base text-ink placeholder:text-muted/70 transition focus:border-accent focus:bg-card focus:outline-none focus:ring-4 focus:ring-accent/15";

export default function InputPanel({
  running,
  onSubmit,
  onCancel,
}: {
  running: boolean;
  onSubmit: (r: CheckRequest) => void;
  onCancel: () => void;
}) {
  const [tab, setTab] = useState<Tab>("text");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [image, setImage] = useState<File | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const preview = useMemo(() => (image ? URL.createObjectURL(image) : null), [image]);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  function pick(file: File | undefined) {
    if (!file) return;
    const p = imageProblem(file);
    setProblem(p);
    setImage(p ? null : file);
  }

  async function submit(e?: React.FormEvent) {
    e?.preventDefault();
    if (running) return;
    if (tab === "image" && image) onSubmit({ kind: "image", image_b64: await fileToBase64(image), mime: image.type });
    else if (tab === "url" && url.trim()) onSubmit({ kind: "url", url: url.trim() });
    else if (tab === "text" && text.trim()) onSubmit({ kind: "text", text: text.trim() });
    else setProblem(tab === "text" ? "Type or paste a claim first." : tab === "url" ? "Paste an article link first." : "Choose a screenshot first.");
  }

  function onTabKey(e: React.KeyboardEvent, i: number) {
    const next = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : null;
    if (next === null) return;
    e.preventDefault();
    const t = TABS[(next + TABS.length) % TABS.length].id;
    setTab(t);
    setProblem(null);
    document.getElementById(`tab-${t}`)?.focus();
  }

  return (
    <form onSubmit={submit} className="rise rounded-2xl border border-rule bg-card p-4 shadow-[0_1px_0_var(--rule),0_18px_40px_-28px_rgba(0,0,0,0.35)] sm:p-6">
      <div role="tablist" aria-label="Input type" className="mb-4 inline-flex rounded-full border border-rule bg-paper/60 p-1">
        {TABS.map((t, i) => (
          <button
            key={t.id}
            id={`tab-${t.id}`}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            onKeyDown={(e) => onTabKey(e, i)}
            onClick={() => { setTab(t.id); setProblem(null); }}
            className={`rounded-full px-4 py-1.5 text-sm font-medium transition ${tab === t.id ? "bg-ink text-paper" : "text-muted hover:text-ink"}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "text" && (
          <>
            <label htmlFor="claim-text" className="sr-only">Claim or article text</label>
            <textarea
              id="claim-text"
              rows={4}
              value={text}
              placeholder="Paste a claim or a paragraph of news…"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(); }}
              className={`${field} resize-y font-display text-lg leading-snug`}
            />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="text-xs uppercase tracking-wider text-muted">Try</span>
              {EXAMPLES.map((ex) => (
                <button
                  key={ex.name}
                  type="button"
                  disabled={running}
                  onClick={() => { setText(ex.text); setProblem(null); }}
                  className="rounded-full border border-rule px-3 py-1 text-sm text-ink transition hover:-translate-y-0.5 hover:border-accent hover:text-accent disabled:opacity-50"
                >
                  {ex.name}
                </button>
              ))}
            </div>
          </>
        )}
        {tab === "url" && (
          <>
            <label htmlFor="claim-url" className="sr-only">Article link</label>
            <input id="claim-url" type="url" inputMode="url" placeholder="https://www.theguardian.com/…" value={url} onChange={(e) => setUrl(e.target.value)} className={field} />
            <p className="mt-2 text-sm text-muted">We read the page and check its main claims. Only the link you paste is fetched.</p>
          </>
        )}
        {tab === "image" && (
          <div
            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files[0]); }}
            className={`flex min-h-40 items-center justify-center rounded-xl border-2 border-dashed p-4 text-center transition ${over ? "border-accent bg-accent/10" : "border-rule bg-paper/50"}`}
          >
            {preview ? (
              <div className="flex flex-col items-center gap-3">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={preview} alt="Chosen screenshot" className="max-h-40 rounded-lg border border-rule" />
                <button type="button" onClick={() => { setImage(null); if (fileRef.current) fileRef.current.value = ""; }} className="text-sm text-muted underline hover:text-ink">
                  Remove {image?.name}
                </button>
              </div>
            ) : (
              <div>
                <p className="font-display text-lg">Drop a screenshot here</p>
                <p className="mb-3 text-sm text-muted">PNG or JPG, up to 5 MB</p>
                <label htmlFor="claim-image" className="cursor-pointer rounded-full border border-rule px-4 py-1.5 text-sm hover:border-accent hover:text-accent">
                  Choose a file
                </label>
              </div>
            )}
            <input id="claim-image" ref={fileRef} type="file" accept="image/png,image/jpeg" className="sr-only" onChange={(e) => pick(e.target.files?.[0])} />
          </div>
        )}
      </div>

      {problem && <p role="alert" className="mt-3 text-sm font-medium text-accent">{problem}</p>}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={running}
          className="group inline-flex items-center gap-2 rounded-full bg-ink px-6 py-2.5 text-sm font-semibold text-paper transition hover:bg-accent hover:text-white disabled:opacity-60"
        >
          {running ? (<><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent motion-reduce:animate-none" aria-hidden /> Checking</>) : (<>Check it <span aria-hidden className="transition group-hover:translate-x-0.5">→</span></>)}
        </button>
        {running && (
          <button type="button" onClick={onCancel} className="rounded-full border border-rule px-4 py-2 text-sm text-muted hover:border-ink hover:text-ink">
            Cancel
          </button>
        )}
        {tab === "text" && !running && <span className="hidden text-xs text-muted sm:inline">or press ⌘/Ctrl + Enter</span>}
      </div>
    </form>
  );
}
