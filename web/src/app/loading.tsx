function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={`bg-surface-elevated rounded-lg animate-pulse ${className ?? ''}`}
      aria-hidden="true"
    />
  );
}

export default function DashboardLoading() {
  return (
    <div className="space-y-8">
      {/* Heading */}
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <Skeleton className="h-8 w-36" />
          <Skeleton className="h-4 w-52" />
        </div>
        <Skeleton className="h-10 w-36" />
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="card flex items-start gap-4">
            <Skeleton className="w-12 h-12 rounded-xl" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-8 w-16" />
            </div>
          </div>
        ))}
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {[...Array(2)].map((_, i) => (
          <div key={i} className="card space-y-4">
            <Skeleton className="h-5 w-44" />
            {[...Array(4)].map((_, j) => (
              <div key={j} className="flex items-center gap-3">
                <Skeleton className="w-20 h-4" />
                <Skeleton className="flex-1 h-3 rounded-full" />
                <Skeleton className="w-8 h-4" />
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
