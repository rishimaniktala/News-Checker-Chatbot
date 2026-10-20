export default function SourcesBadge({ count }: { count?: number | null }) {
  if (count == null) return null;
  return <span className="rounded-full border border-rule px-3 py-0.5 font-mono text-xs text-muted">{count} independent {count === 1 ? "outlet" : "outlets"}</span>;
}
