'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { getTrends } from '@/lib/api';
import { useLocale, interpolate } from '@/lib/locale';
import type { TrendsData } from '@/types';

const RANGE_OPTIONS = [
  { label: '7d', value: 7 },
  { label: '30d', value: 30 },
  { label: '90d', value: 90 },
] as const;

const SEVERITY_COLORS = {
  critical: '#ef4444',
  major: '#fb923c',
  minor: '#facc15',
  info: '#60a5fa',
};

const DIMENSION_COLORS = {
  efficiency: '#3b82f6',
  security: '#a855f7',
  cost: '#22c55e',
  errors: '#ef4444',
};

/** Map dimension key to its translated name via locale */
const DIM_KEYS: Record<string, string> = {
  efficiency: 'dim.efficiency',
  security: 'dim.security',
  cost: 'dim.cost',
  errors: 'dim.errors',
};

/** Derive human-readable insight bullets from the trend data. */
function generateInsights(
  data: TrendsData,
  days: number,
  t: (k: string) => string,
): string[] {
  const insights: string[] = [];
  const scores = data.daily_scores;
  const dims = data.dimension_trends;
  const repos = data.repo_comparison;

  // ── Overall trend direction ──
  if (scores.length >= 2) {
    const first = scores[0];
    const last = scores[scores.length - 1];
    const diff = last.total - first.total;
    if (diff > 0) {
      insights.push(
        interpolate(t('insight.increased'), { from: first.total, to: last.total, days }),
      );
    } else if (diff < 0) {
      insights.push(
        interpolate(t('insight.decreased'), { from: first.total, to: last.total, days }),
      );
    } else {
      insights.push(
        interpolate(t('insight.stable'), { count: last.total, days }),
      );
    }
  }

  // ── Critical highlight ──
  const totalCritical = scores.reduce((sum, d) => sum + d.critical, 0);
  if (totalCritical > 0) {
    insights.push(interpolate(t('insight.critical_found'), { count: totalCritical }));
  } else if (scores.length > 0) {
    insights.push(t('insight.no_critical'));
  }

  // ── Dominant dimension ──
  if (dims.length > 0) {
    const totals = { efficiency: 0, security: 0, cost: 0, errors: 0 };
    for (const d of dims) {
      totals.efficiency += d.efficiency;
      totals.security += d.security;
      totals.cost += d.cost;
      totals.errors += d.errors;
    }
    const sorted = Object.entries(totals).sort((a, b) => b[1] - a[1]);
    if (sorted[0][1] > 0) {
      const [topDim, topCount] = sorted[0];
      const total = sorted.reduce((s, [, v]) => s + v, 0);
      const pct = Math.round((topCount / total) * 100);
      const dimLabel = t(DIM_KEYS[topDim] ?? topDim);
      const capitalised = dimLabel.charAt(0).toUpperCase() + dimLabel.slice(1);
      insights.push(interpolate(t('insight.top_dimension'), { dim: capitalised, pct }));
    }
  }

  // ── Worst repo ──
  if (repos.length > 0) {
    const worst = repos[0];
    insights.push(
      interpolate(t('insight.worst_repo'), { repo: worst.repo, count: worst.total }),
    );
  }

  return insights;
}

const INSIGHT_ICONS = [
  <svg key="trend" width="16" height="16" viewBox="0 0 24 24" fill="none" className="shrink-0 mt-0.5"><path d="M3 17l6-6 4 4 8-8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/><path d="M17 7h4v4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  <svg key="alert" width="16" height="16" viewBox="0 0 24 24" fill="none" className="shrink-0 mt-0.5"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2"/><path d="M12 8v4M12 16h.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>,
  <svg key="chart" width="16" height="16" viewBox="0 0 24 24" fill="none" className="shrink-0 mt-0.5"><rect x="3" y="12" width="4" height="9" rx="1" fill="currentColor" opacity=".6"/><rect x="10" y="6" width="4" height="15" rx="1" fill="currentColor" opacity=".8"/><rect x="17" y="3" width="4" height="18" rx="1" fill="currentColor"/></svg>,
  <svg key="repo" width="16" height="16" viewBox="0 0 24 24" fill="none" className="shrink-0 mt-0.5"><path d="M4 19.5A2.5 2.5 0 016.5 17H20" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>,
];

function InsightSummary({ data, days }: { data: TrendsData; days: number }) {
  const { t } = useLocale();
  const insights = generateInsights(data, days, t);
  if (insights.length === 0) return null;

  return (
    <div className="card border border-accent-blue/20 bg-accent-blue/5">
      <h3 className="font-semibold text-slate-200 mb-3 flex items-center gap-2">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <path d="M12 2L2 7l10 5 10-5-10-5z" stroke="#60a5fa" strokeWidth="2" strokeLinejoin="round"/>
          <path d="M2 17l10 5 10-5" stroke="#60a5fa" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          <path d="M2 12l10 5 10-5" stroke="#60a5fa" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        {t('trend.insights')}
      </h3>
      <ul className="space-y-2">
        {insights.map((text, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-slate-300">
            <span className="text-accent-blue">
              {INSIGHT_ICONS[i % INSIGHT_ICONS.length]}
            </span>
            {text}
          </li>
        ))}
      </ul>
    </div>
  );
}

