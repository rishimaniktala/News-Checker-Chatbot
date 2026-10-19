export default function Skeleton() {
  return (
    <section aria-busy="true" aria-label="Verdict loading" className="space-y-5 rounded-2xl border border-rule bg-card p-5 sm:p-7">
      <div className="shimmer h-3 w-24 rounded" />
      <div className="shimmer h-7 w-4/5 rounded" />
      <div className="shimmer h-10 w-48 rounded-md" />
      <div className="space-y-2">
        <div className="shimmer h-4 w-full rounded" />
        <div className="shimmer h-4 w-11/12 rounded" />
        <div className="shimmer h-4 w-2/3 rounded" />
      </div>
      {[0, 1].map((i) => (
        <div key={i} className="shimmer h-24 w-full rounded-xl" style={{ animationDelay: `${i * 150}ms` }} />
      ))}
    </section>
  );
}
