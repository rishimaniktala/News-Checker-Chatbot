"use client";
import { useRef, useState } from "react";
import type { CheckRequest } from "@/lib/types";
import { fileToBase64, imageProblem } from "@/lib/image";

export const EXAMPLES = [
  { name: "True claim", text: "Sweden joined NATO in 2024." },
  { name: "False claim", text: "Anthropic has shut down." },
  { name: "Odd claim", text: "A man in Ohio says he invented a fourth primary colour." },
  { name: "Swedish claim", text: "Sverige gick med i Nato 2024." },
];

const field = "w-full rounded-md border border-slate-400 bg-white px-3 py-2 text-sm";

export default function InputPanel({
  running,
  onSubmit,
  onCancel,
}: {
  running: boolean;
  onSubmit: (r: CheckRequest) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [image, setImage] = useState<File | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function pick(file: File | undefined) {
    if (!file) return;
    const p = imageProblem(file);
    setProblem(p);
    setImage(p ? null : file);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (image) {
      onSubmit({ kind: "image", image_b64: await fileToBase64(image), mime: image.type });
    } else if (url.trim()) {
      onSubmit({ kind: "url", url: url.trim() });
    } else if (text.trim()) {
      onSubmit({ kind: "text", text: text.trim() });
    } else {
      setProblem("Enter a claim, a link or a screenshot.");
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded-lg border border-slate-300 bg-white p-4">
      <div>
        <p className="mb-2 text-sm font-medium">Try an example</p>
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex.name}
              type="button"
              disabled={running}
              onClick={() => {
                setText(ex.text);
                setUrl("");
                setImage(null);
                setProblem(null);
              }}
              className="rounded-full border border-slate-400 px-3 py-1 text-sm hover:bg-slate-100 disabled:opacity-50"
            >
              {ex.name}
            </button>
          ))}
        </div>
      </div>
      <div>
        <label htmlFor="claim-text" className="mb-1 block text-sm font-medium">Claim or article text</label>
        <textarea id="claim-text" rows={4} value={text} onChange={(e) => setText(e.target.value)} className={field} />
      </div>
      <div>
        <label htmlFor="claim-url" className="mb-1 block text-sm font-medium">Or an article link</label>
        <input id="claim-url" type="url" placeholder="https://" value={url} onChange={(e) => setUrl(e.target.value)} className={field} />
      </div>
      <div>
        <label htmlFor="claim-image" className="mb-1 block text-sm font-medium">Or a screenshot (PNG or JPG, up to 5 MB)</label>
        <div
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files[0]); }}
          className={`rounded-md border-2 border-dashed p-3 text-sm ${over ? "border-blue-600 bg-blue-50" : "border-slate-400"}`}
        >
          <p className="mb-2">Drop an image here, or choose a file.</p>
          <input
            id="claim-image"
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg"
            onChange={(e) => pick(e.target.files?.[0])}
          />
          {image && (
            <p className="mt-2">
              {image.name}{" "}
              <button
                type="button"
                className="underline"
                onClick={() => { setImage(null); if (fileRef.current) fileRef.current.value = ""; }}
              >
                Remove
              </button>
            </p>
          )}
        </div>
      </div>
      {problem && <p role="alert" className="text-sm font-medium text-red-800">{problem}</p>}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={running}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {running ? "Checking..." : "Check"}
        </button>
        {running && (
          <button type="button" onClick={onCancel} className="rounded-md border border-slate-400 px-4 py-2 text-sm">
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
