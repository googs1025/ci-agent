'use client';

import { useState, useMemo } from 'react';
import FindingTable from '@/components/FindingTable';
import SummaryMarkdown from '@/components/SummaryMarkdown';
import type { Dimension, Finding, Severity } from '@/types';

interface Tab {
  key: Dimension;
  label: string;
  count: number;
}

interface ReportTabsProps {
  dimensions: Tab[];
  byDimension: Partial<Record<Dimension, Finding[]>>;
  summaryMd?: string | null;
  sevCounts: Partial<Record<Severity, number>>;
}

const DIMENSION_ACCENT: Record<string, { dot: string; active: string; nav: string }> = {
  efficiency: {
    dot: 'bg-accent-blue',
    active: 'text-accent-blue border-accent-blue bg-blue-500/5',
    nav: 'text-blue-400',
  },
  security: {
    dot: 'bg-accent-purple',
    active: 'text-accent-purple border-accent-purple bg-purple-500/5',
    nav: 'text-purple-400',
  },
  cost: {
    dot: 'bg-accent-green',
    active: 'text-accent-green border-accent-green bg-green-500/5',
    nav: 'text-green-400',
  },
  errors: {
    dot: 'bg-accent-red',
    active: 'text-accent-red border-accent-red bg-red-500/5',
    nav: 'text-red-400',
  },
};

const DEFAULT_ACCENT = {
  dot: 'bg-slate-400',
  active: 'text-slate-200 border-slate-400 bg-slate-500/5',
  nav: 'text-slate-300',
};

const SEVERITY_CONFIG: Record<Severity, { label: string; dot: string; chip: string; active: string }> = {
  critical: { label: 'Critical', dot: 'bg-red-500',    chip: 'border-red-500/30 text-red-400 hover:bg-red-500/10',    active: 'bg-red-500/15 border-red-500/50 text-red-300' },
  major:    { label: 'Major',    dot: 'bg-orange-400', chip: 'border-orange-500/30 text-orange-400 hover:bg-orange-500/10', active: 'bg-orange-500/15 border-orange-500/50 text-orange-300' },
  minor:    { label: 'Minor',    dot: 'bg-yellow-400', chip: 'border-yellow-500/30 text-yellow-400 hover:bg-yellow-500/10', active: 'bg-yellow-500/15 border-yellow-500/50 text-yellow-300' },
  info:     { label: 'Info',     dot: 'bg-blue-400',   chip: 'border-blue-500/30 text-blue-400 hover:bg-blue-500/10',   active: 'bg-blue-500/15 border-blue-500/50 text-blue-300' },
};

