import type { ReactNode } from 'react';

interface StatCardProps {
  label: string;
  value: number | string;
  icon: ReactNode;
  /** Tailwind text color class, e.g. "text-accent-blue" */
  color?: string;
  /** Optional small sub-label below the value */
  subLabel?: string;
}

export default function StatCard({
  label,
  value,
  icon,
  color = 'text-accent-blue',
  subLabel,
}: StatCardProps) {
  return (
    <div className="card flex items-start gap-4">
      {/* Icon container */}
      <div
        className={[
          'shrink-0 flex items-center justify-center w-12 h-12 rounded-xl bg-surface-elevated',
          color,
        ].join(' ')}
        aria-hidden="true"
      >
        {icon}
      </div>

      {/* Text */}
      <div className="min-w-0">
        <p className="text-sm font-medium text-slate-400 truncate">{label}</p>
        <p className={['text-3xl font-bold tracking-tight mt-0.5', color].join(' ')}>
          {typeof value === 'number' ? value.toLocaleString() : value}
        </p>
        {subLabel && (
          <p className="text-xs text-slate-500 mt-1">{subLabel}</p>
        )}
      </div>
    </div>
  );
}
