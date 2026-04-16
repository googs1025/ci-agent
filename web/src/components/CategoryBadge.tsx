import type { DiagnoseCategory } from '@/types';
import { useLocale } from '@/lib/locale';

/**
 * Color-coded pill for the 9 failure-triage categories.
 * Colors are chosen so severity-like categories (resource_limit, infra)
 * lean red while recoverable ones (flaky, network) lean yellow/blue.
 */
const CONFIG: Record<
  DiagnoseCategory,
  { badgeClass: string; dotClass: string }
> = {
  flaky_test: {
    badgeClass: 'bg-yellow-400/15 text-yellow-400 ring-1 ring-yellow-400/30',
    dotClass: 'bg-yellow-400',
  },
  timeout: {
    badgeClass: 'bg-orange-400/15 text-orange-400 ring-1 ring-orange-400/30',
    dotClass: 'bg-orange-400',
  },
  dependency: {
    badgeClass: 'bg-purple-400/15 text-purple-400 ring-1 ring-purple-400/30',
    dotClass: 'bg-purple-400',
  },
  network: {
    badgeClass: 'bg-blue-400/15 text-blue-400 ring-1 ring-blue-400/30',
    dotClass: 'bg-blue-400',
  },
  resource_limit: {
    badgeClass: 'bg-red-500/15 text-red-400 ring-1 ring-red-500/30',
    dotClass: 'bg-red-500',
  },
  config: {
    badgeClass: 'bg-cyan-400/15 text-cyan-400 ring-1 ring-cyan-400/30',
    dotClass: 'bg-cyan-400',
  },
  build: {
    badgeClass: 'bg-pink-400/15 text-pink-400 ring-1 ring-pink-400/30',
    dotClass: 'bg-pink-400',
  },
  infra: {
    badgeClass: 'bg-red-500/15 text-red-400 ring-1 ring-red-500/30',
    dotClass: 'bg-red-500',
  },
  unknown: {
    badgeClass: 'bg-slate-500/15 text-slate-400 ring-1 ring-slate-500/30',
    dotClass: 'bg-slate-500',
  },
};

interface CategoryBadgeProps {
  category: DiagnoseCategory;
  size?: 'sm' | 'md';
}

export default function CategoryBadge({ category, size = 'md' }: CategoryBadgeProps) {
  const { t } = useLocale();
  const cfg = CONFIG[category] ?? CONFIG.unknown;
  const label = t(`diag.cat.${category}`);
  const padding = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-sm';

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium ${padding} ${cfg.badgeClass}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dotClass}`} aria-hidden="true" />
      {label}
    </span>
  );
}