export default function ReportTabs({ dimensions, byDimension, summaryMd, sevCounts }: ReportTabsProps) {
  const firstWithFindings = dimensions.find((d) => d.count > 0)?.key ?? dimensions[0]?.key;
  const [active, setActive] = useState<Dimension>(firstWithFindings ?? '');
  const [severityFilter, setSeverityFilter] = useState<Severity | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  const allFindings = useMemo(
    () => Object.values(byDimension).flat() as Finding[],
    [byDimension],
  );

  const filteredFindings = useMemo(() => {
    let base = byDimension[active] ?? [];
    if (severityFilter) base = base.filter((f) => f.severity === severityFilter);
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      base = base.filter(
        (f) =>
          f.title.toLowerCase().includes(q) ||
          (f.description ?? '').toLowerCase().includes(q) ||
          (f.file_path ?? '').toLowerCase().includes(q),
      );
    }
    return base;
  }, [byDimension, active, severityFilter, searchQuery]);

  // Count for each dimension + current filters
  function filteredCount(dim: Dimension): number {
    let base = byDimension[dim] ?? [];
    if (severityFilter) base = base.filter((f) => f.severity === severityFilter);
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      base = base.filter(
        (f) =>
          f.title.toLowerCase().includes(q) ||
          (f.description ?? '').toLowerCase().includes(q) ||
          (f.file_path ?? '').toLowerCase().includes(q),
      );
    }
    return base.length;
  }

  const totalFindings = allFindings.length;

  if (!firstWithFindings) return null;

  return (
    <div className="lg:grid lg:grid-cols-[220px_1fr] lg:gap-6 lg:items-start space-y-6 lg:space-y-0">
      {/* ── Sidebar ────────────────────────────────────── */}
      <aside className="lg:sticky lg:top-20 space-y-5">
        {/* Severity filter */}
        <div className="card p-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
            Filter by Severity
          </p>
          <div className="space-y-1.5">
            {(['critical', 'major', 'minor', 'info'] as Severity[]).map((sev) => {
              const cfg = SEVERITY_CONFIG[sev];
              const count = sevCounts[sev] ?? 0;
              if (count === 0) return null;
              const isActive = severityFilter === sev;
              return (
                <button
                  key={sev}
                  type="button"
                  onClick={() => setSeverityFilter(isActive ? null : sev)}
                  className={[
                    'w-full flex items-center justify-between px-3 py-1.5 rounded-lg text-sm border transition-colors',
                    isActive ? cfg.active : `border-transparent ${cfg.chip}`,
                  ].join(' ')}
                >
                  <span className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${cfg.dot}`} />
                    {cfg.label}
                  </span>
                  <span className="font-mono text-xs font-semibold">{count}</span>
                </button>
              );
            })}
            {severityFilter && (
              <button
                type="button"
                onClick={() => setSeverityFilter(null)}
                className="w-full text-xs text-slate-500 hover:text-slate-300 transition-colors pt-1"
              >
                Clear filter
              </button>
            )}
          </div>
        </div>

        {/* Dimension navigation */}
        <div className="card p-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
            Dimensions
          </p>
          <nav className="space-y-0.5" aria-label="Findings by dimension">
            {dimensions.map((dim) => {
              const cfg = DIMENSION_ACCENT[dim.key] ?? DEFAULT_ACCENT;
              const isActive = active === dim.key;
              const count = filteredCount(dim.key);
              return (
                <button
                  key={dim.key}
                  type="button"
                  onClick={() => setActive(dim.key)}
                  className={[
                    'w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm border transition-colors text-left',
                    isActive
                      ? cfg.active
                      : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-surface-elevated',
                  ].join(' ')}
                  aria-current={isActive ? 'page' : undefined}
                >
                  <span className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${cfg.dot}`} />
                    {dim.label}
                  </span>
                  {count > 0 && (
                    <span className={`text-xs font-mono font-semibold ${isActive ? '' : 'text-slate-500'}`}>
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Total count */}
        {totalFindings > 0 && (
          <p className="text-xs text-slate-600 text-center">
            {totalFindings} finding{totalFindings !== 1 ? 's' : ''} total
          </p>
        )}
      </aside>

      {/* ── Main content ───────────────────────────────── */}
      <div className="space-y-6 min-w-0">
        {/* Executive Summary */}
        {summaryMd && (
          <div className="card">
            <h2 className="font-semibold text-slate-200 mb-4">Executive Summary</h2>
            <SummaryMarkdown source={summaryMd} />
          </div>
        )}

        {/* Search bar + active dimension heading */}
        <div className="flex items-center gap-3">
          <div className="relative flex-1">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" aria-hidden="true">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
                <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="2" />
                <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </span>
            <input
              type="search"
              placeholder="Search findings…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="input pl-9 py-2 text-sm"
              aria-label="Search findings"
            />
          </div>
          {(severityFilter || searchQuery) && (
            <button
              type="button"
              onClick={() => { setSeverityFilter(null); setSearchQuery(''); }}
              className="text-xs text-slate-500 hover:text-slate-300 whitespace-nowrap transition-colors"
            >
              Clear all
            </button>
          )}
        </div>

        {/* Mobile dimension tabs (hidden on lg) */}
        <div
          role="tablist"
          aria-label="Findings by dimension"
          className="lg:hidden flex gap-1 overflow-x-auto border-b border-surface-border pb-px"
        >
          {dimensions.map((dim) => {
            const cfg = DIMENSION_ACCENT[dim.key] ?? DEFAULT_ACCENT;
            const isActive = active === dim.key;
            const count = filteredCount(dim.key);
            return (
              <button
                key={dim.key}
                role="tab"
                aria-selected={isActive}
                onClick={() => setActive(dim.key)}
                className={[
                  'flex items-center gap-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 -mb-px transition-colors rounded-t-lg',
                  isActive
                    ? cfg.active + ' border-current'
                    : 'border-transparent text-slate-400 hover:text-slate-200',
                ].join(' ')}
              >
                {dim.label}
                {count > 0 && (
                  <span className="text-xs px-1.5 py-0.5 rounded-full font-semibold bg-surface-elevated text-slate-400">
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Findings */}
        <div>
          <FindingTable findings={filteredFindings} />
          {filteredFindings.length === 0 && (byDimension[active] ?? []).length > 0 && (
            <p className="text-center text-sm text-slate-500 py-8">
              No findings match the current filters.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}