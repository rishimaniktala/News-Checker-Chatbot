export default function ModelNote({ model, fallback }: { model?: string | null; fallback?: boolean }) {
  return (
    <>
      {model && <p className="font-mono text-xs text-muted">Judged by {model}</p>}
      {fallback && <p role="note" className="rounded-lg border border-warn px-3 py-2 text-sm text-warn"><span aria-hidden>⚠ </span>Backup model used, treat with a little more caution.</p>}
    </>
  );
}