function EmptyState() {
  const { t } = useLocale();
  return (
    <div className="flex flex-col items-center justify-center py-12 text-slate-500">
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M3 12h4l3-8 4 16 3-8h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <p className="mt-3 text-sm">{t('trend.empty')}</p>
      <p className="text-xs text-slate-600">{t('trend.empty_hint')}</p>
    </div>
  );
}

export default function TrendCharts() {
  const { lang, t } = useLocale();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<TrendsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async (d: number) => {
    setLoading(true);
    setError(null);
    try {
      const result = await getTrends(d);
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load trends');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(days);
  }, [days, fetchData]);

  const isEmpty =
    !data ||
    (data.daily_scores.length === 0 &&
      data.dimension_trends.length === 0 &&
      data.repo_comparison.length === 0);

  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr + 'T00:00:00');
    return lang === 'zh'
      ? d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
      : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  return (
    <div className="space-y-6">
      {/* Section header + range selector */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">{t('trend.title')}</h2>
        <div className="flex gap-1 bg-surface-elevated rounded-lg p-1">
          {RANGE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setDays(opt.value)}
              className={`px-3 py-1 text-sm rounded-md transition-colors ${
                days === opt.value
                  ? 'bg-accent-blue/20 text-accent-blue font-medium'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-12 text-slate-400">
          <svg className="animate-spin h-5 w-5 mr-2" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          {t('trend.loading')}
        </div>
      )}

      {error && (
        <div className="text-center py-8 text-red-400 text-sm">{error}</div>
      )}

      {!loading && !error && isEmpty && <EmptyState />}

      {!loading && !error && !isEmpty && (
        <div className="space-y-6">
          <InsightSummary data={data!} days={days} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* ── Finding Trend (line chart) ── */}
            {data!.daily_scores.length > 0 && (
              <div className="card">
                <h3 className="font-semibold text-slate-200 mb-4">{t('trend.finding_trend')}</h3>
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={data!.daily_scores}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="date" tickFormatter={formatDate} stroke="#64748b" fontSize={12} />
                    <YAxis stroke="#64748b" fontSize={12} allowDecimals={false} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px', fontSize: '12px' }}
                      labelFormatter={formatDate}
                    />
                    <Line type="monotone" dataKey="total" stroke="#60a5fa" strokeWidth={2} dot={{ r: 3 }} name={t('trend.total')} />
                    <Line type="monotone" dataKey="critical" stroke={SEVERITY_COLORS.critical} strokeWidth={1.5} strokeDasharray="4 2" dot={false} name={t('trend.critical')} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* ── Dimension Trend (stacked area) ── */}
            {data!.dimension_trends.length > 0 && (
              <div className="card">
                <h3 className="font-semibold text-slate-200 mb-4">{t('trend.dimension_trend')}</h3>
                <ResponsiveContainer width="100%" height={260}>
                  <AreaChart data={data!.dimension_trends}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="date" tickFormatter={formatDate} stroke="#64748b" fontSize={12} />
                    <YAxis stroke="#64748b" fontSize={12} allowDecimals={false} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px', fontSize: '12px' }}
                      labelFormatter={formatDate}
                    />
                    <Legend iconType="circle" wrapperStyle={{ fontSize: '12px' }} />
                    <Area type="monotone" dataKey="efficiency" stackId="1" stroke={DIMENSION_COLORS.efficiency} fill={DIMENSION_COLORS.efficiency} fillOpacity={0.3} name={t('trend.efficiency')} />
                    <Area type="monotone" dataKey="security" stackId="1" stroke={DIMENSION_COLORS.security} fill={DIMENSION_COLORS.security} fillOpacity={0.3} name={t('trend.security')} />
                    <Area type="monotone" dataKey="cost" stackId="1" stroke={DIMENSION_COLORS.cost} fill={DIMENSION_COLORS.cost} fillOpacity={0.3} name={t('trend.cost')} />
                    <Area type="monotone" dataKey="errors" stackId="1" stroke={DIMENSION_COLORS.errors} fill={DIMENSION_COLORS.errors} fillOpacity={0.3} name={t('trend.errors')} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* ── Repo Comparison (horizontal bar) ── */}
            {data!.repo_comparison.length > 0 && (
              <div className="card lg:col-span-2">
                <h3 className="font-semibold text-slate-200 mb-4">{t('trend.repo_comparison')}</h3>
                <ResponsiveContainer width="100%" height={Math.max(200, data!.repo_comparison.length * 48)}>
                  <BarChart data={data!.repo_comparison} layout="vertical" margin={{ left: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" horizontal={false} />
                    <XAxis type="number" stroke="#64748b" fontSize={12} allowDecimals={false} />
                    <YAxis type="category" dataKey="repo" stroke="#64748b" fontSize={12} width={140} tick={{ fill: '#cbd5e1' }} />
                    <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px', fontSize: '12px' }} />
                    <Legend iconType="circle" wrapperStyle={{ fontSize: '12px' }} />
                    <Bar dataKey="critical" stackId="a" fill={SEVERITY_COLORS.critical} name={t('trend.critical')} />
                    <Bar dataKey="major" stackId="a" fill={SEVERITY_COLORS.major} name={t('trend.major')} />
                    <Bar dataKey="minor" stackId="a" fill={SEVERITY_COLORS.minor} name={t('trend.minor')} />
                    <Bar dataKey="info" stackId="a" fill={SEVERITY_COLORS.info} name={t('trend.info')} radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}