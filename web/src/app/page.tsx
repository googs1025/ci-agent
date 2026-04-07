import type { Metadata } from 'next';
import Link from 'next/link';
import { getDashboard } from '@/lib/api';
import StatCard from '@/components/StatCard';
import SeverityBadge from '@/components/SeverityBadge';
import type { ReportListItem, Severity } from '@/types';
import { format, parseISO } from 'date-fns';

export const metadata: Metadata = { title: 'Dashboard' };

// Revalidate every 60 seconds
export const revalidate = 60;

// ──────────────────────────────────────────────────────────
// Helper sub-components (server-side)
// ──────────────────────────────────────────────────────────

function BarRow({
  label,
  value,
  max,
  colorClass,
}: {
  label: string;
  value: number;
  max: number;
  colorClass: string;
}) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="w-24 shrink-0 text-sm text-slate-400 capitalize text-right">
        {label}
      </span>
      <div className="flex-1 bg-surface-elevated rounded-full h-3 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${colorClass}`}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${label}: ${value}`}
        />
      </div>
      <span className="w-10 shrink-0 text-sm text-slate-300 font-mono text-right">
        {value}
      </span>
    </div>
  );
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-red-500',
  major: 'bg-orange-400',
  minor: 'bg-yellow-400',
  info: 'bg-blue-400',
};

const DIMENSION_COLORS: Record<string, string> = {
  efficiency: 'bg-accent-blue',
  security: 'bg-accent-purple',
  cost: 'bg-accent-green',
  errors: 'bg-accent-red',
};

function StatusPill({ status }: { status: string }) {
  const cfg: Record<string, string> = {
    completed: 'bg-green-500/15 text-green-400',
    failed: 'bg-red-500/15 text-red-400',
    running: 'bg-blue-500/15 text-blue-400',
    pending: 'bg-slate-500/15 text-slate-400',
  };
  return (
    <span
      className={`badge capitalize ${cfg[status] ?? cfg.pending}`}
    >
      {status}
    </span>
  );
}

function formatDuration(ms: number | null): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ──────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────

export default async function DashboardPage() {
  let dashboard;
  try {
    dashboard = await getDashboard();
  } catch {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-slate-500">
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none" aria-hidden="true">
          <circle cx="24" cy="24" r="22" stroke="currentColor" strokeWidth="2" />
          <path d="M24 14v12M24 34v1" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
        </svg>
        <p className="text-lg font-medium text-slate-400">Could not reach the API server.</p>
        <p className="text-sm">Make sure the FastAPI backend is running at <code className="font-mono text-accent-purple">http://localhost:8000</code></p>
        <Link href="/analyze" className="btn-primary mt-2">
          Start an analysis anyway
        </Link>
      </div>
    );
  }

  const {
    repo_count,
    analysis_count,
    severity_distribution: sevDist,
    dimension_distribution: dimDist,
    recent_reports,
  } = dashboard;

  const totalFindings = Object.values(sevDist).reduce((a, b) => a + b, 0);
  const maxSev = Math.max(...Object.values(sevDist), 1);
  const maxDim = Math.max(...Object.values(dimDist), 1);

  return (
    <div className="space-y-8">
      {/* ── Page heading ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Dashboard</h1>
          <p className="text-slate-400 text-sm mt-1">
            Overview of your CI pipeline health
          </p>
        </div>
        <Link href="/analyze" className="btn-primary">
          + New Analysis
        </Link>
      </div>

      {/* ── Stat cards ── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="Repositories"
          value={repo_count}
          color="text-accent-blue"
          icon={
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <rect x="3" y="3" width="7" height="7" rx="1.5" fill="currentColor" opacity="0.8" />
              <rect x="3" y="13" width="7" height="7" rx="1.5" fill="currentColor" opacity="0.5" />
              <rect x="13" y="3" width="7" height="7" rx="1.5" fill="currentColor" opacity="0.6" />
              <rect x="13" y="13" width="7" height="7" rx="1.5" fill="currentColor" opacity="0.4" />
            </svg>
          }
        />
        <StatCard
          label="Total Analyses"
          value={analysis_count}
          color="text-accent-green"
          icon={
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M3 12h4l3-8 4 16 3-8h4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          }
        />
        <StatCard
          label="Total Findings"
          value={totalFindings}
          color="text-accent-yellow"
          subLabel={`${sevDist.critical ?? 0} critical`}
          icon={
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 3L2 20h20L12 3z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
              <path d="M12 10v5M12 17v1" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          }
        />
      </div>

      {/* ── Distribution charts ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Severity distribution */}
        <div className="card space-y-4">
          <h2 className="font-semibold text-slate-200">Severity Distribution</h2>
          <div className="space-y-3">
            {(['critical', 'major', 'minor', 'info'] as Severity[]).map((sev) => (
              <BarRow
                key={sev}
                label={sev}
                value={sevDist[sev] ?? 0}
                max={maxSev}
                colorClass={SEVERITY_COLORS[sev]}
              />
            ))}
          </div>
        </div>

        {/* Dimension distribution */}
        <div className="card space-y-4">
          <h2 className="font-semibold text-slate-200">Dimension Distribution</h2>
          <div className="space-y-3">
            {(['efficiency', 'security', 'cost', 'errors'] as const).map((dim) => (
              <BarRow
                key={dim}
                label={dim}
                value={dimDist[dim] ?? 0}
                max={maxDim}
                colorClass={DIMENSION_COLORS[dim]}
              />
            ))}
          </div>
        </div>
      </div>

      {/* ── Recent reports ── */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-slate-200">Recent Reports</h2>
          <Link
            href="/reports"
            className="text-sm text-accent-blue hover:underline"
          >
            View all
          </Link>
        </div>

        {recent_reports.length === 0 ? (
          <p className="text-slate-500 text-sm py-6 text-center">
            No analyses yet.{' '}
            <Link href="/analyze" className="text-accent-blue hover:underline">
              Start one now
            </Link>
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" aria-label="Recent reports">
              <thead>
                <tr className="border-b border-surface-border">
                  <th scope="col" className="pb-3 text-left font-semibold text-slate-400">Repository</th>
                  <th scope="col" className="pb-3 text-left font-semibold text-slate-400 hidden sm:table-cell">Date</th>
                  <th scope="col" className="pb-3 text-left font-semibold text-slate-400">Status</th>
                  <th scope="col" className="pb-3 text-right font-semibold text-slate-400">Findings</th>
                  <th scope="col" className="pb-3 text-right font-semibold text-slate-400 hidden md:table-cell">Duration</th>
                </tr>
              </thead>
              <tbody>
                {recent_reports.slice(0, 5).map((r: ReportListItem) => (
                  <tr
                    key={r.id}
                    className="border-b border-surface-border last:border-0 table-row-hover"
                  >
                    <td className="py-3 pr-4">
                      <Link
                        href={`/reports/${r.id}`}
                        className="font-medium text-slate-200 hover:text-accent-blue transition-colors"
                      >
                        {r.repo_owner}/{r.repo_name}
                      </Link>
                    </td>
                    <td className="py-3 pr-4 text-slate-400 hidden sm:table-cell whitespace-nowrap">
                      {format(parseISO(r.created_at), 'MMM d, yyyy')}
                    </td>
                    <td className="py-3 pr-4">
                      <StatusPill status={r.status} />
                    </td>
                    <td className="py-3 text-right font-mono text-slate-300">
                      {r.finding_count}
                    </td>
                    <td className="py-3 text-right text-slate-400 hidden md:table-cell">
                      {formatDuration(r.duration_ms)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
