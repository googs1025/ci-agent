function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={`bg-surface-elevated rounded-lg animate-pulse ${className ?? ''}`}
      aria-hidden="true"
    />
  );
}

export default function ReportDetailLoading() {
  return (
    <div className="space-y-8">
      {/* Back link skeleton */}
      <Skeleton className="h-5 w-24" />

      {/* Header card */}
      <div className="card space-y-3">
        <div className="flex items-center gap-3">
          <Skeleton className="h-7 w-56" />
          <Skeleton className="h-5 w-20" />
        </div>
        <Skeleton className="h-4 w-48" />
      </div>

      {/* Summary */}
      <div className="card space-y-3">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
        <Skeleton className="h-4 w-4/6" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
      </div>

      {/* Findings table placeholder */}
      <div>
        <Skeleton className="h-5 w-48 mb-4" />
        <div className="card p-0 overflow-hidden space-y-px">
          {[...Array(5)].map((_, i) => (
            <div
              key={i}
              className="flex items-center gap-4 px-6 py-4 border-b border-surface-border last:border-0"
            >
              <Skeleton className="h-5 w-16" />
              <Skeleton className="h-4 flex-1" />
              <Skeleton className="h-4 w-32 hidden md:block" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
