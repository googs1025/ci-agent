'use client';

import { useState } from 'react';
import FindingTable from '@/components/FindingTable';
import type { Dimension, Finding } from '@/types';

interface Tab {
  key: Dimension;
  label: string;
  count: number;
}

interface ReportTabsProps {
  dimensions: Tab[];
  byDimension: Partial<Record<Dimension, Finding[]>>;
}

const DIMENSION_ACCENT: Record<Dimension, string> = {
  efficiency: 'text-accent-blue border-accent-blue',
  security: 'text-accent-purple border-accent-purple',
  cost: 'text-accent-green border-accent-green',
  errors: 'text-accent-red border-accent-red',
};

const DIMENSION_COUNT_BG: Record<Dimension, string> = {
  efficiency: 'bg-blue-500/15 text-blue-400',
  security: 'bg-purple-500/15 text-purple-400',
  cost: 'bg-green-500/15 text-green-400',
  errors: 'bg-red-500/15 text-red-400',
};

export default function ReportTabs({ dimensions, byDimension }: ReportTabsProps) {
  const firstWithFindings = dimensions.find((d) => d.count > 0)?.key ?? dimensions[0].key;
  const [active, setActive] = useState<Dimension>(firstWithFindings);

  return (
    <div>
      {/* Tab bar */}
      <div
        role="tablist"
        aria-label="Findings by dimension"
        className="flex gap-1 overflow-x-auto border-b border-surface-border mb-6 pb-px"
      >
        {dimensions.map((dim) => {
          const isActive = active === dim.key;
          return (
            <button
              key={dim.key}
              role="tab"
              aria-selected={isActive}
              aria-controls={`panel-${dim.key}`}
              id={`tab-${dim.key}`}
              onClick={() => setActive(dim.key)}
              className={[
                'flex items-center gap-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 -mb-px transition-colors duration-150 rounded-t-lg',
                isActive
                  ? `${DIMENSION_ACCENT[dim.key]} bg-surface-elevated`
                  : 'border-transparent text-slate-400 hover:text-slate-200',
              ].join(' ')}
            >
              {dim.label}
              {dim.count > 0 && (
                <span
                  className={`text-xs px-1.5 py-0.5 rounded-full font-semibold ${
                    isActive
                      ? DIMENSION_COUNT_BG[dim.key]
                      : 'bg-surface-elevated text-slate-500'
                  }`}
                >
                  {dim.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Tab panels */}
      {dimensions.map((dim) => (
        <div
          key={dim.key}
          id={`panel-${dim.key}`}
          role="tabpanel"
          aria-labelledby={`tab-${dim.key}`}
          hidden={active !== dim.key}
        >
          <FindingTable findings={byDimension[dim.key] ?? []} />
        </div>
      ))}
    </div>
  );
}
