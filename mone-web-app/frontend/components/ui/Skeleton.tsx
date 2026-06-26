export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden="true" />;
}

export function CardSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-5 space-y-3">
      <Skeleton className="h-4 w-1/3" />
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-3 w-full" />
      ))}
    </div>
  );
}

export function TableSkeleton({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="overflow-hidden rounded-xl border border-[var(--bg-border)]">
      <div className="grid gap-px bg-[var(--bg-border)]" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
        {Array.from({ length: cols }).map((_, i) => (
          <div key={i} className="bg-[var(--bg-elevated)] px-3 py-2">
            <Skeleton className="h-3 w-3/4" />
          </div>
        ))}
        {Array.from({ length: rows * cols }).map((_, i) => (
          <div key={`r${i}`} className="bg-[var(--bg-card)] px-3 py-2.5">
            <Skeleton className="h-3 w-full" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function ChartSkeleton() {
  return (
    <div className="rounded-2xl border border-[var(--bg-border)] bg-[var(--bg-card)] p-4 space-y-2">
      <div className="flex justify-between">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-4 w-16" />
      </div>
      <Skeleton className="h-48 w-full" />
      <div className="flex gap-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-7 w-12 rounded-lg" />
        ))}
      </div>
    </div>
  );
}
