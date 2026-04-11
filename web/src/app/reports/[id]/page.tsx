import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { getReport } from '@/lib/api';
import { format, parseISO } from 'date-fns';
import type { Dimension, Finding, Severity } from '@/types';
import SeverityBadge from '@/components/SeverityBadge';
import ReportTabs from './ReportTabs';

// ──────────────────────────────────────────────────────────
// Metadata
// ──────────────────────────────────────────────────────────

export async function generateMetadata({
  params,
}: {
  params: { id: string };
}): Promise<Metadata> {
  try {
    const report = await getReport(params.id);
    return { title: `${report.repo_owner}/${report.repo_name} — Report` };
  } catch {
    return { title: 'Report' };
  }
}

// ──────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────

function formatDuration(ms: number | null): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, string> = {
    completed: 'bg-green-500/15 text-green-400',
    failed: 'bg-red-500/15 text-red-400',
    running: 'bg-blue-500/15 text-blue-400',
    pending: 'bg-slate-500/15 text-slate-400',
  };
  return (
    <span className={`badge capitalize ${cfg[status] ?? cfg.pending}`}>
      {status}
    </span>
  );
}

function SeverityCount({ severity, count }: { severity: Severity; count: number }) {
  if (count === 0) return null;
  return (
    <div className="flex items-center gap-1.5">
      <SeverityBadge severity={severity} dotOnly />
      <span className="text-sm font-semibold text-slate-300">{count}</span>
      <span className="text-xs text-slate-500 capitalize">{severity}</span>
    </div>
  );
}

// ──────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────

export default async function ReportDetailPage({
  params,
}: {
  params: { id: string };
}) {
  let report;
  try {
    report = await getReport(params.id);
  } catch {
    notFound();
  }

  const {
    repo_owner,
    repo_name,
    created_at,
    status,
    duration_ms,
    summary_md,
    error_message,
    findings,
  } = report;

  // Count by severity
  const sevCounts = findings.reduce(
    (acc, f) => { acc[f.severity] = (acc[f.severity] ?? 0) + 1; return acc; },
    {} as Record<Severity, number>,
  );

  // Group by dimension
  const byDimension = findings.reduce(
    (acc, f) => { (acc[f.dimension] ??= []).push(f); return acc; },
    {} as Record<Dimension, Finding[]>,
  );

  // Build dimension list
  const dimensionKeys = Array.from(new Set(findings.map((f) => f.dimension)));
  const KNOWN_ORDER = ['efficiency', 'security', 'cost', 'errors'];
  const ordered = [
    ...KNOWN_ORDER.filter((k) => dimensionKeys.includes(k)),
    ...dimensionKeys.filter((k) => !KNOWN_ORDER.includes(k)),
  ];
  const dimensionsToShow = ordered.length > 0 ? ordered : KNOWN_ORDER;
  const dimensions = dimensionsToShow.map((key) => ({
    key,
    label: key.charAt(0).toUpperCase() + key.slice(1),
    count: (byDimension[key] ?? []).length,
  }));

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link
        href="/reports"
        className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200 transition-colors"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M10 12L6 8l4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        All Reports
      </Link>

      {/* ── Header card ── */}
      <div className="card">
        <div className="flex flex-col sm:flex-row sm:items-start gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-xl font-bold text-white truncate">
                {repo_owner}/{repo_name}
              </h1>
              <StatusBadge status={status} />
            </div>
            <p className="text-sm text-slate-400 mt-1">
              Analyzed {format(parseISO(created_at), "MMM d, yyyy 'at' HH:mm")}
              {duration_ms != null && <> &middot; {formatDuration(duration_ms)}</>}
            </p>
          </div>
          <div className="flex items-center gap-4 flex-wrap">
            {(['critical', 'major', 'minor', 'info'] as Severity[]).map((sev) => (
              <SeverityCount key={sev} severity={sev} count={sevCounts[sev] ?? 0} />
            ))}
            {findings.length === 0 && <span className="text-sm text-slate-500">No findings</span>}
          </div>
        </div>
      </div>

      {/* ── Error message ── */}
      {status === 'failed' && error_message && (
        <div
          role="alert"
          className="flex items-start gap-3 bg-red-500/10 border border-red-500/25 rounded-xl px-5 py-4 text-sm text-red-400"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="shrink-0 mt-0.5">
            <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" />
            <path d="M12 8v5M12 15v1" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <div>
            <p className="font-semibold text-red-300 mb-0.5">Analysis failed</p>
            <p>{error_message}</p>
          </div>
        </div>
      )}

      {/* ── Success empty state ── */}
      {status === 'completed' && findings.length === 0 && !error_message && (
        <div className="card text-center py-12 text-slate-500">
          <svg width="40" height="40" viewBox="0 0 40 40" fill="none" aria-hidden="true" className="mx-auto mb-3 text-green-500">
            <circle cx="20" cy="20" r="18" stroke="currentColor" strokeWidth="2" />
            <path d="M12 20l6 6 10-12" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <p className="font-medium text-slate-300">No findings — your pipeline looks great!</p>
        </div>
      )}

      {/* ── Two-column: sidebar nav + summary + findings ── */}
      {(findings.length > 0 || summary_md) && (
        <ReportTabs
          dimensions={dimensions}
          byDimension={byDimension}
          summaryMd={summary_md}
          sevCounts={sevCounts}
        />
      )}
    </div>
  );
}
