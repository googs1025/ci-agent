import type { Severity } from '@/types';

interface SeverityBadgeProps {
  severity: Severity;
  /** Show as a dot-only indicator instead of full badge */
  dotOnly?: boolean;
}

const CONFIG: Record<
  Severity,
  { label: string; dotClass: string; badgeClass: string }
> = {
  critical: {
    label: 'Critical',
    dotClass: 'bg-red-500',
    badgeClass: 'bg-red-500/15 text-red-400 ring-1 ring-red-500/30',
  },
  major: {
    label: 'Major',
    dotClass: 'bg-orange-400',
    badgeClass: 'bg-orange-400/15 text-orange-400 ring-1 ring-orange-400/30',
  },
  minor: {
    label: 'Minor',
    dotClass: 'bg-yellow-400',
    badgeClass: 'bg-yellow-400/15 text-yellow-400 ring-1 ring-yellow-400/30',
  },
  info: {
    label: 'Info',
    dotClass: 'bg-blue-400',
    badgeClass: 'bg-blue-400/15 text-blue-400 ring-1 ring-blue-400/30',
  },
};

export default function SeverityBadge({
  severity,
  dotOnly = false,
}: SeverityBadgeProps) {
  const cfg = CONFIG[severity] ?? CONFIG.info;

  if (dotOnly) {
    return (
      <span
        className={`inline-block w-2.5 h-2.5 rounded-full shrink-0 ${cfg.dotClass}`}
        title={cfg.label}
        aria-label={cfg.label}
      />
    );
  }

  return (
    <span className={`badge ${cfg.badgeClass}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dotClass}`} aria-hidden="true" />
      {cfg.label}
    </span>
  );
}
